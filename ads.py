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
CROWN = os.path.join(HERE, "assets", "boost_crown.png")
TITLE = os.path.join(HERE, "assets", "boost_title.png")
# szerokosc zielonego "Tak!" na zrzucie referencyjnym (481 px szerokosci)
CROWN_REF_BTN_W = 172.0


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


def has_popup(img, min_frac=0.05):
    """Czy na ekranie jest okno (reklama, popup, anty-macro).

    Okna gry sa jasnoszare (RGB w okolicach 190) - na planszy takiego koloru
    praktycznie nie ma (<1%). Wazne: pod oknem plansza jest przyciemniona,
    wiec wyglada jak sztorm - bez tego sprawdzenia bot zamiast obsluzyc okno
    zaczalby zbierac scrapa.
    """
    b, g, r = cv2.split(img.astype(np.int16))
    mask = (np.abs(b - g) < 12) & (np.abs(g - r) < 12) & (b > 185) & (b < 235)
    return float(mask.mean()) > min_frac


# ---------------------------------------------------------------- popup boost
def _components(mask, min_area=1):
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area >= min_area:
            out.append((x, y, w, h, area))
    return out


def _green_boxes(img):
    """Zielone przyciski (x, y, w, h) - z bialym napisem, jak "Tak!"."""
    h, w = img.shape[:2]
    scale = min(1.0, 480.0 / max(w, 1))
    small = (cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))),
                        interpolation=cv2.INTER_AREA) if scale < 1.0 else img)
    sh, sw = small.shape[:2]
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([45, 130, 90]), np.array([90, 255, 255]))
    green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    out = []
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
        out.append((int(x / scale), int(y / scale), int(bw / scale), int(bh / scale)))
    return out


