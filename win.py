"""Sterowanie oknem BlueStacks bez ADB: zrzut okna + drag mysza.

Wspolrzedne sa liczone w pikselach okna, wiec nie trzeba zadnej kalibracji
skali - detekcja beczek i tak dziala w dowolnej rozdzielczosci.
"""
import ctypes
import threading
import time
from ctypes import wintypes

import cv2
import numpy as np

user32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor DPI
except Exception:
    user32.SetProcessDPIAware()

HWND = None
RECT = (0, 0, 0, 0)          # lewy, gorny, prawy, dolny ekranu


def find_window(title_part: str = "BlueStacks App Player"):
    """Najwieksze widoczne okno BlueStacks (pomija male okna-pomocniki)."""
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if title_part.lower() in buf.value.lower():
            r = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(r))
            found.append((r.right * r.bottom, hwnd, buf.value, (r.right, r.bottom)))
        return True

    user32.EnumWindows(cb, 0)
    if not found:
        return None
    found.sort(reverse=True)
    return found[0][1]


def pid_of(exe: str = "HD-Player.exe"):
    """PID procesu emulatora (okno szukamy po PID, bo tytul sie zmienia)."""
    import subprocess
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    pids = []
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[1].isdigit():
            pids.append(int(parts[1]))
    return pids[0] if pids else None


def find_window_by_pid(pid: int):
    """Najwieksze widoczne okno nalezace do procesu pid."""
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value != pid:
            return True
        r = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(r))
        if r.right > 200 and r.bottom > 300:
            found.append((r.right * r.bottom, hwnd))
        return True

    user32.EnumWindows(cb, 0)
    if not found:
        return None
    found.sort(reverse=True)
    return found[0][1]


def foreground_hwnd():
    return user32.GetForegroundWindow()


def restore_foreground(hwnd) -> None:
    """Oddaje fokus oknu, ktore mialo go przed startem bota."""
    if hwnd:
        try:
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass



def client_rect(hwnd):
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, pt.x + r.right, pt.y + r.bottom


_TLS = threading.local()


def grab(hwnd=None):
    """Zrzut klienta okna -> BGR (osobna instancja mss na watek)."""
    from mss import MSS
    global HWND, RECT
    HWND = hwnd or ensure_window()
    if not HWND:
        raise RuntimeError("Nie znaleziono okna gry")
    RECT = client_rect(HWND)
    left, top, right, bottom = RECT
    sct = getattr(_TLS, "sct", None)
    if sct is None:
        sct = MSS()
        _TLS.sct = sct
    raw = np.array(sct.grab({"left": left, "top": top,
                             "width": right - left, "height": bottom - top}))
    return cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)


def ensure_window():
    """Okno gry: najpierw po PID procesu, w razie braku po tytule."""
    global HWND
    if HWND:
        return HWND
    pid = pid_of()
    HWND = (find_window_by_pid(pid) if pid else None) or find_window()
    if not HWND:
        raise RuntimeError("Nie znaleziono okna gry (HD-Player / BlueStacks)")
    return HWND


def foreground(hwnd=None):
    global HWND
    HWND = hwnd or ensure_window()
    user32.ShowWindow(HWND, 9)          # SW_RESTORE
    user32.SetForegroundWindow(HWND)
    time.sleep(0.12)


def covered_fraction(hwnd=None, samples: int = 5) -> float:
    """Ile procent siatki okna jest zasloniete innym oknem (0.0 = czysto).

    Zrzut okna to zwykly zrzut ekranu, wiec nakladka = bot widzi obcy obraz
    i moze zle trafic. Dlatego przed akcja sprawdzamy punkty WindowFromPoint."""
    hwnd = hwnd or HWND or ensure_window()
    left, top, right, bottom = client_rect(hwnd)
    bad = total = 0
    for i in range(1, samples + 1):
        for j in range(1, samples + 1):
            x = left + (right - left) * i // (samples + 1)
            y = top + (bottom - top) * j // (samples + 1)
            h = user32.WindowFromPoint(wintypes.POINT(x, y))
            if not h:
                continue
            total += 1
            if h != hwnd and not user32.IsChild(hwnd, h):
                bad += 1
    return bad / total if total else 1.0


def drag(x1, y1, x2, y2, dur: int = 45, steps: int = None, hold: float = 0.005):
    """Prawdziwy drag mysza w wspolrzednych okna.

    dur = ile ms ma trwac ruch (bez klikniecia i puszczenia). Krotszy drag =
    wiecej merge'y na sekunde, ale gra musi zdazyc zobaczyc ruch.
    """
    left, top, _, _ = client_rect(ensure_window())
    sx1, sy1 = int(left + x1), int(top + y1)
    sx2, sy2 = int(left + x2), int(top + y2)
    if steps is None:
        steps = max(3, int(max(abs(sx2 - sx1), abs(sy2 - sy1)) // 45))
    per = max(0.003, (dur / 1000.0) / steps)
    user32.SetCursorPos(sx1, sy1)
    time.sleep(0.004)
    user32.mouse_event(0x0002, 0, 0, 0, 0)          # LEFTDOWN
    time.sleep(hold)
    for k in range(1, steps + 1):
        user32.SetCursorPos(int(sx1 + (sx2 - sx1) * k / steps),
                            int(sy1 + (sy2 - sy1) * k / steps))
        time.sleep(per)
    time.sleep(hold)
    user32.mouse_event(0x0004, 0, 0, 0, 0)          # LEFTUP


def hold_path(points, seg_ms: int = 110):
    """Trzyma lewy przycisk myszy i przeciaga po calej liscie punktow.

    W grze zbieranie scrapa dziala tylko przytrzymaniem i ruszeniem kursorem,
    wiec to jest jedna dluga gestia, a nie seria tapniec.
    """
    if not points:
        return
    left, top, _, _ = client_rect(ensure_window())
    pts = [(int(left + x), int(top + y)) for x, y in points]
    user32.SetCursorPos(*pts[0])
    time.sleep(0.02)
    user32.mouse_event(0x0002, 0, 0, 0, 0)              # LEFTDOWN
    per_seg = max(0.04, seg_ms / 1000.0)
    for (sx, sy), (ex, ey) in zip(pts, pts[1:]):
        steps = max(3, max(abs(ex - sx), abs(ey - sy)) // 25)
        for k in range(1, steps + 1):
            user32.SetCursorPos(int(sx + (ex - sx) * k / steps),
                                int(sy + (ey - sy) * k / steps))
            time.sleep(per_seg / steps)
    time.sleep(0.03)
    user32.mouse_event(0x0004, 0, 0, 0, 0)              # LEFTUP


def tap(x, y):
    left, top, _, _ = client_rect(ensure_window())
    user32.SetCursorPos(int(left + x), int(top + y))
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.04)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


if __name__ == "__main__":
    h = find_window()
    print("hwnd:", h)
    print("rect:", client_rect(h))
    img = grab(h)
    print("zrzut:", img.shape)
