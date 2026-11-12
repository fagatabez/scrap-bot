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
jedna dluga gestia „trzymaj i machaj" po calym ekranie (tor zygzakiem), a nie
20 tapniec - gra zbiera tylko wtedy, gdy przycisk jest trzymany i sie rusza.
Ten sam przejazd leci takze wtedy, gdy nie ma czego laczyc.

Uzycie:
    python bot.py                 # domyslnie: skaner + robotnik, F8 pauza, F9 stop
    python bot.py --safe          # wolniej i ostrozniej (dluzsze czekanie)
    python bot.py --dry           # tylko pokaz plan, bez dotykania gry
    python bot.py --once          # jeden przebieg i koniec
    python bot.py --merge 3       # jeden przebieg, maks. 3 merge'y
    python bot.py --until-done    # konczy, gdy nie ma czego laczyc
    python bot.py --collect       # tylko zbieraj scrap (przejazd po ekranie)
    python bot.py --no-sweep      # nie zbieraj przy bezczynnosci
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

import ads
import backends
import pairs

try:                       # sterowanie oknem Windows - tylko na PC
    import win
except Exception:          # na telefonie (Termux) dziala tylko backend adb/root
    win = None

SHOT = os.path.join(tempfile.gettempdir(), "scrap_bot_shot.png")

BACKEND = "auto"            # auto | root | adb | win - rozpoznawane przy starcie
IO = None                   # obiekt wejscia/wyjscia wybrany przez backends.detect
STORM_MERGE = False         # True po kupieniu laczenia w sztormie za gwiazdy
SWIPE_MS = 75               # czas trwania dragu (ms) - krotszy = szybsze laczenie

SCAN_INTERVAL = 0.015       # odstep miedzy skanami planszy
SETTLE = 0.05               # zrzut musi byc nowszy niz drag + SETTLE
MERGE_GAP = 0.03            # przerwa miedzy kolejnymi dragami
ANIM = 0.26                 # tyle sekund nie ufamy polom dotknietym dragiem
RETRY = 1.2                 # ta sama para moze byc powtorzona po tym czasie
VERIFY_THRESHOLD = 0.35     # zmiana wygladu pola = merge przeszedl (tryb --once)
TAP_GAP = 0.05              # odstep miedzy tapami (juz nieuzywany w zbieraniu)
SWEEP_LINES = 5             # ile poziomych przejazdow przy zbieraniu trzymajac
SWEEP_SEG_MS = 110          # czas jednego odcinka przejazdu
SWEEP_EVERY = 1.5           # co tyle sekund bez par zbieraj scrap (0 = nigdy)
SWEEP = True                # zbieranie trzymajac (machanie po ekranie)
STORM_PAUSE = 0.10          # przerwa miedzy cyklami zbierania w sztormie
IDLE = 0.05                 # przerwa, gdy nie ma czego laczyc
GUARD = True                # pilnowanie reklam/popupow

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
    "fps": 0.0,
    "backend": "?",
    "ads_closed": 0,
}
LOCK = threading.Lock()
ACTIONS = []                # ostatnie dragi: (x1, y1, x2, y2, czas)
BOOST = None                # klikacz "szybsze beczki" (ads.Boost)


def grab():
    return IO.grab()


def tap(x, y):
    IO.tap(x, y)


def do_merge(a, b):
    IO.swipe(a[0], a[1], b[0], b[1], dur=SWIPE_MS)


def center(box):
    return box[0] + box[2] // 2, box[1] + box[3] // 2


def sweep_path(frame, lines=None, mx=0.05, top=0.10, bottom=0.10):
    """Tor machania po calym ekranie: poziome przejazdy tam i z powrotem.

    Marginesy omijaja gorna belke i dolny pasek, zeby nie klikac w menu.
    Zwraca liste punktow w wspolrzednych obrazu.
    """
    h, w = frame.shape[:2]
    lines = lines or SWEEP_LINES
    x0, x1 = int(w * mx), int(w * (1 - mx))
    y0, y1 = int(h * top), int(h * (1 - bottom))
    pts = []
    for k in range(max(2, lines)):
        y = int(y0 + (y1 - y0) * k / (max(2, lines) - 1))
        row = [(x0, y), (x1, y)]
        pts.extend(row if k % 2 == 0 else row[::-1])
    return pts


