"""Ustawianie przycisku 'szybsze beczki' przez klikniecie na zrzucie.

Uzycie:
    python pick.py                  # zrobi zrzut i pokaze go w okienku
    python pick.py zrzut.png        # albo uzyj gotowego pliku

Klikasz na przycisku od boosta, zamykasz okno. Wspolrzedne zapisuja sie jako
ulamki planszy w config.json, wiec dzialaja przy kazdej rozdzielczosci.
Potem uruchom bota z --boost.
"""
import sys
import tkinter as tk

import cv2
from PIL import Image, ImageTk

import ads
import backends


def screenshot(path=None):
    if path:
        img = cv2.imread(path)
        if img is None:
            raise SystemExit(f"nie moge wczytac {path}")
        return img
    io, errors = backends.detect("auto")
    print("srodowisko:", io.name)
    for e in errors:
        print("  pominiete:", e)
    return io.grab()


def main():
    img = screenshot(sys.argv[1] if len(sys.argv) > 1 else None)
    rect = ads.board_rect(img)
    if not rect:
        raise SystemExit("nie widze planszy gry - zrob zrzut, gdy gra jest otwarta")
    bx, by, bw, bh = rect
    print(f"plansza: x={bx} y={by} w={bw} h={bh}")

    h, w = img.shape[:2]
    scale = min(1.0, 900.0 / w)
    shown = cv2.resize(img, (int(w * scale), int(h * scale)))
    shot = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(shown, cv2.COLOR_BGR2RGB)))

    root = tk.Tk()
    root.title("Kliknij przycisk 'szybsze beczki'")
    canvas = tk.Canvas(root, width=shown.shape[1], height=shown.shape[0])
    canvas.pack()
    canvas.create_image(0, 0, anchor="nw", image=shot)
    hint = tk.Label(root, text="Kliknij przycisk, ktory ma byc klikany automatycznie")
    hint.pack()

    def on_click(event):
        # piksel okienka -> piksel obrazu -> ulamek planszy
        ix, iy = event.x / scale, event.y / scale
        fx, fy = (ix - bx) / bw, (iy - by) / bh
        cfg = ads.load()
        cfg.setdefault("boost", {})
        cfg["boost"]["button"] = [round(fx, 4), round(fy, 4)]
        cfg["boost"].setdefault("idle", 8)
        cfg["boost"].setdefault("cooldown", 120)
        ads.save(cfg)
        print(f"zapisane: {cfg['boost']}")
        hint.config(text=f"zapisane: {fx:.3f}, {fy:.3f} - mozesz zamknac okno")
        canvas.create_oval(event.x - 8, event.y - 8, event.x + 8, event.y + 8,
                           outline="red", width=3)

    canvas.bind("<Button-1>", on_click)
    root.mainloop()


if __name__ == "__main__":
    main()
