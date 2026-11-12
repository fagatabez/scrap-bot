"""Wykrywanie srodowiska i szybkie wejscie/wyjscie (zrzut, tap, swipe).

Bot ma dzialac tak samo na telefonie z rootem, na telefonie sterowanym ADB,
na BlueStacks przez ADB i na oknie BlueStacks na pulpicie. Wybor jest
automatyczny - kolejnosc: root -> ADB -> okno Windows.

Dlaczego "szybkie": zmierzone na tym PC uruchomienie jednego procesu adb
to ~22 ms, a wykrycie par w obrazie 900x1600 to ~58 ms. Przy respie beczki
co 0.3 s nie ma miejsca na odpalanie procesu na kazdy tap, wiec:
  * tapy i swipe'y ida do stalej powloki (jedno 'su -c sh' / 'adb shell'),
  * zrzuty ida ze stalej rury screencap (bez kodowania i bez procesu na ramke),
  * obraz jest skalowany do szerokosci MAX_W, a wspolrzedne przeliczane z powrotem.
"""
import os
import struct
import subprocess
import sys
import threading

import cv2
import numpy as np

ADB = os.environ.get("ADB_PATH", r"C:\ADB\adb.exe")
DEVICE = os.environ.get("ADB_DEVICE", "")
DEFAULT_DEVICE = "127.0.0.1:5555"      # BlueStacks / emulator na tym samym PC
MAX_W = 900                              # do takiej szerokosci skalujemy obraz
PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _run(cmd, timeout=20, **kw):
    return subprocess.run(cmd, capture_output=True, timeout=timeout,
                          check=False, **kw)


def _resize(img):
    """Zmniejsza obraz do MAX_W, zwraca (obraz, skala obraz->ekran)."""
    h, w = img.shape[:2]
    if w <= MAX_W:
        return img, 1.0
    s = MAX_W / w
    small = cv2.resize(img, (MAX_W, int(round(h * s))), interpolation=cv2.INTER_AREA)
    return small, 1.0 / s


class Stream:
    """Stala rura ze zrzutami PNG. Kazda ramka to jeden PNG w strumieniu.

    Dzieki temu zrzut nie kosztuje uruchomienia procesu ani kodowania po
    naszej stronie - urzadzenie robi je w tle, a my tylko czytamy najswiezsza.
    """

    def __init__(self, popen_cmd):
        self.proc = subprocess.Popen(popen_cmd, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, bufsize=1 << 20)
        self.buf = b""
        self.lock = threading.Lock()

    def _more(self):
        chunk = self.proc.stdout.read1(1 << 16)
        if not chunk:
            raise RuntimeError("strumien zrzutow sie zamknal")
        self.buf += chunk

    def read(self):
        """Najswiezsza ramka jako obraz BGR."""
        with self.lock:
            # ramka jest miedzy dwoma naglowkami PNG
            while True:
                first = self.buf.find(PNG_SIG)
                if first < 0:
                    if len(self.buf) > 16:
                        self.buf = self.buf[-8:]
                    self._more()
                    continue
                second = self.buf.find(PNG_SIG, first + 8)
                if second < 0:
                    self._more()
                    continue
                data = self.buf[first:second]
                self.buf = self.buf[second:]
                img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    return img

    def close(self):
        try:
            self.proc.kill()
        except Exception:
            pass


class Base:
    name = "?"
    scale = 1.0                       # obraz -> wspolrzedne urzadzenia
    async_input = False               # True = akcje tylko sie kolejka, nie czekaja

    def grab(self):
        raise NotImplementedError

    def tap(self, x, y):
        raise NotImplementedError

    def swipe(self, x1, y1, x2, y2, dur=90):
        self.tap(x1, y1)

    def key(self, code):
        """Klawisz systemowy (4 = WSTECZ). Domyslnie nic - nadpisuja go IO."""
        return None

    def hold_path(self, points, seg_ms=110, total_ms=None):
        """Przeciagnij trzymajac przez wszystkie punkty (zbieranie scrapa).

        points: [(x, y), ...] w wspolrzednych obrazu. Domyslnie kazdy odcinek
        idzie jako osobny swipe - palec/klawisz puszcza sie miedzy odcinkami,
        ale to i tak duzo lepsze niz pojedyncze tapy.
        """
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            self.swipe(x1, y1, x2, y2, dur=seg_ms)

    def to_dev(self, x, y):
        return int(round(x / self.scale)), int(round(y / self.scale))

    def info(self):
        return {"backend": self.name, "scale": round(self.scale, 3)}