def collect(frame=None, verbose=True, lines=None):
    """Zbiera scrap trzymajac: jedna dluga gestia przez caly ekran.

    Gra zbiera tylko wtedy, gdy palec/kursor jest trzymany i sie rusza -
    dlatego nie ma tu tapow, jest przejazd tam i z powrotem (sweep_path).
    """
    frame = frame if frame is not None else grab()
    pts = sweep_path(frame, lines)
    IO.hold_path(pts, seg_ms=SWEEP_SEG_MS)
    if getattr(IO, "async_input", False):
        # powloka tylko przyjela polecenia - poczekaj, az gra je wykona,
        # inaczej kolejne przejazdy i merge'e ustawilyby sie w kolejce
        time.sleep((len(pts) - 1) * SWEEP_SEG_MS / 1000.0 + 0.05)
    if verbose:
        print(f"[BOT] zbieranie: przejazd po ekranie, {len(pts)} punktow, "
              f"{len(pts) - 1} odcinkow")
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
            if IO.name == "win" and now - last_cover > 0.7:
                cover = IO.win.covered_fraction()
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
            STATS["fps"] = round(1.0 / max(ts - (STATS.get("last_frame") or ts), 1e-6), 1)
            STATS["last_frame"] = ts

            # plansza nie wyglada jak gra -> reklama, popup albo ekran ulepszen
            if GUARD and not ads.looks_like_game(frame):
                with LOCK:
                    STATE["plan"] = None
                    STATE["serial"] += 1
                if ads.close_screen(IO):
                    STATS["ads_closed"] = STATS.get("ads_closed", 0) + 1
                    print("[BOT] zamknalem reklame/popup - wracam do laczenia")
                continue

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
    last_sweep = t0

    while not STATE["stop"]:
        if STATE["paused"]:
            time.sleep(0.1)
            continue

        now = time.time()
        if IO.name == "win" and now - last_cover_check > 0.25:
            last_cover_check = now
            if IO.win.covered_fraction() > 0.05:
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

        # brak planu przez dluzszy czas = nuda na planszy: pora na "szybsze beczki"
        if BOOST is not None and BOOST.due(now - last_progress):
            print("[BOT] brak par - odpalam szybsze beczki")
            try:
                BOOST.trigger(IO)
            except Exception as exc:
                print(f"[BOT] boost: {exc}")
            last_progress = time.time()
            continue

        if plan is None:
            # brak par = dobry moment na zebranie scrapa trzymajac
            if SWEEP and now - last_sweep >= SWEEP_EVERY:
                collect(verbose=False)
                last_sweep = time.time()
                last_action = last_sweep        # zeby nie ufac staremu zrzutowi
                continue
            time.sleep(0.01)
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


def setup_io(prefer="auto"):
    """Wybierze srodowisko (root/adb/win), przygotuje IO i zwroci jego nazwe."""
    global IO, BACKEND
    try:
        IO, errors = backends.detect(prefer, SHOT)
    except Exception as exc:
        raise SystemExit(
            f"[BOT] nie znalazlem gry ({prefer}): {exc}\n"
            "[BOT] sprawdz: czy BlueStacks dziala / czy telefon jest podlaczony "
            "po ADB / czy Termux ma roota")
    BACKEND = IO.name
    STATS["backend"] = IO.name

    if IO.name == "win":
        IO.win.foreground()
        print("[BOT] srodowisko: okno BlueStacks na pulpicie")
    else:
        IO.key(224)                                  # KEYCODE_WAKEUP
        IO._send("svc power stayon true")
        dev = getattr(IO, "device", "")
        print(f"[BOT] srodowisko: {IO.name} {dev}".rstrip())
        if getattr(IO, "stream_err", None):
            print(f"[BOT] szybki strumien zrzutow nie dziala ({IO.stream_err})"
                  " - uzywam zwyklych zrzutow")
    for err in errors:
        print(f"[BOT] pominiety tryb: {err}")
    return IO.name


