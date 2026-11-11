"""OCR ekranu gry przez Windows.Media.Ocr (bez instalowania tesseracta).

Jedno wywolanie to osobny proces PowerShell (~0.5-1.5 s), wiec uzywamy go
tylko przy okazji ulepszen i restartu, nigdy w petli skanowania.
"""
import json
import os
import subprocess
import threading

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
PS1 = os.path.join(HERE, "ocr.ps1")
TMP = os.path.join(os.environ.get("TEMP", HERE), "scrap_bot_ocr")
os.makedirs(TMP, exist_ok=True)

_LOCK = threading.Lock()
_WARNED = False


def read(img):
    """Zwraca {"text": str, "lines": [{"text","x","y","w","h"}]}.

    Bledy nie zatrzymuja bota - zwracany jest pusty wynik.
    """
    global _WARNED
    src = os.path.join(TMP, "shot.png")
    out = os.path.join(TMP, "shot.json")
    with _LOCK:
        try:
            cv2.imwrite(src, img)
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", PS1, "-Path", src, "-Out", out],
                capture_output=True, timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if not os.path.exists(out):
                if not _WARNED:
                    print("[BOT] OCR nie dziala:", proc.stderr.decode("utf-8", "ignore")[:200])
                    _WARNED = True
                return {"text": "", "lines": []}
            with open(out, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"text": "", "lines": []}
            data.setdefault("lines", [])
            data.setdefault("text", "")
            return data
        except Exception as exc:
            if not _WARNED:
                print(f"[BOT] OCR blad: {exc}")
                _WARNED = True
            return {"text": "", "lines": []}
