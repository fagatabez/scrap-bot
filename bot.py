"""Scrap Clicker 2 - bot v6: laczy identyczne beczki BEZ biblioteki szablonow.

Dwa watki:
  * skaner  - ciagle robi zrzut okna, wykrywa beczki i liczy pary,
  * robotnik - bierze liste par i od razu przeciaga beczke na beczke.
Skan trwa w tle, wiec kolejna lista jest gotowa, zanim skonczy sie poprzedni drag.

Kontrola jakosci (zastepuje wolna weryfikacje po kazdym dragu):
  * nowa lista jest brana tylko wtedy, gdy zrzut zrobiono po animacji
    poprzedniego merge'a (SETTLE),
  * pola dotkniete dragiem sa ignorowane przez ANIM sekund, bo w tym czasie
    gra dokupuje nowa beczke i odtwarza animacje,
  * ta sama para nie jest powtarzana czesciej niz co RETRY sekund, wiec
    pojedynczy falszywy match nie zapetla bota.

Sztorm (przyciemniona plansza) zatrzymuje laczenie i wlacza zbieranie scrapa:
tap w kazde pole siatki 4x5. Puste, szare pola sa pomijane i nie licza sie
jako beczki.

Uzycie:
    python bot.py                 # domyslnie: skaner + robotnik, F8 pauza, F9 stop
    python bot.py --safe          # wolniej i ostrozniej (dluzsze czekanie)
    python bot.py --dry           # tylko pokaz plan, bez dotykania gry
    python bot.py --once          # jeden przebieg i koniec
    python bot.py --merge 3       # jeden przebieg, maks. 3 merge'y
    python bot.py --until-done    # konczy, gdy nie ma czego laczyc
    python bot.py --collect       # tylko zbieraj scrap (20 tapow)
    python bot.py --storm-merge   # lacz takze w sztormie (po kupieniu za gwiazdy)
    python bot.py --backend adb   # telefon przez ADB zamiast okna

--fast i --loop sa nadal przyjmowane, ale nie sa juz potrzebne: tryb ciagly
i szybkie dragi sa domyslne.
"""
import argparse
import threading
import time

import os
import tempfile

import pairs

try:                       # sterowanie oknem Windows - tylko na PC
    import win
except Exception:          # na telefonie (Termux) dziala tylko backend adb
    win = None

SHOT = os.path.join(tempfile.gettempdir(), "scrap_bot_shot.png")

BACKEND = "win"
STORM_MERGE = False         # True po kupieniu laczenia w sztormie za gwiazdy

SCAN_INTERVAL = 0.03        # odstep miedzy skanami planszy
SETTLE = 0.12               # zrzut musi byc nowszy niz drag + SETTLE
MERGE_GAP = 0.08            # przerwa miedzy kolejnymi dragami
ANIM = 0.55                 # tyle sekund nie ufamy polom dotknietym dragiem
RETRY = 1.5                 # ta sama para moze byc powtorzona po tym czasie
VERIFY_THRESHOLD = 0.35     # zmiana wygladu pola = merge przeszedl (tryb --once)
TAP_GAP = 0.07              # odstep miedzy tapami przy zbieraniu
STORM_PAUSE = 0.35          # przerwa miedzy cyklami zbierania w sztormie
IDLE = 0.10                 # przerwa, gdy nie ma czego laczyc

STATE = {
    "plan": None,           # {"id", "ts", "boxes", "prs"}
    "serial": 0,
    "storm": False,
    "stop": False,
    "paused": False,
    "cover": 0.0,
}
STATS = {                 # statystyki na panel webowy
    "merges": 0,
    "rate": 0.0,
    "barrels": 0,
    "pairs": 0,
    "started": 0.0,
}
LOCK = threading.Lock()
ACTIONS = []                # ostatnie dragi: (x1, y1, x2, y2, czas)


def grab():
    if BACKEND == "adb":
        return pairs.screencap(SHOT)
    return win.grab()


def tap(x, y):
    if BACKEND == "adb":
        import subprocess
        subprocess.run([pairs.ADB, "-s", pairs.DEVICE, "exec-out", "input", "tap",
                        str(int(x)), str(int(y))], check=False)
    else:
        win.tap(x, y)


