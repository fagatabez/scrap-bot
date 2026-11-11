"""Znajduje, gdzie w oknie BlueStacks (na pulpicie) leży obraz telefonu.

Bierze zrzut z ADB (1600x900) i szuka go na pulpicie w różnych skalach.
Wynik: offset (ox, oy) i skala, czyli screen_xy = (ox + x*scale, oy + y*scale).
"""
import json
import subprocess
import sys

import cv2
import numpy as np
from mss import mss

ADB = r"C:\ADB\adb.exe"
DEVICE = "127.0.0.1:5555"


def screencap(path: str) -> np.ndarray:
    with open(path, "wb") as f:
        subprocess.run([ADB, "-s", DEVICE, "exec-out", "screencap", "-p"], stdout=f, check=True)
    return cv2.imread(path)


def grab_desktop() -> np.ndarray:
    with mss() as sct:
        shot = np.array(sct.grab(sct.monitors[1]))
    return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)


def find_device(dev: np.ndarray, desk: np.ndarray):
    best = (0.0, 1.0, (0, 0))
    for scale in np.arange(0.85, 1.25, 0.005):
        w, h = int(dev.shape[1] * scale), int(dev.shape[0] * scale)
        if w >= desk.shape[1] or h >= desk.shape[0]:
            continue
        tmpl = cv2.resize(dev, (w, h), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(desk, tmpl, cv2.TM_CCOEFF_NORMED)
        _, val, _, loc = cv2.minMaxLoc(res)
        if val > best[0]:
            best = (float(val), float(scale), loc)
    return best


if __name__ == "__main__":
    dev_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\wikto\AppData\Local\Temp\opencode\scrap\shot3.png"
    dev = screencap(dev_path)
    desk = grab_desktop()
    val, scale, (ox, oy) = find_device(dev, desk)
    out = {"match": round(val, 4), "scale": round(scale, 4), "offset": [ox, oy],
           "device": [dev.shape[1], dev.shape[0]], "desktop": [desk.shape[1], desk.shape[0]]}
    print(json.dumps(out))
