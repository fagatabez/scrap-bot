"""Wykrywa beczki na ekranie Scrap Clicker 2 i rysuje podglad."""
import sys

import cv2
import numpy as np

IMG = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\wikto\AppData\Local\Temp\opencode\scrap\game1.png"
OUT = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\wikto\AppData\Local\Temp\opencode\scrap\grid.png"


def find_barrels(img):
    h, w = img.shape[:2]
    # tlo gry: mediana z pasow po bokach (bez UI)
    border = np.concatenate([img[120:800, 0:20].reshape(-1, 3), img[120:800, w - 20:w].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    diff = np.linalg.norm(img.astype(np.int16) - bg.astype(np.int16), axis=2)
    mask = (diff > 40).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))

    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in cnts:
        x, y, bw, bh = cv2.boundingRect(c)
        area = cv2.contourArea(c)
        if 3000 < area < 40000 and 40 < bw < 160 and 60 < bh < 220:
            if 120 < y < 830:  # tylko obszar gry, nie UI
                boxes.append((x, y, bw, bh, area))
    boxes.sort(key=lambda b: (b[1] // 100, b[0]))
    return boxes, bg


if __name__ == "__main__":
    img = cv2.imread(IMG)
    boxes, bg = find_barrels(img)
    print("bg", bg, "count", len(boxes))
    vis = img.copy()
    for i, (x, y, bw, bh, a) in enumerate(boxes):
        cx, cy = x + bw // 2, y + bh // 2
        cv2.rectangle(vis, (x, y), (x + bw, y + bh), (0, 0, 255), 2)
        cv2.putText(vis, str(i), (cx - 10, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 255), 2)
        print(i, "center", cx, cy, "box", bw, bh, "area", int(a))
    cv2.imwrite(OUT, vis)
