"""Wykrywanie i parowanie identycznych beczek w Scrap Clicker 2 - BEZ szablonow.

Idea: nie porownujemy beczek z biblioteka 1000 skinow, tylko kazda beczka
z kazda na tym samym zrzucie. Opis beczki to histogram barwy (H) + nasycenia (S)
+ odrobina struktury (krawedzie), wiec jest odporny na cien, perspektywe
i rozdzielczosc. Ten sam skin => dystans ~0.05, inny skin => ~0.8.

Uzycie:
    python pairs.py [zrzut.png] [wyjscie.png]
Bez argumentow bierze swiezy zrzut z ADB.
"""
import itertools
import subprocess
import sys

import cv2
import numpy as np

import os
import tempfile

ADB = os.environ.get("ADB_PATH", r"C:\ADB\adb.exe")
DEVICE = os.environ.get("ADB_DEVICE", "127.0.0.1:5555")
# root na telefonie: zrzut i tapy idą przez su, bez ADB
USE_ROOT = os.environ.get("SCRAP_USE_ROOT", "") not in ("", "0", "false", "False")

# prog decyzji "ta sama beczka" (0 = identyczne, 1 = zupelnie inne)
SAME_THRESHOLD = 0.32

# puste (nierespione) pole: szary walec, bardzo niskie nasycenie
EMPTY_MAX_SAT = 32
EMPTY_MAX_VAL = 150

# ile piksel musi roznic sie od tla planszy, zeby byc czescia beczki.
# Musi byc nisko: jasny, szary korpus beczki rozni sie od zielonego tla tylko
# o ~35-40, a przy 45 rozpadal sie na dwa kawalki i szare beczki znikaly.
BG_DIFF = 32

# sztorm: plansza jest przyciemniona (normalnie tlo ma jasnosc ~208, w sztormie ~56)
STORM_MAX_V = 130


def dominant_bgr(band: np.ndarray):
    """Najczestszy kolor (kwantyzacja //8) bez sortowania pikseli.
    Histogram 32x32x32 ma dokladnie te same progi co (v // 8 * 8)."""
    hist = cv2.calcHist([band], [0, 1, 2], None, [32, 32, 32],
                        [0, 256, 0, 256, 0, 256])
    i = np.unravel_index(int(np.argmax(hist)), hist.shape)
    bgr = np.array([i[0] * 8, i[1] * 8, i[2] * 8], np.uint8)
    frac = float(hist[i]) / (band.shape[0] * band.shape[1])
    return bgr, frac


def background(img: np.ndarray):
    """Najczestszy kolor pasa gry -> (BGR, HSV, udzial)."""
    h, _ = img.shape[:2]
    band = img[int(h * 0.12):int(h * 0.89)]
    bgr, frac = dominant_bgr(band)
    hsv = cv2.cvtColor(bgr.reshape(1, 1, 3), cv2.COLOR_BGR2HSV)[0, 0]
    return bgr, hsv, frac


def is_storm(img: np.ndarray) -> bool:
    """Sztorm = przyciemnione tlo planszy. W sztormie gra nie pozwala laczyc
    (dopoki nie kupi sie laczenia za gwiazdy), wiec bot ma wtedy zbierac."""
    _, hsv, frac = background(img)
    return hsv[2] < STORM_MAX_V and frac > 0.15


# siatka gry: 4 kolumny x 5 rzedow, ulamki wzgledem pola gry
GRID_COLS, GRID_ROWS = 4, 5
COL0, COL_STEP = 0.164, 0.2258
ROW0, ROW_STEP = 0.0995, 0.2089


def playfield_rect(img: np.ndarray):
    """Prostokat pola gry (najwiekszy obszar w kolorze tla). None gdy brak."""
    bgr, _, _ = background(img)
    dist = np.linalg.norm(img.astype(np.int16) - bgr.astype(np.int16), axis=2)
    m = (dist < 14).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    if n < 2:
        return None
    i = 1 + int(np.argmax(stats[1:, 4]))
    x, y, w, h, _ = stats[i]
    if w < img.shape[1] * 0.30 or h < img.shape[0] * 0.40:
        return None
    # pole gry ma staly proporcje ~0.71 (900x1268); inny ksztalt = cos zaslania
    if not (0.62 < w / h < 0.82):
        return None
    return int(x), int(y), int(w), int(h)


