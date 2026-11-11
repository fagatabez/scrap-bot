"""Rozpoznawanie ekranow Scrap Clicker 2 i wspolrzedne elementow UI.

Wszystko liczone jest wzgledem "viewportu" gry, czyli pionowego pasa 9:16
w oknie BlueStacks. Dzieki temu dziala przy dowolnym rozmiarze okna i przy
panelu reklamowym z boku.
"""
import cv2
import numpy as np


def _runs(mask_1d, min_len=1):
    """Zamienia maske 1D na liste (start, end) ciaglych True."""
    runs = []
    start = None
    n = len(mask_1d)
    for i, v in enumerate(mask_1d):
        if v and start is None:
            start = i
        if (not v or i == n - 1) and start is not None:
            end = i if not v else i + 1
            if end - start >= min_len:
                runs.append((start, end))
            start = None
    return runs


def game_x_range(img):
    """Skrajne kolumny zielonego paska gry -> (x0, x1).

    Pasek jest widoczny takze pod przyciemnionym tlem (menu ulepszen,
    ekran restartu), wiec po nim poznajemy polozenie calego viewportu.
    Bierzemy skrajne kolumny, a nie jeden ciagly odcinek, bo ikony na pasku
    dziela go na kilka kawalkow.
    """
    h, w = img.shape[:2]
    band = img[int(h * 0.86):h]
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([35, 60, 25]), np.array([95, 255, 255]))
    colfrac = mask.mean(axis=0) / 255.0
    cols = (colfrac > 0.20).astype(np.int32)
    if cols.sum() < max(10, int(w * 0.10)):
        return None
    # wygladz: pojedyncze piksele nie licza sie, ale dziury po ikonach tak
    smooth = np.convolve(cols, np.ones(9, np.int32), mode="same") >= 3
    idx = np.where(smooth)[0]
    if len(idx) == 0:
        return None
    x0, x1 = int(idx.min()), int(idx.max()) + 1
    if x1 - x0 < w * 0.30:
        return None
    return x0, x1


def find_viewport(img):
    """Prostokat gry (x, y, w, h) wyliczony z dolnego paska. None gdy brak."""
    nav = game_x_range(img)
    if not nav:
        return None
    x0, x1 = nav
    vw = x1 - x0
    vh = int(round(vw * 16 / 9))
    if vh > img.shape[0]:
        vh = img.shape[0]
    y = img.shape[0] - vh
    return int(x0), int(y), int(vw), int(vh)


def pt(viewport, fx, fy):
    """Punkt w ulamkach viewportu -> piksele okna."""
    x, y, w, h = viewport
    return int(x + fx * w), int(y + fy * h)


def upgrade_band(img, viewport):
    """Ciagly zielony slup przyciskow po prawej -> (y0, y1) albo None.

    Przyciski sa stykaja sie ze soba, wiec nie da sie ich rozdzielic po
    kolorze. Ten pas sluzy tylko do rozpoznania ekranu; konkretny rzad
    wyznacza OCR (nazwa ulepszenia).
    """
    x, y, w, h = viewport
    roi = img[y:y + h, x:x + w]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([50, 140, 80]), np.array([90, 255, 255]))
    x0, x1 = int(w * 0.68), int(w * 0.97)
    frac = mask[:, x0:x1].mean(axis=1) / 255.0
    rows = frac > 0.45
    runs = _runs(rows, min_len=max(20, int(h * 0.12)))
    if not runs:
        return None
    a, b = max(runs, key=lambda r: r[1] - r[0])
    return a + y, b + y


# przyblizone srodki rzedow (ulamki viewportu) - awaryjnie, gdy OCR zawiedzie
UPGRADE_ROW_FRACTIONS = (0.278, 0.348, 0.420, 0.490, 0.561, 0.632, 0.703)


def is_upgrade_screen(img, viewport):
    return upgrade_band(img, viewport) is not None and red_x(img, viewport) is not None


def upgrade_click_x(viewport):
    return int(viewport[0] + viewport[2] * 0.825)


def red_x(img, viewport):
    """Czerwony przycisk X zamykajacy menu -> (x, y) albo None."""
    x, y, w, h = viewport
    roi = img[y:y + h, x:x + w]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    m1 = cv2.inRange(hsv, np.array([0, 150, 120]), np.array([10, 255, 255]))
    m2 = cv2.inRange(hsv, np.array([170, 150, 120]), np.array([180, 255, 255]))
    m = m1 | m2
    n, _, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    best = None
    for i in range(1, n):
        bx, by, bw, bh, area = stats[i]
        if not (0.035 * w < bw < 0.13 * w):
            continue
        if not (0.015 * h < bh < 0.09 * h):
            continue
        if not (0.6 < bw / max(bh, 1) < 1.7):
            continue
        if area < 0.35 * bw * bh:
            continue
        cx, cy = bx + bw // 2, by + bh // 2
        if cx < 0.6 * w or cy > 0.45 * h:
            continue
        if best is None or area > best[2]:
            best = (cx, cy, area)
    if not best:
        return None
    return x + best[0], y + best[1]


def blue_button(img, viewport):
    """Szeroki niebieski przycisk (Restart Gry) -> (x, y, w, h) albo None."""
    x, y, w, h = viewport
    roi = img[y:y + h, x:x + w]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([95, 150, 110]), np.array([115, 255, 255]))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    best = None
    for i in range(1, n):
        bx, by, bw, bh, area = stats[i]
        if not (0.35 * w < bw < 0.92 * w):
            continue
        if not (0.025 * h < bh < 0.11 * h):
            continue
        if area < 0.45 * bw * bh:
            continue
        if by + bh // 2 < 0.45 * h:
            continue
        if best is None or bw * bh > best[2]:
            best = (bx + bw // 2, by + bh // 2, bw * bh)
    if not best:
        return None
    return x + best[0], y + best[1], 0, 0


def line_center(line):
    return int(line["x"] + line["w"] / 2), int(line["y"] + line["h"] / 2)
