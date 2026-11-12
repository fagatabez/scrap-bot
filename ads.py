"""Pilnowanie ekranu: reklama, popup, brak planszy + przycisk 'szybsze beczki'.

Zasada: bot laczy beczki tylko wtedy, gdy na ekranie widzi plansze gry.
Gdy plansza zniknie (reklama nagrody, popup, ekran ulepszen), bot probuje
zamknac to, co wisi: czerwony X, klawisz WSTECZ, a na koncu rogi ekranu.
Kazda proba jest sprawdzana - jesli plansza wrocila, konczymy.

Wspolrzedne przycisku boost sa w ulamkach planszy (0..1), zeby dzialaly przy
kazdej rozdzielczosci. Ustaw je przez `python pick.py` albo recznie w config.json.
"""
import json
import os
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")


# ---------------------------------------------------------------- config
def load():
    try:
        with open(CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save(data):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------- ekran gry
def board_rect(img):
    """Prostokat planszy: najwiekszy jednolity obszar tla. None gdy brak."""
    try:
        import pairs
        return pairs.playfield_rect(img)
    except Exception:
        return None


def looks_like_game(img):
    """Plansza gry: jest duzy obszar tla o stalym stosunku bokow."""
    return board_rect(img) is not None


# ---------------------------------------------------------------- zamykanie
def find_close_button(img):
    """Czerwony/jasny X zamykajacy - zwraca (x, y) albo None.

    Szukamy w gornej polowie ekranu elementu o ksztalcie zblizonym do kwadratu,
    ktory jest czerwony albo bardzo jasny na ciemnym tle (typowe X-y reklam).
    """
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, np.array([0, 120, 100]), np.array([12, 255, 255])) | \
        cv2.inRange(hsv, np.array([168, 120, 100]), np.array([180, 255, 255]))
    white = cv2.inRange(hsv, np.array([0, 0, 205]), np.array([180, 45, 255]))
    mask = cv2.morphologyEx(red | white, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    best = None
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if not (8 <= bw <= w * 0.12 and 8 <= bh <= h * 0.08):
            continue
        if not (0.5 < bw / max(bh, 1) < 2.0):
            continue
        if area < 0.3 * bw * bh:
            continue
        cx, cy = x + bw // 2, y + bh // 2
        if cy > h * 0.5:                       # X-y siedza na gorze ekranu
            continue
        # wolimy prawy gorny rog (tam najczesciej jest X reklamy)
        score = area - 0.5 * cx
        if best is None or score > best[0]:
            best = (score, cx, cy)
    return (best[1], best[2]) if best else None


def close_screen(io, tries_corners=True):
    """Proboje zamknac to, co zaslania gre. True = chyba sie udalo."""
    frame = io.grab()
    if looks_like_game(frame):
        return True

    pos = find_close_button(frame)
    if pos:
        io.tap(*pos)
        time.sleep(0.7)
        if looks_like_game(io.grab()):
            return True

    io.key(4)                                  # WSTECZ zamyka wiekszosc reklam
    time.sleep(0.9)
    if looks_like_game(io.grab()):
        return True

    if tries_corners:
        h, w = frame.shape[:2]
        for fx, fy in ((0.94, 0.05), (0.06, 0.05), (0.94, 0.95), (0.5, 0.95)):
            io.tap(int(w * fx), int(h * fy))
            time.sleep(0.6)
            if looks_like_game(io.grab()):
                return True
    return False


# ---------------------------------------------------------------- boost
class Boost:
    """Klika 'szybsze beczki' (obejrzenie reklamy) i wraca do laczenia.

    button: [fx, fy] w ulamkach planszy gry - ustaw przez pick.py
    idle:   po ilu sekundach bez pary kliknac (0 = wylaczone)
    cooldown: minimalny odstep miedzy probami (s)
    """

    def __init__(self, cfg=None):
        cfg = cfg if cfg is not None else load().get("boost", {})
        self.button = cfg.get("button")
        self.idle = float(cfg.get("idle", 0) or 0)
        self.cooldown = float(cfg.get("cooldown", 120) or 120)
        self.clicks = 0
        self.last = 0.0
        self.enabled = bool(self.button) and self.idle > 0

    def due(self, idle_for):
        return (self.enabled and idle_for >= self.idle
                and time.time() - self.last >= self.cooldown)

    def trigger(self, io):
        """Klika przycisk, czeka na reklame, zamyka ja, wraca do gry."""
        rect = board_rect(io.grab())
        if not rect:
            return False
        x, y, w, h = rect
        px = int(x + self.button[0] * w)
        py = int(y + self.button[1] * h)
        self.last = time.time()
        io.tap(px, py)
        time.sleep(1.2)

        # reklama moze sie ladowac - dajemy jej kilka sekund i zamykamy
        for _ in range(12):
            frame = io.grab()
            if looks_like_game(frame):
                self.clicks += 1
                return True
            pos = find_close_button(frame)
            if pos:
                io.tap(*pos)
            time.sleep(1.0)
        ok = close_screen(io)
        if ok:
            self.clicks += 1
        return ok

    def info(self):
        return {"enabled": self.enabled, "clicks": self.clicks,
                "button": self.button, "idle": self.idle}