def grid_centers(rect):
    """20 srodkow pol (4x5) wyliczonych z prostokata pola gry - dziala tez
    w sztormie, gdy kolorow beczek nie da sie odroznic od tla."""
    x, y, w, h = rect
    return [(int(x + (COL0 + c * COL_STEP) * w),
             int(y + (ROW0 + r * ROW_STEP) * h))
            for r in range(GRID_ROWS) for c in range(GRID_COLS)]




# ---------------------------------------------------------------- zrzut
def connect():
    """Podlacza sie do urzadzenia po ADB.

    Dwa warianty:
      * bot na telefonie, gra na telefonie - telefon laczy sie z samym soba
        przez debugowanie bezprzewodowe (localhost:PORT),
      * bot na telefonie, gra w emulatorze na PC - laczy sie z IP komputera.
    """
    if ":" not in DEVICE:
        return
    subprocess.run([ADB, "connect", DEVICE],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   check=False)


def adb_shell(*args, timeout=20):
    """Polecenie w powloce urzadzenia (uzywane do tapow i swipe'ow)."""
    connect()
    return subprocess.run([ADB, "-s", DEVICE, "shell", *args],
                          capture_output=True, text=True, timeout=timeout,
                          check=False)


def screencap(path: str) -> np.ndarray:
    if USE_ROOT:
        # root: zrzut przez su, bez ADB - telefon gra sam w sobie
        with open(path, "wb") as f:
            proc = subprocess.run(["su", "-c", f"screencap -p > {path}"],
                                  capture_output=True, timeout=20, check=False)
        img = cv2.imread(path)
        if img is None:
            raise RuntimeError(f"screencap (root) nieudany: {proc.stderr[:200]}")
        return img
    connect()
    with open(path, "wb") as f:
        subprocess.run([ADB, "-s", DEVICE, "exec-out", "screencap", "-p"],
                       stdout=f, check=True)
    return cv2.imread(path)


def shell(*args, timeout=20):
    """Polecenie powloki systemowej: przez ADB albo (z rootem) przez su."""
    if USE_ROOT:
        cmd = " ".join(args)
        return subprocess.run(["su", "-c", cmd], capture_output=True, text=True,
                              timeout=timeout, check=False)
    return adb_shell(*args, timeout=timeout)


# ---------------------------------------------------------------- detekcja
def find_barrels(img: np.ndarray):
    """Zwraca liste (x, y, w, h) beczek. Tlo wykrywane z obrazu, wiec dziala
    przy dowolnej rozdzielczosci i motywie graficznym."""
    h, w = img.shape[:2]
    y0, y1 = int(h * 0.12), int(h * 0.89)          # pomijamy HUD i dolny pasek
    band = img[y0:y1]

    # najczestszy kolor w pasie gry = tlo planszy
    bg, _ = dominant_bgr(band)
    bg = bg.astype(np.int16)

    dist = np.linalg.norm(band.astype(np.int16) - bg, axis=2)
    mask = (dist > BG_DIFF).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))

    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    boxes = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if bw < 0.075 * w or bw > 0.22 * w:
            continue
        if bh < 0.07 * h or bh > 0.25 * h:
            continue
        if area < 0.5 * bw * bh:                    # za malo wypelnione
            continue
        if x <= 1 or x + bw >= w - 1:               # ucieta przy krawedzi
            continue
        boxes.append((int(x), int(y + y0), int(bw), int(bh)))

    if not boxes:
        return []

    # odsiew ucietych od dolu (dolny pasek zaslania czesc ostatniego rzedu)
    med = float(np.median([b[3] for b in boxes]))
    boxes = [b for b in boxes if b[3] > 0.88 * med]

    # odsiew pustych (nierespionych) pol - szary walec bez koloru
    boxes = [b for b in boxes if not is_empty_slot(img, b)]

    boxes.sort(key=lambda b: (round(b[1] / (0.3 * h)), b[0]))
    return boxes