def do_merge(a, b):
    if BACKEND == "adb":
        import subprocess
        subprocess.run([pairs.ADB, "-s", pairs.DEVICE, "exec-out", "input", "swipe",
                        str(a[0]), str(a[1]), str(b[0]), str(b[1]), "170"], check=False)
    else:
        win.drag(a[0], a[1], b[0], b[1], steps=10, hold=0.025)


def center(box):
    return box[0] + box[2] // 2, box[1] + box[3] // 2


def collect(frame=None, verbose=True):
    """Zbiera scrap: tap w kazde pole siatki 4x5. W sztormie tylko to wolno,
    a siatka jest liczona z pola gry, wiec nie zalezy od kolorow beczek."""
    frame = frame if frame is not None else grab()
    rect = pairs.playfield_rect(frame)
    if not rect:
        if verbose:
            print("[BOT] nie widze pola gry - nie zbieram")
        return 0
    pts = pairs.grid_centers(rect)
    for x, y in pts:
        tap(x, y)
        time.sleep(TAP_GAP)
    if verbose:
        print(f"[BOT] sztorm: zebrane {len(pts)} pol")
    return len(pts)


# ------------------------------------------------------------------ skaner
def scanner_loop():
    """Ciagle skanuje plansze i publikuje najnowsza liste par."""
    last_cover = 0.0
    fails = 0
    while not STATE["stop"]:
        if STATE["paused"]:
            time.sleep(0.08)
            continue

        try:
            now = time.time()
            if BACKEND == "win" and now - last_cover > 0.7:
                cover = win.covered_fraction()
                last_cover = time.time()
                with LOCK:
                    STATE["cover"] = cover
                if cover > 0.05:
                    with LOCK:
                        STATE["plan"] = None
                        STATE["serial"] += 1
                    time.sleep(0.3)
                    continue

            frame = grab()
            ts = time.time()

            if pairs.is_storm(frame) and not STORM_MERGE:
                with LOCK:
                    STATE["storm"] = True
                    STATE["plan"] = None
                    STATE["serial"] += 1
            else:
                boxes, _, prs = pairs.find_pairs(frame)
                with LOCK:
                    STATE["storm"] = False
                    STATE["serial"] += 1
                    STATE["plan"] = {"id": STATE["serial"], "ts": ts,
                                     "boxes": boxes, "prs": prs}
                    STATS["barrels"] = len(boxes)
                    STATS["pairs"] = len(prs)
            fails = 0
        except Exception as exc:                    # zrzut mogl sie nie udac
            fails += 1
            if fails <= 3:
                print(f"[BOT] skan: {exc}")
            if fails > 20:
                print("[BOT] skan nie dziala - koncze")
                STATE["stop"] = True
                break
            time.sleep(0.5)

        time.sleep(SCAN_INTERVAL)


