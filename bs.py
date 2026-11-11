"""Sterowanie BlueStacks: zrzut przez ADB + kliknięcia myszą po współrzędnych telefonu.

Kalibracja: obraz gry 900x1600 jest skalowany do rozmiaru okna (np. 504x896).
"""
import ctypes
import subprocess
import time

import cv2
import numpy as np
import pyautogui

ADB = r"C:\ADB\adb.exe"
DEVICE = "127.0.0.1:5555"
HWND = 920216
SHOT = r"C:\Users\wikto\AppData\Local\Temp\opencode\scrap\live.png"

# wynik kalibracji (uzupelnia calibrate())
OFFSET = (184, 75)
SCALE = 0.56

u = ctypes.windll.user32
pyautogui.FAILSAFE = False


def foreground() -> None:
    if u.GetForegroundWindow() != HWND:
        u.ShowWindow(HWND, 9)
        u.SetForegroundWindow(HWND)
        time.sleep(0.15)


def screencap(path: str = SHOT) -> np.ndarray:
    with open(path, "wb") as f:
        subprocess.run([ADB, "-s", DEVICE, "exec-out", "screencap", "-p"], stdout=f, check=True)
    return cv2.imread(path)


def grab_desktop() -> np.ndarray:
    from mss import MSS
    with MSS() as sct:
        return cv2.cvtColor(np.array(sct.grab(sct.monitors[1])), cv2.COLOR_BGRA2BGR)


def calibrate(dev: np.ndarray | None = None):
    """Ustala OFFSET i SCALE, szukajac obrazu telefonu na pulpicie."""
    global OFFSET, SCALE
    foreground()
    time.sleep(0.4)
    if dev is None:
        dev = screencap(r"C:\Users\wikto\AppData\Local\Temp\opencode\scrap\cal_live.png")
    desk = grab_desktop()
    best = (0.0, SCALE, OFFSET)
    for scale in np.arange(0.35, 1.0, 0.005):
        w, h = int(dev.shape[1] * scale), int(dev.shape[0] * scale)
        if w >= desk.shape[1] or h >= desk.shape[0]:
            continue
        t = cv2.resize(dev, (w, h), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(desk, t, cv2.TM_CCOEFF_NORMED)
        _, val, _, loc = cv2.minMaxLoc(res)
        if val > best[0]:
            best = (float(val), float(scale), loc)
    SCALE = best[1]
    OFFSET = best[2]
    return best


def tap(x: float, y: float, delay: float = 0.02) -> None:
    foreground()
    pyautogui.moveTo(OFFSET[0] + x * SCALE, OFFSET[1] + y * SCALE, duration=0)
    pyautogui.click()
    time.sleep(delay)


def swipe(x1, y1, x2, y2, duration=0.3, delay=0.4):
    foreground()
    pyautogui.moveTo(OFFSET[0] + x1 * SCALE, OFFSET[1] + y1 * SCALE)
    pyautogui.dragTo(OFFSET[0] + x2 * SCALE, OFFSET[1] + y2 * SCALE, duration=duration, button="left")
    time.sleep(delay)


if __name__ == "__main__":
    foreground()
    print(calibrate())
