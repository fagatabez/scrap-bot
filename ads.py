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


# ---------------------------------------------------------------- popup boost
def _components(mask, min_area=1):
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area >= min_area:
            out.append((x, y, w, h, area))
    return out


def find_green_button(img):
    """Zielony przycisk z bialym napisem - zwraca (x, y) srodka albo None.

    W popupie "Szybsze Beczki" zielony przycisk "Tak!" ma bialy napis.
    Tlo gry tez jest zielone, wiec odsiewamy: szerokosc 10-55% ekranu,
    wypelnienie > 75%, proporcje jak przycisk (1.3-5) i bialy tekst w srodku.
    """
    h, w = img.shape[:2]
    scale = min(1.0, 480.0 / max(w, 1))
    small = (cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))),
                        interpolation=cv2.INTER_AREA) if scale < 1.0 else img)
    sh, sw = small.shape[:2]
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([45, 130, 90]), np.array([90, 255, 255]))
    green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    best = None
    for x, y, bw, bh, area in _components(green, 50):
        if not (0.10 * sw <= bw <= 0.55 * sw):
            continue
        if not (0.04 * sh <= bh <= 0.20 * sh):
            continue
        if area < 0.75 * bw * bh:
            continue
        if not (1.3 < bw / max(bh, 1) < 5.0):
            continue
        crop = hsv[y:y + bh, x:x + bw]
        if crop.size == 0:
            continue
        white = cv2.inRange(crop, np.array([0, 0, 190]), np.array([180, 70, 255]))
        if int((white > 0).sum()) < 0.008 * bw * bh:
            continue                       # brak bialego napisu - to tlo gry
        cx, cy = x + bw // 2, y + bh // 2
        if best is None or area > best[0]:
            best = (area, cx, cy)
    if best is None:
        return None
    return (int(best[1] / scale), int(best[2] / scale))


def find_boost_button(img):
    """Przycisk "Tak!" w popupie "Szybsze Beczki" albo None.

    Rozpoznanie jest bezpieczne: musi byc zielony przycisk z bialym napisem
    ORAZ czerwony przycisk tego samego rozmiaru w tym samym rzedu (lewy
    przycisk "Nie"). Takie okno nie jest przypadkiem sklepu - tylko oferta
    "obejrzyj reklame i zdobywaj beczki 10x szybciej".
    """
    green = find_green_button(img)
    if not green:
        return None
    h, w = img.shape[:2]
    scale = min(1.0, 480.0 / max(w, 1))
    small = (cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))),
                        interpolation=cv2.INTER_AREA) if scale < 1.0 else img)
    sh, sw = small.shape[:2]
    gx, gy = green[0] * scale, green[1] * scale
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, np.array([0, 130, 110]), np.array([12, 255, 255])) | \
        cv2.inRange(hsv, np.array([168, 130, 110]), np.array([180, 255, 255]))
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    for x, y, bw, bh, area in _components(red, 200):
        if not (0.08 * sw <= bw <= 0.5 * sw):
            continue
        if abs(bh - 70 * sh / 558.0) > 0.10 * sh:
            continue
        if x > gx:                        # czerwony musi byc na lewo
            continue
        if abs((y + bh // 2) - gy) > 0.12 * sh:
            continue
        return green
    return None


def take_boost(io, pos=None):
    """Kliknie "Tak!" w popupie boostu, zamknie reklame, wraca do gry."""
    if pos is None:
        pos = find_boost_button(io.grab())
    if not pos:
        return False
    io.tap(*pos)
    time.sleep(1.6)
    return close_after_ad(io)


# ---------------------------------------------------------------- zamykanie
def find_close_button(img):
    """Czerwony/jasny X zamykajacy - zwraca (x, y) albo None.

    Szukamy w gornej polowie ekranu elementu o ksztalcie zblizonym do kwadratu,
    ktory jest czerwony albo bardzo jasny na ciemnym tle (typowe X-y reklam).
    Czerwony jest zawsze silniejszym kandydatem - biale litery napisow (np.
    "Event!") tez wygladaja jak male kwadraty, wiec bez tego waga wygrywal
    by ktorys liter napisu zamiast prawdziwego X-a.
    """
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, np.array([0, 120, 100]), np.array([12, 255, 255])) | \
        cv2.inRange(hsv, np.array([168, 120, 100]), np.array([180, 255, 255]))
    white = cv2.inRange(hsv, np.array([0, 0, 205]), np.array([180, 45, 255]))
    best = None
    for mask, weight, max_w, max_h in ((red, 6.0, 0.16, 0.13),
                                       (white, 1.0, 0.12, 0.08)):
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            if not (8 <= bw <= w * max_w and 8 <= bh <= h * max_h):
                continue
            if not (0.5 < bw / max(bh, 1) < 2.0):
                continue
            if area < 0.3 * bw * bh:
                continue
            cx, cy = x + bw // 2, y + bh // 2
            if cy > h * 0.5:                   # X-y siedza na gorze ekranu
                continue
            # wolimy prawy gorny rog (tam najczesciej jest X reklamy)
            score = area * weight - 0.5 * cx
            if best is None or score > best[0]:
                best = (score, cx, cy)
    return (best[1], best[2]) if best else None


def close_after_ad(io, tries=25):
    """Reklama wlasnie leci: czekamy az sie skonczy i wracamy do gry."""
    for i in range(tries):
        frame = io.grab()
        if looks_like_game(frame):
            return True
        pos = find_close_button(frame)
        if pos:
            io.tap(*pos)
            time.sleep(0.9)
            continue
        if i % 3 == 2:
            io.key(4)                       # WSTECZ zamyka wiekszosc reklam
            time.sleep(0.9)
        else:
            time.sleep(1.0)
    return False


def close_screen(io, tries_corners=True, try_boost=True):
    """Proboje zamknac to, co zaslania gre. True = chyba sie udalo."""
    frame = io.grab()
    if looks_like_game(frame):
        return True

    # Popup oferty "Szybsze Beczki": klikamy "Tak!" (obejrzyj reklame) i
    # wchodzimy w boost na 10 minut, zamiast zamykac okno krzyzykiem.
    if try_boost:
        pos = find_boost_button(frame)
        if pos:
            io.tap(*pos)
            time.sleep(1.6)
            if close_after_ad(io):
                return True
            return close_screen(io, tries_corners, try_boost=False)

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
        self.popup = bool(cfg.get("popup", True))   # wykrywac "Tak!" w oknie
        self.clicks = 0
        self.last = 0.0
        self.enabled = bool(self.button) and self.idle > 0

    def due(self, idle_for):
        if time.time() - self.last < self.cooldown:
            return False
        return self.enabled and idle_for >= self.idle

    def trigger(self, io):
        """Klika przycisk, czeka na reklame, zamyka ja, wraca do gry."""
        frame = io.grab()
        # 1) popup "Szybsze Beczki" z zielonym "Tak!"
        pos = find_boost_button(frame)
        if pos:
            self.last = time.time()
            io.tap(*pos)
            time.sleep(1.6)
            ok = close_after_ad(io)
            if ok:
                self.clicks += 1
            return ok
        # 2) przycisk z config.json (ustawiony przez pick.py)
        rect = board_rect(frame)
        if not rect or not self.button:
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