# ------------------------------------------------------------------ robotnik
def _pair_key(a, b):
    return tuple(sorted(((a[0] // 30, a[1] // 30), (b[0] // 30, b[1] // 30))))


def _remember_action(a, b):
    now = time.time()
    ACTIONS.append((a[0], a[1], b[0], b[1], now))
    ACTIONS[:] = [x for x in ACTIONS if now - x[4] <= 5.0]


def _blocked(a, b, now, radius):
    """Czy ktorys koniec pary lezy na polu dotknietym niedawno dragiem."""
    r2 = radius * radius
    for x1, y1, x2, y2, t in ACTIONS:
        if now - t > ANIM:
            continue
        for cx, cy in (a, b):
            if (cx - x1) ** 2 + (cy - y1) ** 2 <= r2:
                return True
            if (cx - x2) ** 2 + (cy - y2) ** 2 <= r2:
                return True
    return False


def worker_loop(forever=True):
    total = 0
    t0 = time.time()
    last_report = t0
    last_total = -1
    last_n = 0
    last_action = 0.0
    last_progress = t0
    last_cover_check = 0.0
    warned_cover = False
    storm_announced = False
    cur = None
    cur_id = None
    idx = 0
    recent = {}

    while not STATE["stop"]:
        if STATE["paused"]:
            time.sleep(0.1)
            continue

        now = time.time()
        if BACKEND == "win" and now - last_cover_check > 0.25:
            last_cover_check = now
            if win.covered_fraction() > 0.05:
                if not warned_cover:
                    print("[BOT] STOP: okno gry zasloniete innym programem "
                          "- czekam, az bedzie widoczne w calosci.")
                    warned_cover = True
                cur = None
                cur_id = None
                time.sleep(0.35)
                continue
            warned_cover = False

        with LOCK:
            storm = STATE["storm"]
            plan = STATE["plan"]

        if storm:
            cur = None
            cur_id = None
            if not storm_announced:
                print("[BOT] sztorm - zbieram scrap (laczenie zablokowane)")
                storm_announced = True
            if not forever:
                print("[BOT] sztorm - koncze, w sztormie nie da sie laczyc")
                break
            collect(verbose=False)
            time.sleep(STORM_PAUSE)
            continue
        storm_announced = False

        if plan is None:
            time.sleep(0.02)
            continue

        if cur is None:
            if plan["ts"] < last_action + SETTLE:
                time.sleep(0.01)                   # zrzut sprzed animacji
                continue
            cur, cur_id, idx = plan, plan["id"], 0
            last_n = len(plan["boxes"])

        if idx >= len(cur["prs"]):
            cur = None
            cur_id = None
            if not forever and time.time() - last_progress > 2.0:
                break
            time.sleep(IDLE)
            continue

        boxes, prs = cur["boxes"], cur["prs"]
        widths = sorted(b[2] for b in boxes)
        radius = 0.45 * widths[len(widths) // 2] if widths else 45.0
        now = time.time()

        chosen = None
        while idx < len(prs):
            i, j, _ = prs[idx]
            idx += 1
            if i >= len(boxes) or j >= len(boxes):
                continue
            a = center(boxes[i])
            b = center(boxes[j])
            if _blocked(a, b, now, radius):
                continue
            key = _pair_key(a, b)
            if now - recent.get(key, 0.0) < RETRY:
                continue
            chosen = (a, b, key)
            break

        if chosen is None:
            cur = None
            cur_id = None
            if not forever and time.time() - last_progress > 2.0:
                break
            time.sleep(IDLE)
            continue

        a, b, key = chosen
        _remember_action(a, b)                      # zanim skaner zrobi zrzut
        do_merge(a, b)
        last_action = time.time()
        recent[key] = last_action
        last_progress = last_action
        total += 1
        STATS["merges"] = total

        now = time.time()
        if now - last_report >= 1.0 and total != last_total:
            rate = total / max(now - t0, 1e-6)
            print(f"[BOT] merge'y: {total} | {rate:.2f}/s | beczek: {last_n}")
            last_report = now
            last_total = total
            STATS["rate"] = rate
            STATS["merges"] = total

        time.sleep(MERGE_GAP)                       # czas na animacje merge'a

    return total


# ------------------------------------------------------------------ jeden przebieg
def merge_pass(max_merges=None, dry=False, verbose=True):
    """Skan + merge'e po kolei (tryb --once / --merge / --dry)."""
    if BACKEND == "win":
        hiding = win.covered_fraction()
        if hiding > 0.05:
            print(f"[BOT] STOP: okno gry zasloniete w {hiding * 100:.0f}%.")
            return 0, 0, False

    frame = grab()

    if pairs.is_storm(frame) and not STORM_MERGE:
        if dry:
            rect = pairs.playfield_rect(frame)
            extra = f", tapnalbym {len(pairs.grid_centers(rect))} pol" if rect else ""
            print(f"[BOT] sztorm wykryty - w grze tylko zbieranie{extra}")
            return 0, 0, True
        if verbose:
            print("[BOT] sztorm - laczenie zablokowane, zbieram scrap")
        collect(frame, verbose)
        return 0, 0, True

    boxes, _, prs = pairs.find_pairs(frame)
    if dry:
        print(f"[BOT] beczek: {len(boxes)}, par: {len(prs)}")
        for i, j, d in prs[:max_merges or len(prs)]:
            print(f"  merge {center(boxes[i])} -> {center(boxes[j])}  (dystans {d:.3f})")
        return 0, len(boxes), False

    todo = prs[:max_merges] if max_merges is not None else prs
    ok = 0
    for i, j, _ in todo:
        a, b = center(boxes[i]), center(boxes[j])
        sig = pairs.describe(frame, boxes[j])
        do_merge(a, b)
        time.sleep(max(SETTLE, 0.25))
        after = grab()
        crop = pairs.barrel_crop(after, boxes[j])
        delta = 1.0 if crop.size == 0 else pairs.distance(sig, pairs.describe_crop(crop))
        if delta > VERIFY_THRESHOLD:
            ok += 1
        elif verbose:
            print(f"  merge {a} -> {b}: BRAK zmiany ({delta:.2f})")

    if verbose:
        print(f"[BOT] beczek: {len(boxes)}, par: {len(prs)}, zlaczone: {ok}/{len(todo)}")
    return ok, len(boxes), False


# ------------------------------------------------------------------ start
def _toggle():
    STATE["paused"] = not STATE["paused"]
    print("[BOT]", "PAUZA" if STATE["paused"] else "START")


def _stop():
    STATE["stop"] = True
    print("[BOT] STOP")


def main():
    global BACKEND, STORM_MERGE, SETTLE, ANIM, MERGE_GAP
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="tylko pokaz plan, bez ruchu")
    ap.add_argument("--merge", type=int, default=None, help="jeden przebieg, maks. N merge'y")
    ap.add_argument("--once", action="store_true", help="jeden przebieg i koniec")
    ap.add_argument("--until-done", action="store_true", help="konczy, gdy brak par")
    ap.add_argument("--safe", action="store_true", help="wolniej, ale ostrozniej")
    ap.add_argument("--fast", action="store_true", help="(domyslne) szybkie dragi")
    ap.add_argument("--loop", action="store_true", help="(domyslne) praca ciagla")
    ap.add_argument("--backend", choices=("win", "adb"), default="win")
    ap.add_argument("--threshold", type=float, default=pairs.SAME_THRESHOLD)
    ap.add_argument("--settle", type=float, default=None, help="czekanie po dragu (s)")
    ap.add_argument("--collect", action="store_true", help="tylko zbieraj scrap")
    ap.add_argument("--storm-merge", action="store_true",
                    help="lacz takze w sztormie (po kupieniu laczenia za gwiazdy)")
    args = ap.parse_args()

    BACKEND = args.backend
    STORM_MERGE = args.storm_merge
    if args.settle is not None:
        SETTLE = args.settle
    elif args.safe:
        SETTLE, ANIM, MERGE_GAP = 0.30, 0.90, 0.22
    pairs.SAME_THRESHOLD = args.threshold

    if args.collect:
        prev = win.foreground_hwnd() if BACKEND == "win" else None
        if BACKEND == "win":
            win.foreground()
        try:
            collect()
        finally:
            if BACKEND == "win":
                win.restore_foreground(prev)
        return

    if args.dry:
        merge_pass(None, dry=True, verbose=True)
        return

    if args.once or args.merge is not None:
        prev = win.foreground_hwnd() if BACKEND == "win" else None
        if BACKEND == "win":
            win.foreground()
        try:
            merge_pass(args.merge, dry=False, verbose=True)
        finally:
            if BACKEND == "win":
                win.restore_foreground(prev)
        return

    prev = win.foreground_hwnd() if BACKEND == "win" else None
    if BACKEND == "win":
        win.foreground()
        time.sleep(0.15)

    total = 0
    try:
        try:                            # skróty klawiszowe tylko na PC
            import keyboard
            keyboard.add_hotkey("f8", _toggle)
            keyboard.add_hotkey("f9", _stop)
        except Exception:
            print("[BOT] brak modulu 'keyboard' - sterowanie tylko z panelu/ADB")

        scanner = threading.Thread(target=scanner_loop, daemon=True)
        scanner.start()
        print("[BOT] F8 pauza, F9 stop - skaner + robotnik w tle")
        try:
            total = worker_loop(forever=not args.until_done)
        except Exception as exc:
            print(f"[BOT] blad: {exc}")
    finally:
        STATE["stop"] = True
        if BACKEND == "win":
            win.restore_foreground(prev)

    print(f"[BOT] koniec. Merge'y: {total}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("przerwano")