def find_green_button(img):
    """Zielony przycisk z bialym napisem - zwraca (x, y) srodka albo None."""
    boxes = _green_boxes(img)
    if not boxes:
        return None
    x, y, w, h = max(boxes, key=lambda b: b[2] * b[3])
    return (x + w // 2, y + h // 2)


def find_boost_crown(img, btn_w):
    """Czy w kadrze jest zlota korona z okna "Szybsze Beczki"?

    Korona to jedyny element tego okna, ktorego nie ma w innych popupach
    (w grze jest ~10 roznych okien z zielonymi przyciskami). Szablon
    dopasowujemy w skali zielonego "Tak!" - dzieki temu dziala na kazdej
    rozdzielczosci telefonu.
    """
    tmpl = cv2.imread(CROWN, cv2.IMREAD_GRAYSCALE)
    if tmpl is None:
        return None
    scale = btn_w / CROWN_REF_BTN_W
    if abs(scale - 1.0) > 0.03:
        tmpl = cv2.resize(tmpl, (max(4, int(tmpl.shape[1] * scale)),
                                 max(4, int(tmpl.shape[0] * scale))),
                          interpolation=cv2.INTER_NEAREST)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(hsv, np.array([18, 90, 120]), np.array([38, 255, 255]))
    yellow = cv2.morphologyEx(yellow, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    if yellow.shape[0] < tmpl.shape[0] or yellow.shape[1] < tmpl.shape[1]:
        return None
    res = cv2.matchTemplate(yellow, tmpl, cv2.TM_CCORR_NORMED)
    _, mx, _, loc = cv2.minMaxLoc(res)
    return mx, loc, tmpl.shape[1], tmpl.shape[0]


def _title_profile(band, buckets=24):
    """Profil tuszu w linijce tytulu (kolumny -> 24 liczby, znormalizowane)."""
    counts = band.sum(axis=1)
    lines, cur = [], None
    for i, c in enumerate(counts):
        if c > 2:
            cur = [i, i] if cur is None else [cur[0], i]
        elif cur is not None:
            lines.append(tuple(cur))
            cur = None
    if cur:
        lines.append(tuple(cur))
    if not lines:
        return None
    ty0, ty1 = max(lines, key=lambda ln: ln[1] - ln[0])   # tytul = najwyzsze litery
    tband = band[ty0:ty1 + 1]
    cols = np.where(tband.sum(axis=0) > 0)[0]
    if len(cols) == 0:
        return None
    prof = tband[:, int(cols.min()):int(cols.max()) + 1].sum(axis=0).astype(np.float32)
    edges = np.linspace(0, len(prof), buckets + 1).astype(int)
    out = np.array([prof[a:b].sum() for a, b in zip(edges[:-1], edges[1:])], np.float32)
    nrm = float(np.linalg.norm(out))
    return out / nrm if nrm else out


_TITLE_REF = None


def _title_reference():
    """Profil tytulu 'Szybsze Beczki' z szablonu (assets/boost_title.png)."""
    global _TITLE_REF
    if _TITLE_REF is None:
        tmpl = cv2.imread(TITLE, cv2.IMREAD_GRAYSCALE)
        prof = None
        if tmpl is not None:
            prof = _title_profile((tmpl > 100).astype(np.uint8))
        _TITLE_REF = prof if prof is not None else False
    return _TITLE_REF if _TITLE_REF is not False else None


def title_is_boost(img, crown_bottom, btn_top, x0=0, x1=None):
    """Czy tytul okna to "Szybsze Beczki"?

    W oknie "Auto Łączenie" jest ta sama korona i ten sam uklad przyciskow -
    roznia je tylko napis. Wiec porownujemy profil tuszu tytulu (ksztalt
    liter) z szablonem. Tanie: 24 liczby, zero dopasowania wzorca.
    """
    ref = _title_reference()
    if ref is None:
        return True                      # brak szablonu - nie blokujemy bota
    h, w = img.shape[:2]
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    dark = (g < 140)
    top = max(0, int(crown_bottom))
    bottom = min(h, int(btn_top) - 4)
    x0 = max(0, int(x0))
    x1 = w if x1 is None else min(w, int(x1))
    if bottom - top < 10 or x1 - x0 < 20:
        return False
    prof = _title_profile(dark[top:bottom, x0:x1])
    if prof is None:
        return False
    sim = float(np.dot(ref, prof) / (np.linalg.norm(ref) * np.linalg.norm(prof) + 1e-9))
    return sim >= 0.97


def find_boost_button(img):
    """Przycisk "Tak!" w popupie "Szybsze Beczki" albo None.

    Rozpoznanie jest bezpieczne: musi byc zielony przycisk z bialym napisem,
    czerwony przycisk tego samego rozmiaru w tym samym rzedu (lewy "Nie"),
    zlota korona z tego okna ORAZ tytul "Szybsze Beczki" (nie "Auto Laczenie"
    - tam jest ta sama korona i ten sam uklad, ale inne okno).
    """
    green = find_green_button(img)
    if not green:
        return None
    boxes = _green_boxes(img)
    btn = max(boxes, key=lambda b: b[2] * b[3])
    gx, gy = green
    h, w = img.shape[:2]
    scale = min(1.0, 480.0 / max(w, 1))
    small = (cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))),
                        interpolation=cv2.INTER_AREA) if scale < 1.0 else img)
    sh, sw = small.shape[:2]
    sgx, sgy = gx * scale, gy * scale
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, np.array([0, 130, 110]), np.array([12, 255, 255])) | \
        cv2.inRange(hsv, np.array([168, 130, 110]), np.array([180, 255, 255]))
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    ok_red = False
    red_x0 = 0
    for x, y, bw, bh, area in _components(red, 200):
        if not (0.08 * sw <= bw <= 0.5 * sw):
            continue
        if abs(bh - 70 * sh / 558.0) > 0.10 * sh:
            continue
        if x > sgx:                       # czerwony musi byc na lewo
            continue
        if abs((y + bh // 2) - sgy) > 0.12 * sh:
            continue
        ok_red = True
        red_x0 = int(x / scale)
        break
    if not ok_red:
        return None
    crown = find_boost_crown(img, btn[2])
    if not crown:
        return None
    score, (cx, cy), tw, th = crown
    if score < 0.72:
        return None
    # korona jest nad przyciskami, mniej wiecej w tym samym miejscu w poziomie
    if cy + th > gy - 0.02 * h:
        return None
    if abs((cx + tw / 2) - gx) > 0.45 * w:
        return None
    # tytul: "Szybsze Beczki" a nie "Auto Laczenie"
    if not title_is_boost(img, cy + th, btn[1], red_x0, btn[0] + btn[2]):
        return None
    return green


def _green_button_width(img):
    """Szerokosc zielonego przycisku "Tak!" w pikselach (do skali szablonu)."""
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([45, 130, 90]), np.array([90, 255, 255]))
    green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    best = 0
    for x, y, bw, bh, area in _components(green, 50):
        if not (0.10 * w <= bw <= 0.55 * w):
            continue
        if area < 0.75 * bw * bh:
            continue
        if not (1.3 < bw / max(bh, 1) < 5.0):
            continue
        best = max(best, bw)
    return best


def find_red_button(img):
    """Czerwony przycisk "Nie" w popupie (obok zielonego "Tak!")."""
    h, w = img.shape[:2]
    green = find_green_button(img)
    if not green:
        return None
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, np.array([0, 130, 110]), np.array([12, 255, 255])) | \
        cv2.inRange(hsv, np.array([168, 130, 110]), np.array([180, 255, 255]))
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    best = None
    for x, y, bw, bh, area in _components(red, 200):
        if not (0.08 * w <= bw <= 0.5 * w):
            continue
        if not (0.03 * h <= bh <= 0.16 * h):
            continue
        if not (1.3 < bw / max(bh, 1) < 5.0):
            continue
        if x > green[0]:                   # musi byc na lewo od "Tak!"
            continue
        cx, cy = x + bw // 2, y + bh // 2
        if best is None or area > best[0]:
            best = (area, cx, cy)
    return (best[1], best[2]) if best else None