def is_empty_slot(img: np.ndarray, box, max_sat: int = EMPTY_MAX_SAT,
                  max_val: int = EMPTY_MAX_VAL) -> bool:
    """Puste pole = szary walec bez czarnej czapy.

    Uwaga: najnizsza polka beczek tez jest szara - odroznia ja czarny wierzch
    (otwor). Dlatego najpierw sprawdzamy ciemne piksele: jesli sa, to beczka,
    nawet gdy caly korpus jest szary i malo nasycony.
    """
    x, y, w, h = box
    crop = barrel_crop(img, box)
    if crop.size == 0:
        return True
    s = cv2.resize(crop, (40, 40), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(s, cv2.COLOR_BGR2HSV)
    h_, s_, v_ = cv2.split(hsv)
    dark = float(np.count_nonzero(v_ < 60)) / v_.size
    if dark > 0.04:                     # czarny otwor = prawdziwa beczka
        return False
    return float(s_.mean()) <= max_sat and float(v_.mean()) <= max_val


# ---------------------------------------------------------------- opis
def barrel_crop(img, box):
    """Wycina gorna czesc beczki (czapa + poczatek korpusu) w stalym kadrze,
    dzieki czemu rozmiar na ekranie nie ma znaczenia."""
    x, y, bw, bh = box
    cx = x + bw / 2
    hh = int(bw * 0.95)
    return img[y:y + hh, int(cx - 0.46 * bw):int(cx + 0.46 * bw)]


def describe(img, box):
    return describe_crop(barrel_crop(img, box))


def describe_crop(crop):
    s = cv2.resize(crop, (40, 40), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(s, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [18, 8], [0, 180, 0, 256])
    hist = cv2.normalize(hist, hist).flatten().astype(np.float32)

    gray = cv2.cvtColor(s, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    edges = cv2.resize(np.sqrt(gx * gx + gy * gy), (10, 10),
                       interpolation=cv2.INTER_AREA).flatten()
    edges = edges / (edges.mean() + 1e-6)
    return hist, edges


def distance(f1, f2):
    h1, e1 = f1
    h2, e2 = f2
    dh = float(cv2.compareHist(h1.reshape(-1, 1), h2.reshape(-1, 1),
                               cv2.HISTCMP_BHATTACHARYYA))
    de = float(np.abs(e1 - e2).mean())
    return 0.85 * dh + 0.15 * de


# ---------------------------------------------------------------- parowanie
def find_pairs(img: np.ndarray, threshold: float = None):
    """Zwraca (boxes, feats, pary). Pary sa rozlaczne - kazda beczka raz."""
    if threshold is None:
        threshold = SAME_THRESHOLD          # czytane co wywolanie, nie przy imporcie
    boxes = find_barrels(img)
    if len(boxes) < 2:
        return boxes, [], []
    feats = [describe(img, b) for b in boxes]

    cand = []
    for i, j in itertools.combinations(range(len(boxes)), 2):
        d = distance(feats[i], feats[j])
        if d < threshold:
            cand.append((d, i, j))
    cand.sort()

    used, pairs = set(), []
    for d, i, j in cand:
        if i in used or j in used:
            continue
        used.update((i, j))
        pairs.append((i, j, d))
    return boxes, feats, pairs


# ---------------------------------------------------------------- podglad
def annotate(img, boxes, pairs, out_path):
    vis = img.copy()
    for i, j, d in pairs:
        bi, bj = boxes[i], boxes[j]
        ci = (int(bi[0] + bi[2] / 2), int(bi[1] + bi[3] * 0.4))
        cj = (int(bj[0] + bj[2] / 2), int(bj[1] + bj[3] * 0.4))
        cv2.rectangle(vis, bi[:2], (bi[0] + bi[2], bi[1] + bi[3]), (0, 0, 255), 3)
        cv2.rectangle(vis, bj[:2], (bj[0] + bj[2], bj[1] + bj[3]), (0, 0, 255), 3)
        cv2.line(vis, ci, cj, (255, 0, 255), 4)
        cv2.putText(vis, f"{d:.2f}", ((ci[0] + cj[0]) // 2, (ci[1] + cj[1]) // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)
    cv2.putText(vis, f"beczek: {len(boxes)}  par: {len(pairs)}", (10, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
    cv2.imwrite(out_path, vis)
    return vis


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else None
    out = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\wikto\AppData\Local\Temp\opencode\scrap\pairs.png"
    img = cv2.imread(src) if src else screencap(
        r"C:\Users\wikto\AppData\Local\Temp\opencode\scrap\live3.png")
    boxes, feats, pairs = find_pairs(img)
    print(f"beczek={len(boxes)} par={len(pairs)}")
    for i, j, d in pairs:
        ci = (boxes[i][0] + boxes[i][2] // 2, boxes[i][1] + boxes[i][3] // 2)
        cj = (boxes[j][0] + boxes[j][2] // 2, boxes[j][1] + boxes[j][3] // 2)
        print(f"  {ci} <-> {cj}  dystans={d:.3f}")
    annotate(img, boxes, pairs, out)
    print("podglad:", out)