def main():
    global STORM_MERGE, SETTLE, ANIM, MERGE_GAP, SWIPE_MS, GUARD, BOOST
    global SWEEP, SWEEP_LINES, SWEEP_EVERY, SWEEP_SEG_MS
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="tylko pokaz plan, bez ruchu")
    ap.add_argument("--merge", type=int, default=None, help="jeden przebieg, maks. N merge'y")
    ap.add_argument("--once", action="store_true", help="jeden przebieg i koniec")
    ap.add_argument("--until-done", action="store_true", help="konczy, gdy brak par")
    ap.add_argument("--safe", action="store_true", help="wolniej, ale ostrozniej")
    ap.add_argument("--fast", action="store_true", help="(domyslne) szybkie dragi")
    ap.add_argument("--loop", action="store_true", help="(domyslne) praca ciagla")
    ap.add_argument("--backend", choices=("auto", "win", "adb", "root"), default="auto",
                    help="auto = sam rozpozna telefon/ADB/okno BlueStacks")
    ap.add_argument("--root", action="store_true",
                    help="skrot: telefon z rootem, bez ADB")
    ap.add_argument("--no-guard", action="store_true",
                    help="nie zamykaj reklam i popupow")
    ap.add_argument("--boost", action="store_true",
                    help="klikaj 'szybsze beczki' (wymaga config.json z pick.py)")
    ap.add_argument("--threshold", type=float, default=pairs.SAME_THRESHOLD)
    ap.add_argument("--settle", type=float, default=None, help="czekanie po dragu (s)")
    ap.add_argument("--collect", action="store_true", help="tylko zbieraj scrap")
    ap.add_argument("--no-sweep", action="store_true",
                    help="nie zbieraj scrapa przy bezczynnosci")
    ap.add_argument("--sweep-lines", type=int, default=SWEEP_LINES,
                    help="ile przejazdow przy zbieraniu trzymajac (domyslnie 5)")
    ap.add_argument("--sweep-every", type=float, default=SWEEP_EVERY,
                    help="co ile sekund bez par zbierac (0 = nie zbieraj)")
    ap.add_argument("--hold-ms", type=int, default=SWEEP_SEG_MS,
                    help="czas jednego odcinka przejazdu przy zbieraniu (ms)")
    ap.add_argument("--storm-merge", action="store_true",
                    help="lacz takze w sztormie (po kupieniu laczenia za gwiazdy)")
    args = ap.parse_args()

    SWEEP = not args.no_sweep
    SWEEP_LINES = max(2, args.sweep_lines)
    SWEEP_EVERY = max(0.0, args.sweep_every)
    SWEEP_SEG_MS = max(40, args.hold_ms)
    STORM_MERGE = args.storm_merge
    GUARD = not args.no_guard
    if args.settle is not None:
        SETTLE = args.settle
    elif args.safe:
        SETTLE, ANIM, MERGE_GAP, SWIPE_MS = 0.30, 0.90, 0.22, 220
    pairs.SAME_THRESHOLD = args.threshold

    setup_io("root" if args.root else args.backend)

    cfg = ads.load()
    if args.boost or (cfg.get("boost") or {}).get("idle"):
        BOOST = ads.Boost()
        if BOOST.enabled:
            print(f"[BOT] szybsze beczki: klik po {BOOST.idle:.0f} s bez par")
        else:
            print("[BOT] szybsze beczki: brak przycisku w config.json "
                  "(ustaw przez python pick.py)")


    if args.collect:
        collect()
        return

    if args.dry:
        merge_pass(None, dry=True, verbose=True)
        return

    if args.once or args.merge is not None:
        merge_pass(args.merge, dry=False, verbose=True)
        return

    total = 0
    try:
        try:                            # skroty klawiszowe tylko na PC
            import keyboard
            keyboard.add_hotkey("f8", _toggle)
            keyboard.add_hotkey("f9", _stop)
        except Exception:
            pass

        scanner = threading.Thread(target=scanner_loop, daemon=True)
        scanner.start()
        print("[BOT] F8 pauza, F9 stop - skaner + robotnik w tle")
        try:
            total = worker_loop(forever=not args.until_done)
        except Exception as exc:
            print(f"[BOT] blad: {exc}")
    finally:
        STATE["stop"] = True

    print(f"[BOT] koniec. Merge'y: {total}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("przerwano")