def find_boost_icon(img, board=None):
    """Zlota koronka 'szybsze beczki' w prawym gornym rogu gry.

    W grze to zolta korona na niebieskim przycisku, nad prawa gora planszy.
    (W popupie jest inny zolty znak - ikona "A+" - wiec wymagamy, zeby
    korona byla nad plansza gry i miala ksztalt korony, a nie kwadratu.)
    """
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(hsv, np.array([18, 120, 140]), np.array([38, 255, 255]))
    yellow = cv2.morphologyEx(yellow, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    best = None
    for x, y, bw, bh, area in _components(yellow, 60):
        if x < 0.60 * w:                   # prawa polowa ekranu
            continue
        if y > 0.30 * h:                  # gora ekranu
            continue
        if not (0.02 * w <= bw <= 0.16 * w):
            continue
        if not (0.012 * h <= bh <= 0.10 * h):
            continue
        if not (1.12 < bw / max(bh, 1) < 1.9):
            continue
        cx, cy = x + bw // 2, y + bh // 2
        if board is not None:
            bx, by, bw2, bh2 = board
            if cy > by:                   # musi byc NAD plansza
                continue
            if not (bx - 0.12 * bw2 <= cx <= bx + 1.08 * bw2):
                continue
        if best is None or area > best[0]:
            best = (area, cx, cy)
    return (best[1], best[2]) if best else None


def watch_offer(io):
    """Kliknie koronke eventow i obsluzy oferte.

    Zwraca: 'tak' (obejrzano reklame = boost), 'nie' (odrzucono oferte),
    None (nie bylo oferty).
    """
    frame = io.grab()
    board = board_rect(frame)
    pos = find_boost_icon(frame, board)
    if not pos:
        return None
    io.tap(*pos)
    time.sleep(1.2)

    frame = io.grab()
    tak = find_boost_button(frame)          # "Szybsze Beczki" - chcemy to
    if tak:
        io.tap(*tak)
        time.sleep(1.6)
        close_after_ad(io)
        return "tak"
    nie = find_red_button(frame)            # inne okno (np. "Auto Laczenie")
    if nie:
        io.tap(*nie)
        time.sleep(0.9)
        return "nie"
    return None


# ---------------------------------------------------------------- anty-macro
def _event_panel(img):
    """Panel 'Event' (dialog anty-macro): jasnoszare okno z niebieskim '!'."""
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, np.array([100, 110, 90]), np.array([132, 255, 255]))
    blue = cv2.morphologyEx(blue, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    mark = None
    for x, y, bw, bh, area in _components(blue, 60):
        if not (0.015 * w <= bw <= 0.10 * w):
            continue
        if not (0.010 * h <= bh <= 0.08 * h):
            continue
        if abs(bw / max(bh, 1) - 1.0) > 0.4:
            continue
        if mark is None or area > mark[4]:
            mark = (x, y, bw, bh, area)
    if mark is None:
        return None
    mx, my, mw, mh, _ = mark
    # jasnoszare tlo panelu (kolor okna gry jest zielony)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    light = ((g > 190) & (g < 235)).astype(np.uint8) * 255
    light = cv2.morphologyEx(light, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(light, 8)
    best = None
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        if area < 0.01 * h * w:
            continue
        if x > mx + mw or x + bw < mx:            # panel musi obejmowac '!'
            continue
        if y > my + mh or y + bh < my - 0.02 * h:
            continue
        if best is None or area > best[4]:
            best = (x, y, bw, bh, area)
    if best is None:
        return None
    x, y, bw, bh, _ = best
    x0 = min(x, mx)
    y0 = min(y, my)
    x1 = max(x + bw, mx + mw)
    y1 = max(y + bh, my + mh)
    return x0, y0, x1 - x0, y1 - y0


def _blob_color(img, box):
    """Typowy kolor plamy (kolorowy sredni hue + median nasycenia)."""
    x, y, w, h = box
    crop = img[y:y + h, x:x + w]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    s = hsv[:, :, 1].astype(np.float32)
    v = hsv[:, :, 2].astype(np.float32)
    m = (s > 25) & (v > 40)
    if int(m.sum()) < 4:
        return None
    hues = hsv[:, :, 0][m].astype(np.float32)
    sats = s[m]
    ang = hues * (2 * np.pi / 180.0)
    mean_h = (np.arctan2(np.sin(ang).mean(), np.cos(ang).mean()) * 180 / (2 * np.pi)) % 180
    return float(mean_h), float(np.median(sats))


def find_blue_button(img, panel=None):
    """Niebieski przycisk nagrody na dole panelu (zasluzone magnety)."""
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, np.array([100, 110, 90]), np.array([132, 255, 255]))
    blue = cv2.morphologyEx(blue, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    x0, y0, x1, y1 = panel if panel else (0, 0, w, h)
    best = None
    for x, y, bw, bh, area in _components(blue, 100):
        if x < x0 or x + bw > x1 or y < y0 or y + bh > y1:
            continue
        if bw < 0.10 * (x1 - x0) or bh > 0.16 * (y1 - y0):
            continue
        if y < y0 + 0.6 * (y1 - y0):       # nagroda jest na dole
            continue
        cx, cy = x + bw // 2, y + bh // 2
        if best is None or area > best[0]:
            best = (area, cx, cy)
    return (best[1], best[2]) if best else None


def solve_anti_macro(io, frame=None, verbose=True):
    """Dialog anty-macro: zaznacz pole z szukana beczka i odbierz nagrode.

    Wariant z beczkami (od wersji 6.0) da sie rozwiazac po kolorze: szukana
    beczka jest w prawym gornym rogu napisu, a w siatce 3x3 lezy 9 innych.
    Wariant z liczbami wymaga OCR - wtedy bot nic nie klika i czeka.
    """
    frame = frame if frame is not None else io.grab()
    panel = _event_panel(frame)
    if not panel:
        return False
    px, py, pw, ph = panel
    h, w = frame.shape[:2]
    crop = frame[py:py + ph, px:px + pw]
    ch, cw = crop.shape[:2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

    def blobs(mask, min_area):
        return _components(mask.astype(np.uint8) * 255, min_area)

    strong = (hsv[:, :, 1] > 25) & (hsv[:, :, 2] > 40)
    is_blue = (hsv[:, :, 0] > 95) & (hsv[:, :, 0] < 135) & (hsv[:, :, 1] > 90)

    # 1) niebieski '!' w prawym gornym rogu panelu
    mark = None
    for x, y, bw, bh, area in blobs(is_blue, 40):
        if y > 0.16 * ch or x < 0.7 * cw:
            continue
        if mark is None or area > mark[4]:
            mark = (x, y, bw, bh, area)
    # 2) szukana beczka: pod '!' (moze byc ciemna, wiec bez zamykania)
    target = None
    y_from = 0 if mark is None else mark[1] + mark[3]
    for x, y, bw, bh, area in blobs(strong, 10):
        if x < 0.70 * cw or y < y_from or y > y_from + 0.26 * ch:
            continue
        if is_blue[y:y + bh, x:x + bw].mean() > 0.4:
            continue
        col = _blob_color(crop, (x, y, bw, bh))
        if col is None:
            continue
        if target is None or y < target[1]:
            target = (x, y, bw, bh, col)
    # 3) beczki w siatce 3x3
    cells = []
    for x, y, bw, bh, area in blobs(strong, 15):
        if y < 0.18 * ch or y > 0.78 * ch:
            continue
        if is_blue[y:y + bh, x:x + bw].mean() > 0.35:
            continue
        col = _blob_color(crop, (x, y, bw, bh))
        if col is None:
            continue
        cells.append((x, y, bw, bh, col))
    if target is None or len(cells) < 4:
        if verbose:
            print("[BOT] anty-macro: wariant z liczbami albo nieczytelny - "
                  "czekam (trzeba rozwiazac recznie)")
        return False
    th, ts = target[4]
    scored = []
    for c in cells:
        dh = abs(c[4][0] - th)
        dh = min(dh, 180 - dh)
        ds = abs(c[4][1] - ts)
        scored.append((dh + ds * 0.25, c))
    scored.sort(key=lambda t: t[0])
    if not scored:
        return False
    bestd, best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 999.0
    # klikamy tylko jak dopasowanie jest jednoznaczne
    if bestd > 24 or second < bestd * 1.6:
        if verbose:
            print(f"[BOT] anty-macro: dopasowanie niejednoznaczne "
                  f"({bestd:.0f} vs {second:.0f}) - czekam")
        return False
    x, y, bw, bh, _ = best
    tx, ty = px + x + bw // 2, py + y + bh // 2
    io.tap(tx, ty)
    if verbose:
        print(f"[BOT] anty-macro: klikam beczke ({tx}, {ty}) "
              f"barwa {best[4][0]:.0f}/{best[4][1]:.0f} vs {th:.0f}/{ts:.0f}")
    time.sleep(0.4)
    # nagroda: niebieski przycisk na dole panelu
    after = io.grab()
    panel2 = _event_panel(after)
    if panel2:
        btn = find_blue_button(after, panel2)
        if btn:
            io.tap(*btn)
            if verbose:
                print(f"[BOT] anty-macro: odbieram nagrode {btn}")
            time.sleep(0.5)
    return True


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
