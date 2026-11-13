"""Sterowanie oknem BlueStacks bez ADB: zrzut okna + drag mysza.

Wspolrzedne sa liczone w pikselach okna, wiec nie trzeba zadnej kalibracji
skali - detekcja beczek i tak dziala w dowolnej rozdzielczosci.
"""
import ctypes
import os
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
        if user32.IsIconic(HWND):
            user32.ShowWindow(HWND, 9)      # SW_RESTORE
            time.sleep(0.3)
        return HWND
    pid = pid_of()
    HWND = (find_window_by_pid(pid) if pid else None) or find_window()
    if not HWND:
        raise RuntimeError("Nie znaleziono okna gry (HD-Player / BlueStacks)")
    if user32.IsIconic(HWND):
        user32.ShowWindow(HWND, 9)
        time.sleep(0.3)
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


def _wait(sec: float):
    """Krotkie czekanie bez zaokraglania do taktu Windows.

    `time.sleep(0.004)` na Windows trwa ~4,2 ms, choc na Linuksie tyle, ile
    podano. Przy dragu sa trzy takie przerwy na merge, wiec roznica to kilka
    merge'y na sekunde. Do ~8 ms krecimy sie na liczniku, dluzsze czasy
    oddajemy systemowi.
    """
    if sec <= 0:
        return
    if sec > 0.008:
        time.sleep(sec)
        return
    end = time.perf_counter() + sec
    while time.perf_counter() < end:
        pass


def drag(x1, y1, x2, y2, dur: int = 45, steps: int = None, hold: float = 0.005,
         curve: float = 0.0, jitter: float = 0.0):
    """Prawdziwy drag mysza w wspolrzednych okna.

    dur = ile ms ma trwac ruch (bez klikniecia i puszczenia). Krotszy drag =
    wiecej merge'y na sekunde, ale gra musi zdazyc zobaczyc ruch.

    curve  - jak mocno ruch ma odchodzic od prostej (0 = prosta jak w automacie)
    jitter - losowe wahania punktow (px), żeby nie wygladalo jak robot
    """
    import random
    left, top, _, _ = client_rect(ensure_window())
    sx1, sy1 = int(left + x1), int(top + y1)
    sx2, sy2 = int(left + x2), int(top + y2)
    if jitter:
        sx1 += random.randint(-int(jitter), int(jitter))
        sy1 += random.randint(-int(jitter), int(jitter))
        sx2 += random.randint(-int(jitter), int(jitter))
        sy2 += random.randint(-int(jitter), int(jitter))
    if steps is None:
        steps = max(2, int(max(abs(sx2 - sx1), abs(sy2 - sy1)) // 60))
    per = max(0.002, (dur / 1000.0) / steps)
    # punkt kontrolny krzywej (troche z boku prostej) - jak ruch czlowieka
    cx = cy = 0
    if curve:
        dx, dy = sx2 - sx1, sy2 - sy1
        ln = max(1.0, (dx * dx + dy * dy) ** 0.5)
        off = random.uniform(-curve, curve) * ln
        cx = (sx1 + sx2) / 2 - dy / ln * off
        cy = (sy1 + sy2) / 2 + dx / ln * off
    user32.SetCursorPos(sx1, sy1)
    _wait(0.002)
    user32.mouse_event(0x0002, 0, 0, 0, 0)          # LEFTDOWN
    _wait(hold)
    for k in range(1, steps + 1):
        t = k / steps
        # krzywa kwadratowa (Bezier)
        px = (1 - t) ** 2 * sx1 + 2 * (1 - t) * t * cx + t * t * sx2
        py = (1 - t) ** 2 * sy1 + 2 * (1 - t) * t * cy + t * t * sy2
        user32.SetCursorPos(int(px), int(py))
        _wait(per)
    _wait(0.002)
    user32.mouse_event(0x0004, 0, 0, 0, 0)          # LEFTUP


def hold_path(points, total_ms: int = 1000):
    """Trzyma lewy przycisk myszy i przeciaga po calej liscie punktow.

    total_ms = ile ma trwac CALY tor (a nie kazdy odcinek), wiec gestia jest
    plynna nawet przy kilkuset punktach - tak wychodza kolka przy zbieraniu.
    """
    if not points:
        return
    left, top, _, _ = client_rect(ensure_window())
    pts = [(int(left + x), int(top + y)) for x, y in points]

    # najpierw policz kroki, zeby rozlozyc caly czas na wszystkie odcinki
    plan = []
    total_steps = 0
    for (sx, sy), (ex, ey) in zip(pts, pts[1:]):
        steps = max(1, max(abs(ex - sx), abs(ey - sy)) // 30)
        plan.append((sx, sy, ex, ey, steps))
        total_steps += steps
    per = max(0.0005, (total_ms / 1000.0) / max(total_steps, 1))

    user32.SetCursorPos(*pts[0])
    time.sleep(0.004)
    user32.mouse_event(0x0002, 0, 0, 0, 0)              # LEFTDOWN
    for sx, sy, ex, ey, steps in plan:
        for k in range(1, steps + 1):
            user32.SetCursorPos(int(sx + (ex - sx) * k / steps),
                                int(sy + (ey - sy) * k / steps))
            time.sleep(per)
    time.sleep(0.005)
    user32.mouse_event(0x0004, 0, 0, 0, 0)              # LEFTUP


def tap(x, y):
    left, top, _, _ = client_rect(ensure_window())
    user32.SetCursorPos(int(left + x), int(top + y))
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.04)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def fast_tap(x, y, hold=0.012):
    """Klik bez dlugiego trzymania - do szybkiego spamu (do ~60 klikow/s)."""
    left, top, _, _ = client_rect(ensure_window())
    user32.SetCursorPos(int(left + x), int(top + y))
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(hold)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


BACK_ARROW = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "assets", "back_arrow.png")


def find_back_button(frame):
    """Przycisk 'wstecz' BlueStacks w pasku na gorze okna.

    Dziala jak X w reklamie (zamyka reklame), a czasem jest jedynym
    widocznym sposobem na jej zamkniecie.
    """
    import cv2
    tmpl = cv2.imread(BACK_ARROW, cv2.IMREAD_GRAYSCALE)
    if tmpl is None:
        return None
    h, w = frame.shape[:2]
    strip = frame[:max(20, int(h * 0.10))]
    if strip.shape[0] < tmpl.shape[0] or strip.shape[1] < tmpl.shape[1]:
        return None
    gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
    best = None
    for s in (0.75, 0.9, 1.0, 1.15, 1.35):
        t = cv2.resize(tmpl, (max(4, int(tmpl.shape[1] * s)),
                              max(4, int(tmpl.shape[0] * s))),
                       interpolation=cv2.INTER_AREA)
        if gray.shape[0] < t.shape[0] or gray.shape[1] < t.shape[1]:
            continue
        res = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if best is None or mx > best[0]:
            best = (mx, loc[0] + t.shape[1] // 2, loc[1] + t.shape[0] // 2)
    if best and best[0] > 0.55:
        return (best[1], best[2])
    return None


if __name__ == "__main__":
    h = find_window()
    print("hwnd:", h)
    print("rect:", client_rect(h))
    img = grab(h)
    print("zrzut:", img.shape)
