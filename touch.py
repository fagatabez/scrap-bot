"""Dotyk bez ADB: wirtualne urzadzenie uinput (Android, wymaga roota).

Dzieki temu bot moze TRZYMAC palec i ruszac nim - tak jak mysz w oknie
BlueStacks. Bez tego kazdy odcinek to osobny proces `input swipe` (200 ms),
czyli kółeczek na telefonie trwalby minuty.

Uinput tworzy wirtualny ekran dotykowy (MULTI_TOUCH, protokol B), a my
wysylamy do niego zdarzenia ABS_MT_* - Android widzi to jak prawdziwy dotyk.
"""
import ctypes
import os
import struct
import time

UINPUT = "/dev/uinput"

# evdev
EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT = 0x00
ABS_MT_SLOT = 0x2F
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36
ABS_MT_TRACKING_ID = 0x39
BTN_TOUCH = 0x14A
INPUT_PROP_DIRECT = 0x01

# ioctl-y uinput
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_ABSBIT = 0x40045566
UI_SET_PROPBIT = 0x40045567

ABS_CNT = 0x40
UINPUT_MAX_NAME_SIZE = 80

# dlugosc pojedynczego zdarzenia: timeval(2x long) + type + code + value
_EV_FMT = "=llHHi"
_EV_SIZE = struct.calcsize(_EV_FMT)


def _uinput_user_dev(name, width, height):
    """Struktura uinput_user_dev: nazwa, id, efekty, zakresy osi."""
    dev = bytearray()
    dev += name.encode("utf-8")[:UINPUT_MAX_NAME_SIZE - 1]
    dev += b"\x00" * (UINPUT_MAX_NAME_SIZE - len(dev))
    dev += struct.pack("=HHHH", 0x03, 0x1234, 0x5678, 0x0001)   # bustype, vendor, product, version
    dev += struct.pack("=I", 0)                                   # ff_effects_max
    absmax = [0] * ABS_CNT
    absmin = [0] * ABS_CNT
    absfuzz = [0] * ABS_CNT
    absflat = [0] * ABS_CNT
    absmax[ABS_MT_POSITION_X] = max(1, int(width) - 1)
    absmax[ABS_MT_POSITION_Y] = max(1, int(height) - 1)
    absmin[ABS_MT_POSITION_X] = 0
    absmin[ABS_MT_POSITION_Y] = 0
    absfuzz[ABS_MT_POSITION_X] = 2
    absfuzz[ABS_MT_POSITION_Y] = 2
    dev += struct.pack("=" + "I" * ABS_CNT, *absmax)
    dev += struct.pack("=" + "I" * ABS_CNT, *absmin)
    dev += struct.pack("=" + "I" * ABS_CNT, *absfuzz)
    dev += struct.pack("=" + "I" * ABS_CNT, *absflat)
    return bytes(dev)


