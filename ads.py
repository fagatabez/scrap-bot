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


def hud_visible(img, min_mean=78.0):
    """Czy widac pasek HUD gry (liczniki, magnes, pasek poziomu)?

    Reklama tez potrafi wygladac jak plansza (duzy jednolity obszar), wiec
    dodatkowo sprawdzamy, czy gora ekranu jest jasna - w grze jest tam pasek
    z liczbami na jasnym tle, w reklamie ciemna plansza.
    """
    h, w = img.shape[:2]
    y0, y1 = int(h * 0.05), int(h * 0.14)
    if y1 <= y0:
        return True
    g = cv2.cvtColor(img[y0:y1], cv2.COLOR_BGR2GRAY)
    return float(g.mean()) > min_mean


def has_crown(img, min_score=0.18):
    """Czy w kadrze jest zlota korona (szablon z okna oferty).

    Porownujemy maske zoltego koloru z szablonem (roznica pikseli), a nie
    korelacje - inaczej wielki zluty obszar w innej grze tez "pasowal".
    """
    tmpl = cv2.imread(CROWN, cv2.IMREAD_GRAYSCALE)
    if tmpl is None:
        return False
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(hsv, np.array([18, 90, 120]), np.array([38, 255, 255]))
    yellow = cv2.morphologyEx(yellow, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    h, w = yellow.shape[:2]
    best = 1.0
    for s in (0.3, 0.4, 0.55, 0.7, 0.9, 1.0, 1.1, 1.4, 1.8):
        t = cv2.resize(tmpl, (max(4, int(tmpl.shape[1] * s)),
                              max(4, int(tmpl.shape[0] * s))),
                       interpolation=cv2.INTER_NEAREST)
        if t.shape[0] >= h or t.shape[1] >= w:
            continue
        res = cv2.matchTemplate(yellow, t, cv2.TM_SQDIFF_NORMED)
        best = min(best, float(res.min()))
    return best < min_score


def scan_state(img):
    """Jednorazowa analiza klatki: (okno?, pasek gry?, to nasza gra?).

    Wszystkie sprawdzenia korzystaja z jednej konwersji do HSV - wczesniej
    kazda z osobna kosztowala ~4 ms, a skaner wychodzil ~85 ms na klatke
    (11 FPS), przez co robotnik czekal na nowy plan.
    """
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hh, ss, vv = cv2.split(hsv)

    # jasnoszare okno gry (reklama/popup)
    gray = ((np.abs(hh - ss) < 12) & (np.abs(ss - vv) < 12) &
            (vv > 185) & (vv < 235))
    popup = float(gray.mean()) > 0.05

    # nasycona zielen - pasek gry na dole (w kazdej orientacji)
    green = (hh >= 30) & (hh <= 90) & (ss > 120)
    edges = (
        float(green[int(h * 0.90):].mean()),
        float(green[:int(h * 0.10)].mean()),
        float(green[:, :int(w * 0.10)].mean()),
        float(green[:, int(w * 0.90):].mean()),
    )
    in_game = max(edges) > 0.05

    # jasnozielone tlo planszy = nasza gra
    board = ((hh >= 40) & (hh <= 80) & (ss >= 20) & (ss <= 90) & (vv >= 165))
    is_scrap = float(board.mean()) > 0.06 or has_crown(img)
    return popup, in_game, is_scrap


def is_scrap_game(img, min_frac=0.06):
    """Czy to na pewno Scrap Clicker 2 (plansza albo okno gry)?

    Plansza ma jasnozielone tlo, a okna oferty zlota korone. Inne gry
    w emulatorze tego nie maja - bot wtedy nic nie robi, zamiast machac
    myszka w obcej aplikacji.
    """
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = ((hsv[:, :, 0] >= 40) & (hsv[:, :, 0] <= 80) &
         (hsv[:, :, 1] >= 20) & (hsv[:, :, 1] <= 90) &
         (hsv[:, :, 2] >= 165))
    if float(m.mean()) > min_frac:
        return True
    return has_crown(img)


def game_bar(img, min_frac=0.05):
    """Czy widac zielony pasek gry (dolny pasek z beczkami i strzalka).

    Reklama go nie ma - to najprostszy rozroznik reklamy od gry. W sztormie
    pasek jest przyciemniony, ale nadal zielony, wiec dziala tam too.
    Sprawdzamy wszystkie krawedzie, bo ekran moze byc obrocony.
    """
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = (hsv[:, :, 0] >= 30) & (hsv[:, :, 0] <= 90) & (hsv[:, :, 1] > 120)
    edges = {
        "bottom": float(m[int(h * 0.90):].mean()),
        "top": float(m[:int(h * 0.10)].mean()),
        "left": float(m[:, :int(w * 0.10)].mean()),
        "right": float(m[:, int(w * 0.90):].mean()),
    }
    return max(edges.values()) > min_frac


def game_visible(img):
    """Czy naprawde widac gre (a nie reklame)."""
    return looks_like_game(img) and hud_visible(img)


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
    return sim >= 0.95          # 'Szybsze Beczki' ~0.99, 'Auto Laczenie' ~0.90


def find_boost_button(img):
    """Przycisk "Tak!" w popupie "Szybsze Beczki" albo None.

    Ekran moze byc obrocony (telefon/emulator w poziomie) - wtedy szukamy
    w orientacji gry i mapujemy wspolrzedne z powrotem na oryginalny obraz.
    """
    import pairs
    angle = pairs.rotation(img)
    if angle:
        H, W = img.shape[:2]
        pos = _boost_button_in_game(pairs.rotate_to_portrait(img, angle))
        if pos is None:
            return None
        return pairs.map_point_back(pos[0], pos[1], angle, H, W)
    return _boost_button_in_game(img)


def _boost_button_in_game(img):
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
    """Czerwony przycisk "Nie" w popupie (obok zielonego "Tak!").

    Ekran moze byc obrocony - wtedy szukamy w orientacji gry i mapujemy
    wspolrzedne z powrotem.
    """
    import pairs
    angle = pairs.rotation(img)
    if angle:
        H, W = img.shape[:2]
        pos = _red_button_in_game(pairs.rotate_to_portrait(img, angle))
        if pos is None:
            return None
        return pairs.map_point_back(pos[0], pos[1], angle, H, W)
    return _red_button_in_game(img)


def _red_button_in_game(img):
    """Czerwony przycisk "Nie" - szukamy go samodzielnie (nie przez zielony
    przycisk), bo w chwili po kliknieciu koronki "Tak!" moze byc jeszcze
    niewidoczny (animacja okna), a czerwony "Nie" juz widac.
    """
    h, w = img.shape[:2]
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
        crop = hsv[y:y + bh, x:x + bw]
        if crop.size == 0:
            continue
        white = cv2.inRange(crop, np.array([0, 0, 190]), np.array([180, 70, 255]))
        if int((white > 0).sum()) < 0.008 * bw * bh:
            continue                        # brak napisu - to nie przycisk
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
    # Sprawdzamy tylko prawy gorny wycinek (nad plansza) - kosztuje ok. 0,3 ms,
    # wiec mozemy sprawdzac co 0,3 s bez wplywu na tempo mergowania.
    x0 = int(w * 0.55)
    y1 = int(h * 0.30)
    if board is not None:
        bx, by, bw2, bh2 = board
        x0 = max(0, int(bx + bw2 * 0.55))
        y1 = max(30, int(by))
    roi = img[0:y1, x0:w]
    if roi.size == 0:
        return None
    rh, rw = roi.shape[:2]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(hsv, np.array([18, 120, 140]), np.array([38, 255, 255]))
    yellow = cv2.morphologyEx(yellow, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    best = None
    has_board = board is not None
    for x, y, bw, bh, area in _components(yellow, 60):
        if not (0.02 * w <= bw <= 0.16 * w):
            continue
        if not (0.012 * h <= bh <= 0.10 * h):
            continue
        if not (1.12 < bw / max(bh, 1) < 1.9):
            continue
        cx = x + bw // 2 + x0
        cy = y + bh // 2
        if has_board:
            bx, by, bw2, bh2 = board
            if cy > by:                   # musi byc NAD plansza
                continue
            if not (bx - 0.12 * bw2 <= cx <= bx + 1.08 * bw2):
                continue
        if best is None or area > best[0]:
            best = (area, cx, cy)
    if best is None:
        return None
    return (best[1], best[2])


UPGRADE_MAX = os.path.join(HERE, "assets", "upgrade_max.png")
_MAX_TMPL = None


def _upgrade_max_tmpl():
    """Szablon napisu 'MAX' (wczytany raz, nie przy kazdym kliknieciu)."""
    global _MAX_TMPL
    if _MAX_TMPL is None:
        _MAX_TMPL = cv2.imread(UPGRADE_MAX, cv2.IMREAD_GRAYSCALE)
    return _MAX_TMPL


def find_upgrade_arrow(img):
    """Pomarańczowa strzalka na dole gry - otwiera menu 'Ulepszenia'."""
    h, w = img.shape[:2]
    y0 = int(h * 0.82)
    roi = img[y0:h]
    if roi.size == 0:
        return None
    rh, rw = roi.shape[:2]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    orange = cv2.inRange(hsv, np.array([8, 100, 90]), np.array([23, 255, 255]))
    orange = cv2.morphologyEx(orange, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    best = None
    for x, y, bw, bh, area in _components(orange, 80):
        if not (0.02 * w <= bw <= 0.12 * w):
            continue
        if not (0.02 * h <= bh <= 0.09 * h):
            continue
        if not (0.45 < bw / max(bh, 1) < 1.4):
            continue
        cx = x + bw // 2
        if not (0.30 * rw <= cx <= 0.70 * rw):     # srodek dolnego paska
            continue
        if best is None or area > best[0]:
            best = (area, cx, y + bh // 2 + y0)
    return (best[1], best[2]) if best else None


def _text_rows(mask, min_h=5):
    """Wiersze tekstu w obrazie binarnym (kolumna przyciskow)."""
    rows = mask.sum(axis=1)
    runs, cur = [], None
    for i, v in enumerate(rows):
        if v > 2:
            cur = [i, i] if cur is None else [cur[0], i]
        elif cur is not None:
            runs.append(tuple(cur))
            cur = None
    if cur:
        runs.append(tuple(cur))
    return [r for r in runs if r[1] - r[0] >= min_h]


def _green_column(hsv, w):
    """Kolumna zielonych przyciskow (x, szerokosc, od dołu). Szare przyciski
    (nie do kupienia) dziela kolumne na kawalki - laczymy je."""
    green = cv2.inRange(hsv, np.array([45, 130, 90]), np.array([90, 255, 255]))
    green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(green, 8)
    blocks = []
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        if area < 400 or bw > 0.40 * w or bh < 8:
            continue
        blocks.append((x, y, bw, bh, area))
    if not blocks:
        return None
    # najszerszy blok wyznacza kolumne, reszte laczymy po nim
    x0, bw = max(((b[0], b[2]) for b in blocks), key=lambda t: t[1])
    same = [b for b in blocks if abs(b[0] - x0) < 0.02 * w]
    top = min(b[1] for b in same)
    bottom = max(b[1] + b[3] for b in same)
    return x0, bw, top, bottom


def _max_template(col_w):
    """Szablon 'MAX' przeskalowany do szerokosci kolumny przyciskow.

    Kolumna bywa o piksel szerza/nuzsza niz oryginalny szablon, wiec skalujemy
    zawsze - inaczej porownanie jest pomijane albo wyrzuca wszystkie wiersze.
    """
    tmpl = _upgrade_max_tmpl()
    if tmpl is None:
        return None
    scale = col_w / float(tmpl.shape[1])
    if abs(scale - 1.0) < 0.005:
        return tmpl
    return cv2.resize(tmpl, (max(4, int(round(tmpl.shape[1] * scale))),
                           max(4, int(round(tmpl.shape[0] * scale)))),
                      interpolation=cv2.INTER_AREA)


def button_state(img, col_x, col_w, x, y):
    """Stan przycisku pod (x, y): 'green' (kupowalny), 'max', 'grey'.

    Szybkie: patrzy tylko na male wycinki (kolor tla + wzorzec 'MAX'),
    wiec mozna to sprawdzac po kazdej rundzie klikania.
    """
    h, w = img.shape[:2]
    x0 = max(0, col_x + 2)
    x1 = min(w, col_x + max(4, col_w // 4))
    y0 = max(0, y - 9)
    y1 = min(h, y + 10)
    if x1 <= x0 or y1 <= y0:
        return "grey"
    hsv = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    mh = float(np.median(hsv[:, :, 0]))
    ms = float(np.median(hsv[:, :, 1]))
    if not (35 <= mh <= 95 and ms > 90):
        return "grey"                    # szary - nie stac nas
    t = _max_template(col_w)
    if t is not None:
        reg = img[max(0, y - t.shape[0] // 2):y - t.shape[0] // 2 + t.shape[0],
                  col_x:col_x + col_w]
        if reg.size and reg.shape[0] >= t.shape[0] and reg.shape[1] >= t.shape[1]:
            g1 = cv2.cvtColor(reg, cv2.COLOR_BGR2GRAY)
            res = cv2.matchTemplate(g1, t, cv2.TM_CCOEFF_NORMED)
            if float(res.max()) > 0.70:
                return "max"
    return "green"


def find_upgrade_buttons(img):
    """Przyciski w menu 'Ulepszenia', ktore da sie kliknac.

    Pomijamy: napis "MAX" (już wykupione) i przyciski SZARE (nie stac nas -
    cena na czerwono). Zwraca liste (x, y).
    """
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    col = _green_column(hsv, w)
    if col is None:
        return []
    x, bw, top, bottom = col
    white = cv2.inRange(hsv[top:bottom, x:x + bw],
                        np.array([0, 0, 190]), np.array([180, 60, 255]))
    runs = _text_rows(white)
    if not runs:
        return []
    out = []
    for r in runs:
        yy0, yy1 = top + r[0], top + r[1]
        # kolor tla przycisku: zielony = da sie kupic, szary = nie
        patch = hsv[yy0:yy1 + 1, x + 2:x + 12].reshape(-1, 3)
        if patch.size:
            mh = float(np.median(patch[:, 0]))
            ms = float(np.median(patch[:, 1]))
            if not (35 <= mh <= 95 and ms > 90):
                continue                    # szary przycisk - pomijamy
        t = _max_template(bw)
        if t is not None:
            cy = (yy0 + yy1) // 2
            reg = img[max(0, cy - t.shape[0] // 2):cy - t.shape[0] // 2 + t.shape[0],
                      x:x + bw]
            if reg.size == 0:
                continue
            g1 = cv2.cvtColor(reg, cv2.COLOR_BGR2GRAY)
            if g1.shape[0] < t.shape[0] or g1.shape[1] < t.shape[1]:
                continue
            res = cv2.matchTemplate(g1, t, cv2.TM_CCOEFF_NORMED)
            if float(res.max()) > 0.70:
                continue                    # napis MAX - pomijamy
        out.append((x + bw // 2, (yy0 + yy1) // 2))
    return out


def upgrade_menu_open(img):
    """Czy otwarte menu 'Ulepszenia' (zielona kolumna przyciskow po prawej)."""
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, np.array([45, 130, 90]), np.array([90, 255, 255]))
    green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(green, 8)
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        if area > 0.03 * h * w and bw < 0.40 * w and bh > 0.25 * h:
            return True
    return False


def watch_offer(io, verbose=True, pos=None):
    """Kliknie koronke eventow i obsluzy oferte.

    Zwraca: 'tak' (obejrzano reklame = boost), 'nie' (odrzucono oferte),
    None (nie bylo oferty). `pos` to juz znaleziona pozycja koronki.
    """
    if pos is None:
        frame = io.grab()
        board = board_rect(frame)
        pos = find_boost_icon(frame, board)
    if not pos:
        return None
    if verbose:
        print(f"[BOT] koronka eventow na {pos} - klikam")
    io.tap(*pos)
    # okno moze sie otworzyc z opoznieniem (animacja) - sprawdzamy kilka razy
    for wait in (0.5, 0.8, 1.2, 1.8, 2.5):
        time.sleep(wait)
        frame = io.grab()
        tak = find_boost_button(frame)      # "Szybsze Beczki" - chcemy to
        if tak:
            io.tap(*tak)
            time.sleep(1.6)
            close_after_ad(io)
            return "tak"
        nie = find_red_button(frame)        # inne okno (np. "Wiecej Zlomu")
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
    import pairs
    frame = frame if frame is not None else io.grab()
    H, W = frame.shape[:2]
    angle = pairs.rotation(frame)
    if angle:
        frame = pairs.rotate_to_portrait(frame, angle)
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
    if angle:
        tx, ty = pairs.map_point_back(tx, ty, angle, H, W)
    if not (0 <= tx < W and 0 <= ty < H):
        if verbose:
            print("[BOT] anty-macro: klik poza ekranem - czekam")
        return False
    io.tap(tx, ty)
    if verbose:
        print(f"[BOT] anty-macro: klikam beczke ({tx}, {ty}) "
              f"barwa {best[4][0]:.0f}/{best[4][1]:.0f} vs {th:.0f}/{ts:.0f}")
    time.sleep(0.4)
    # nagroda: niebieski przycisk na dole panelu
    after = io.grab()
    angle2 = pairs.rotation(after)
    if angle2:
        after = pairs.rotate_to_portrait(after, angle2)
    panel2 = _event_panel(after)
    if panel2:
        btn = find_blue_button(after, panel2)
        if btn:
            if angle2:
                btn = pairs.map_point_back(btn[0], btn[1], angle2, H, W)
            if 0 <= btn[0] < W and 0 <= btn[1] < H:
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
    """Reklama wlasnie leci: czekamy az sie skonczy i wracamy do gry.

    Najpierw 'wstecz' (przycisk BlueStacks / klawisz BACK) - dziala jak X,
    a X w reklamie bywa niewidoczny. Dopiero potem szukamy X-a na ekranie.
    """
    for i in range(tries):
        frame = io.grab()
        if game_visible(frame):
            return True
        try:
            if io.back():
                time.sleep(1.0)
                continue
        except Exception:
            pass
        pos = find_close_button(frame)
        if pos:
            io.tap(*pos)
            time.sleep(0.9)
            continue
        time.sleep(1.0)
    return False


def close_screen(io, tries_corners=True, try_boost=True):
    """Proboje zamknac to, co zaslania gre. True = chyba sie udalo."""
    frame = io.grab()
    if game_visible(frame):
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
        if game_visible(io.grab()):
            return True

    io.key(4)                                  # WSTECZ zamyka wiekszosc reklam
    time.sleep(0.9)
    if game_visible(io.grab()):
        return True

    if tries_corners:
        h, w = frame.shape[:2]
        for fx, fy in ((0.94, 0.05), (0.06, 0.05), (0.94, 0.95), (0.5, 0.95)):
            io.tap(int(w * fx), int(h * fy))
            time.sleep(0.6)
            if game_visible(io.grab()):
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
            if game_visible(frame):
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