class ShellIO(Base):
    """Wspolna czesc: stala powloka do tapow, opcjonalny strumien zrzutow."""

    async_input = True          # pisze do powloki i wraca, gra wykonuje w tle

    def __init__(self, popen_shell, popen_screencap, shot_path):
        self.sh = subprocess.Popen(popen_shell, stdin=subprocess.PIPE,
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, bufsize=1 << 16)
        self.shot_path = shot_path
        self.stream = None
        self.stream_err = None
        if popen_screencap:
            if os.environ.get("SCRAP_NO_STREAM", "") not in ("", "0"):
                self.stream_err = "wylaczony przez SCRAP_NO_STREAM"
            else:
                try:
                    self.stream = Stream(popen_screencap)
                    self.stream.read()          # sprawdzenie pierwszej ramki
                except Exception as exc:
                    self.stream = None
                    self.stream_err = str(exc)[:120]

    # ---------------------------------------------------------------- zrzut
    def grab(self):
        if self.stream is not None:
            try:
                img, self.scale = _resize(self.stream.read())
                return img
            except Exception:
                self.stream = None                      # rura padla - fallback
                self.stream_err = "rura padla w trakcie"
        img, self.scale = self._grab_once()
        return img

    def _grab_once(self):
        raise NotImplementedError

    # ---------------------------------------------------------------- akcje
    def _send(self, line):
        try:
            self.sh.stdin.write((line + "\n").encode())
            self.sh.stdin.flush()
        except Exception:
            raise RuntimeError("powloka wejsciowa sie zamknela")

    def tap(self, x, y):
        dx, dy = self.to_dev(x, y)
        self._send(f"input tap {dx} {dy}")

    def swipe(self, x1, y1, x2, y2, dur=90):
        a = self.to_dev(x1, y1)
        b = self.to_dev(x2, y2)
        self._send(f"input swipe {a[0]} {a[1]} {b[0]} {b[1]} {int(dur)}")

    def hold_path(self, points, seg_ms=110, total_ms=None):
        """Caly tor jednym poleceniem: powloka wykona odcinki po kolei.

        Finger jest podnoszony tylko na moment miedzy odcinkami (input swipe
        nie umie trzymac miedzy komendami), ale kazdy odcinek to prawdziwy
        przeciag, wiec zbiera wszystko, co mija - inaczej niz 20 tapow.
        """
        cmds = []
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            a = self.to_dev(x1, y1)
            b = self.to_dev(x2, y2)
            cmds.append(f"input swipe {a[0]} {a[1]} {b[0]} {b[1]} {int(seg_ms)}")
        if cmds:
            self._send("; ".join(cmds))

    def key(self, code):
        self._send(f"input keyevent {code}")


class RootIO(ShellIO):
    """Telefon z rootem: zrzut i tapy przez stale 'su -c sh'."""

    name = "root"

    def __init__(self, shot_path):
        if _run(["su", "-c", "id"]).stdout.find(b"uid=0") < 0:
            raise RuntimeError("su nie daje roota")
        super().__init__(
            popen_shell=["su", "-c", "sh"],
            popen_screencap=["su", "-c", "while :; do screencap -p; done"],
            shot_path=shot_path,
        )

    def _grab_once(self):
        _run(["su", "-c", f"screencap -p > {self.shot_path}"])
        img = cv2.imread(self.shot_path)
        if img is None:
            raise RuntimeError("screencap (root) nieudany")
        return _resize(img)

class AdbIO(ShellIO):
    """Telefon lub emulator przez ADB (takze sam ze soba po Wi-Fi)."""

    name = "adb"

    def __init__(self, device, shot_path):
        self.device = device
        if ":" in device:
            _run([ADB, "connect", device], timeout=15)
        out = _run([ADB, "-s", device, "shell", "echo", "ok"]).stdout
        if b"ok" not in out:
            raise RuntimeError(f"brak urzadzenia {device}")
        super().__init__(
            popen_shell=[ADB, "-s", device, "shell"],
            popen_screencap=[ADB, "-s", device, "exec-out",
                             "while :; do screencap -p; done"],
            shot_path=shot_path,
        )

    def _grab_once(self):
        data = _run([ADB, "-s", self.device, "exec-out", "screencap", "-p"]).stdout
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("screencap (adb) nieudany")
        return _resize(img)


class WinIO(Base):
    """Okno BlueStacks na pulpicie (bez ADB). Wymaga widocznego okna."""

    name = "win"

    def __init__(self):
        import win
        self.win = win
        self.scale = 1.0
        self.win.ensure_window()          # brak okna = ten tryb nie dziala

    def grab(self):
        self.scale = 1.0
        return self.win.grab()

    def tap(self, x, y):
        self.win.tap(x, y)

    def swipe(self, x1, y1, x2, y2, dur=90):
        self.win.drag(x1, y1, x2, y2, dur=dur)

    def hold_path(self, points, seg_ms=110, total_ms=None):
        """Trzyma lewy przycisk myszy przez caly tor - tak gra zbiera scrap."""
        self.win.hold_path(points, total_ms=total_ms or (len(points) - 1) * seg_ms)

    def info(self):
        return {"backend": "win", "window": self.win.ensure_window()}


def adb_devices():
    out = _run([ADB, "devices"]).stdout.decode("utf-8", "ignore")
    devs = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devs.append(parts[0])
    return devs


def detect(prefer="auto", shot_path=None):
    """Zwraca gotowy obiekt IO oraz opis, gdzie dziala.

    prefer: auto | root | adb | win
    """
    shot_path = shot_path or os.path.join(
        os.environ.get("TMPDIR", os.environ.get("TEMP", ".")), "scrap_bot_shot.png")
    errors = []

    def try_(name, fn):
        if prefer not in ("auto", name):
            return None
        try:
            return fn()
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            return None

    if prefer in ("auto", "root"):
        io = try_("root", lambda: RootIO(shot_path))
        if io:
            return io, errors

    if prefer in ("auto", "adb"):
        def _adb():
            devs = [DEVICE] if DEVICE else []
            devs += [d for d in adb_devices() if d not in devs]
            if DEFAULT_DEVICE not in devs and not devs:
                devs = [DEFAULT_DEVICE]
            last = None
            for dev in devs:
                try:
                    return AdbIO(dev, shot_path)
                except Exception as exc:
                    last = exc
            raise last or RuntimeError("brak urzadzen ADB")
        io = try_("adb", _adb)
        if io:
            return io, errors

    if prefer in ("auto", "win") and sys.platform == "win32":
        io = try_("win", WinIO)
        if io:
            return io, errors

    raise RuntimeError("nie znalazlem srodowiska: " + "; ".join(errors or ["brak"]))
