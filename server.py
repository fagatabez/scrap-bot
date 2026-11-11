"""Panel webowy do sterowania botem z telefonu.

Uruchom na PC:   python server.py
Na telefonie:    http://<IP_KOMPUTERA>:8765  (ten sam Wi-Fi)

Bot dziala w watku, panel pokazuje status i pozwala start/stop/pauze.
Napisany na czystym stdlib HTTP, wiec nie wymaga zadnych dodatkowych paczek.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import bot

PORT = 8765
HOST = "0.0.0.0"

CTRL = {"running": False, "thread": None, "prev_hwnd": None}

PAGE = """<!doctype html>
<html lang="pl"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scrap Bot</title>
<style>
 body{font-family:system-ui,Arial;background:#15171c;color:#eee;margin:0;padding:16px}
 h1{font-size:20px;margin:0 0 12px}
 .cards{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px}
 .c{background:#22252d;border-radius:10px;padding:12px;text-align:center}
 .c b{display:block;font-size:22px}
 .c span{font-size:12px;color:#9aa3b2}
 button{width:100%;padding:16px;font-size:18px;border:0;border-radius:10px;margin:4px 0}
 .start{background:#2e9e5b;color:#fff}.stop{background:#c0392b;color:#fff}
 .pause{background:#b8860b;color:#fff}.dry{background:#2c6fb5;color:#fff}
 .row{display:grid;grid-template-columns:1fr 1fr;gap:8px}
 #log{background:#0e1014;border-radius:8px;padding:10px;font-size:12px;white-space:pre-wrap;
      max-height:180px;overflow:auto;color:#a8b3c4;margin-top:12px}
 .dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:#666;margin-right:6px}
</style></head><body>
<h1><span class="dot" id="dot"></span>Scrap Clicker bot</h1>
<div class="cards">
 <div class="c"><b id="merges">0</b><span>merge'ow</span></div>
 <div class="c"><b id="rate">0</b><span>na sekunde</span></div>
 <div class="c"><b id="barrels">0</b><span>beczek</span></div>
 <div class="c"><b id="pairs">0</b><span>par</span></div>
</div>
<button class="start" onclick="cmd('start')">START</button>
<div class="row">
 <button class="pause" onclick="cmd('pause')">PAUZA</button>
 <button class="dry" onclick="cmd('dry')">PLAN (suchy przebieg)</button>
</div>
<button class="stop" onclick="cmd('stop')">STOP</button>
<div id="log"></div>
<script>
function cmd(c){fetch('/api/'+c,{method:'POST'});}
async function tick(){
  try{
    const r=await (await fetch('/api/status')).json();
    merges.textContent=r.merges; rate.textContent=r.rate.toFixed(2);
    barrels.textContent=r.barrels; pairs.textContent=r.pairs;
    dot.style.background=r.running?(r.paused?'#b8860b':'#2e9e5b'):'#666';
    if(r.log.length){log.textContent=r.log.join('\\n');log.scrollTop=log.scrollHeight;}
  }catch(e){}
}
setInterval(tick,1000); tick();
</script></body></html>"""


def _log(line):
    with bot.LOCK:
        CTRL.setdefault("log", []).append(f"{time.strftime('%H:%M:%S')} {line}")
        del CTRL["log"][:-40]


def _run_loop():
    """Watek roboczy: skaner + robotnik, az do STOP."""
    try:
        if bot.BACKEND == "win" and bot.win is not None:
            CTRL["prev_hwnd"] = bot.win.foreground_hwnd()
            bot.win.foreground()
        scanner = threading.Thread(target=bot.scanner_loop, daemon=True)
        scanner.start()
        _log("bot start")
        bot.worker_loop(forever=True)
    except Exception as exc:
        _log(f"blad: {exc}")
    finally:
        bot.STATE["stop"] = True
        if bot.BACKEND == "win" and bot.win is not None:
            bot.win.restore_foreground(CTRL.get("prev_hwnd"))
        CTRL["running"] = False
        _log("bot zatrzymany")


def start():
    if CTRL["running"]:
        return
    bot.STATE["stop"] = False
    bot.STATE["paused"] = False
    bot.STATS.update({"merges": 0, "rate": 0.0, "barrels": 0, "pairs": 0,
                      "started": time.time()})
    t = threading.Thread(target=_run_loop, daemon=True)
    CTRL["thread"] = t
    CTRL["running"] = True
    t.start()


def stop():
    bot.STATE["stop"] = True
    bot.STATE["paused"] = False
    _log("STOP")


def toggle_pause():
    bot.STATE["paused"] = not bot.STATE["paused"]
    _log("PAUZA" if bot.STATE["paused"] else "START")


def dry():
    _log("plan:")
    try:
        frame = bot.grab()
        boxes, _, prs = bot.pairs.find_pairs(frame)
        _log(f"beczek: {len(boxes)}, par: {len(prs)}")
        for i, j, d in prs[:10]:
            a = bot.center(boxes[i])
            b = bot.center(boxes[j])
            _log(f"  {a} -> {b} (dystans {d:.3f})")
    except Exception as exc:
        _log(f"blad: {exc}")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/api/status":
            st = {
                "running": CTRL["running"],
                "paused": bot.STATE["paused"],
                "storm": bot.STATE["storm"],
                "log": CTRL.get("log", [])[-15:],
            }
            st.update(bot.STATS)
            self._send(200, json.dumps(st))
        else:
            self._send(404, "{}")

    def do_POST(self):
        action = self.path.rsplit("/", 1)[-1]
        if action == "start":
            start()
        elif action == "stop":
            stop()
        elif action == "pause":
            toggle_pause()
        elif action == "dry":
            dry()
        self._send(200, json.dumps({"ok": True, "running": CTRL["running"]}))

    def log_message(self, *a):
        pass


def local_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=("win", "adb"), default="win")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()
    bot.BACKEND = args.backend
    ip = local_ip()
    print(f"[SERWER] panel: http://{ip}:{args.port}")
    print(f"[SERWER] na telefonie otworz: http://{ip}:{args.port}")
    print("[SERWER] zatrzymanie: Ctrl+C")
    ThreadingHTTPServer((HOST, args.port), Handler).serve_forever()