class Touch:
    """Wirtualny ekran dotykowy - jeden palec, z trzymaniem."""

    def __init__(self, width, height, name="scrap-bot-touch"):
        self.width = int(width)
        self.height = int(height)
        self.name = name
        self.fd = None
        self.slot = 0
        self.tracking_id = 1
        self.down_state = False
        self._open()

    # --------------------------------------------------------------- setup
    def _open(self):
        flags = os.O_WRONLY | getattr(os, "O_NONBLOCK", 0)
        try:
            self.fd = os.open(UINPUT, flags)
        except OSError as exc:
            raise OSError(f"nie moge otworzyc {UINPUT}: {exc}") from exc
        try:
            os.write(self.fd, _uinput_user_dev(self.name, self.width, self.height))
            self._ioctl(UI_SET_EVBIT, EV_SYN)
            self._ioctl(UI_SET_EVBIT, EV_KEY)
            self._ioctl(UI_SET_EVBIT, EV_ABS)
            self._ioctl(UI_SET_KEYBIT, BTN_TOUCH)
            self._ioctl(UI_SET_ABSBIT, ABS_MT_SLOT)
            self._ioctl(UI_SET_ABSBIT, ABS_MT_POSITION_X)
            self._ioctl(UI_SET_ABSBIT, ABS_MT_POSITION_Y)
            self._ioctl(UI_SET_ABSBIT, ABS_MT_TRACKING_ID)
            self._ioctl(UI_SET_PROPBIT, INPUT_PROP_DIRECT)
        except OSError:
            self.close()
            raise
        # Android musi zarejestrowac urzadzenie
        time.sleep(0.4)

    def _ioctl(self, request, arg):
        try:
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
        except OSError:
            return                      # nie-Linux (testy) - pomijamy
        if libc.ioctl(self.fd, request, arg) < 0:
            err = ctypes.get_errno()
            raise OSError(f"ioctl {request:#x} -> {os.strerror(err)}")

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None

    # --------------------------------------------------------------- zdarzenia
    def _pack(self, etype, code, value):
        now = time.time()
        return struct.pack(_EV_FMT, int(now), int((now % 1) * 1e6),
                           etype, code, int(value))

    def _write(self, parts):
        """Jeden zapis = cala paczka zdarzen (mniej syscalli)."""
        os.write(self.fd, b"".join(parts))

    def _pos(self, x, y):
        return (self._pack(EV_ABS, ABS_MT_POSITION_X,
                            max(0, min(self.width - 1, int(x)))),
                self._pack(EV_ABS, ABS_MT_POSITION_Y,
                           max(0, min(self.height - 1, int(y)))))

    # --------------------------------------------------------------- akcje
    def down(self, x, y):
        px, py = self._pos(x, y)
        self._write([self._pack(EV_ABS, ABS_MT_SLOT, self.slot),
                     self._pack(EV_ABS, ABS_MT_TRACKING_ID, self.tracking_id),
                     px, py,
                     self._pack(EV_KEY, BTN_TOUCH, 1),
                     self._pack(EV_SYN, SYN_REPORT, 0)])
        self.down_state = True

    def move(self, x, y):
        if not self.down_state:
            return
        px, py = self._pos(x, y)
        self._write([px, py, self._pack(EV_SYN, SYN_REPORT, 0)])

    def up(self):
        if not self.down_state:
            return
        self._write([self._pack(EV_ABS, ABS_MT_TRACKING_ID, -1),
                     self._pack(EV_KEY, BTN_TOUCH, 0),
                     self._pack(EV_SYN, SYN_REPORT, 0)])
        self.down_state = False
        self.tracking_id = (self.tracking_id % 60000) + 1

    def tap(self, x, y, hold_ms=40):
        self.down(x, y)
        time.sleep(max(0.005, hold_ms / 1000.0))
        self.up()

    def swipe(self, x1, y1, x2, y2, dur_ms=45, steps=6):
        """Przeciagniecie jednym gestem - szybkie, bo to jeden zapis."""
        self.down(x1, y1)
        steps = max(2, int(steps))
        per = max(0.004, (dur_ms / 1000.0) / steps)
        for k in range(1, steps + 1):
            self.move(x1 + (x2 - x1) * k / steps,
                      y1 + (y2 - y1) * k / steps)
            time.sleep(per)
        self.up()

    def hold_path(self, points, total_ms=1000):
        """Trzyma palec i prowadzi go po calej liscie punktow.

        Czas jest liczony bezwzglednie (kazdy punkt ma swoja planowana
        chwile), wiec krótkie usypienia systemu nie rozciagaja gestu.
        """
        if not points:
            return
        pts = [(int(x), int(y)) for x, y in points]
        self.down(*pts[0])
        start = time.perf_counter()
        total = max(0.05, total_ms / 1000.0)
        n = len(pts) - 1
        for i in range(1, len(pts)):
            due = start + total * i / max(n, 1)
            now = time.perf_counter()
            if due > now:
                time.sleep(min(0.02, due - now))
            self.move(*pts[i])
        self.up()


def available() -> bool:
    """Czy mozna uzyc uinput (plik istnieje i da sie go otworzyc)."""
    if not os.path.exists(UINPUT):
        return False
    try:
        fd = os.open(UINPUT, os.O_WRONLY | os.O_NONBLOCK)
    except OSError:
        return False
    os.close(fd)
    return True
