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
jedna dluga gestia „trzymaj i machaj" po calym ekranie - kolka na PC,
zygzak na telefonie - a nie 20 tapniec. Gra zbiera tylko wtedy, gdy przycisk
jest trzymany i sie rusza. Ten sam przejazd leci takze, gdy nie ma czego laczyc.

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
import math
import random
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
SWIPE_MS = 45               # czas trwania dragu (ms) - krotszy = szybsze laczenie

SCAN_INTERVAL = 0.0         # odstep miedzy skanami planszy
SETTLE = 0.03               # zrzut musi byc nowszy niz drag + SETTLE
MERGE_GAP = 0.0             # przerwa miedzy kolejnymi dragami
ANIM = 0.18                 # tyle sekund nie ufamy polom dotknietym dragiem
RETRY = 1.2                 # ta sama para moze byc powtorzona po tym czasie
VERIFY_THRESHOLD = 0.35     # zmiana wygladu pola = merge przeszedl (tryb --once)
TAP_GAP = 0.05              # odstep miedzy tapami (juz nieuzywany w zbieraniu)
SWEEP_LINES = 5             # ile poziomych przejazdow przy zbieraniu trzymajac
SWEEP_SEG_MS = 110          # czas jednego odcinka przejazdu
SWEEP_MS = 1400             # ile trwa CALY tor kolek na PC (ms)
SWEEP_STYLE = "auto"        # auto | circles (kolka) | zigzag (zygzak)
CIRCLE_R = 0.10             # promien kolka jako ulamek krotszego boku ekranu
CIRCLE_OVERLAP = 0.35       # ile sasiednie kolka na siebie nachodza
SWEEP_EVERY = 1.5           # co tyle sekund bez par zbieraj scrap (0 = nigdy)
SWEEP = True                # zbieranie trzymajac (machanie po ekranie)
STORM_PAUSE = 0.10          # przerwa miedzy cyklami zbierania w sztormie
IDLE = 0.01                 # przerwa, gdy nie ma czego laczyc
MAX_BATCH = 0               # max dragow z jednego skanu (0 = bez limitu)
GUARD = True                # pilnowanie reklam/popupow
BOOST_OFFER_EVERY = 600     # jak czesto klikac koronke eventow (s)
WATCH_OFFER = False         # klikanie koronki eventow (false = nie klikamy)
HUMAN = 0.0                 # % celowych bledow przy merge (jak w "ludzkim" bocie)
HUMAN_DELAY = True          # losowa pauza co 4-20 merge'y

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


def circle_path(frame, r_frac=None, overlap=None):
    """Tor zbierania koleczkami: siatka nachodzacych na siebie okregow.

    Kazde kolko to 12 punktow, wiec kursor/palec faktycznie kreca - tak gra
    zbiera magnesy rozrzucone po calym ekranie, nie tylko na liniach.
    """
    h, w = frame.shape[:2]
    r = max(18, int(min(w, h) * (CIRCLE_R if r_frac is None else r_frac)))
    ov = CIRCLE_OVERLAP if overlap is None else overlap
    step = max(20, int(2 * r * (1.0 - ov)))
    mx, top, bottom = 0.04, 0.10, 0.10
    x0, x1 = int(w * mx) + r, int(w * (1 - mx)) - r
    y0, y1 = int(h * top) + r, int(h * (1 - bottom)) - r
    if x1 < x0:
        x0 = x1 = w // 2
    if y1 < y0:
        y0 = y1 = h // 2
    xs = list(range(x0, x1 + 1, step)) or [x0]
    ys = list(range(y0, y1 + 1, step)) or [y0]
    pts = []
    n = 12
    for row, y in enumerate(ys):
        for cx in (xs if row % 2 == 0 else xs[::-1]):
            for k in range(n + 1):
                a = 2.0 * math.pi * k / n
                pts.append((int(cx + r * math.cos(a)), int(y + r * math.sin(a))))
    return pts


def oval_path(frame, r_frac=0.20, turns=3, points=20):
    """Tor owalnych kolek na srodku ekranu - szybkie zbieranie w sztormie.

    W sztormie nie da sie laczyc, wiec gra pozwala tylko zbierac. Owalki na
    srodku ekranu wygladaja jak "wymiatanie" myszka i zbieraja szybciej
    niz calky ekran.
    """
    h, w = frame.shape[:2]
    cx, cy = w // 2, int(h * 0.42)
    rx = max(20, int(w * r_frac))
    ry = max(12, int(rx * 0.55))
    pts = []
    for _ in range(turns):
        for k in range(points + 1):
            a = 2.0 * math.pi * k / points
            pts.append((int(cx + rx * math.cos(a)), int(cy + ry * math.sin(a))))
    return pts


def storm_sweep(frame=None, verbose=False):
    """Sztorm: bardzo szybkie owalne kolka na srodku ekranu.

    Bez uinput kazdy odcinek to osobny proces `input`, wiec robimy wtedy
    tylko jedno kolo (dlugie, ~1 s), a nie trzy szybkie.
    """
    frame = frame if frame is not None else grab()
    fast = getattr(IO, "can_hold", False)
    pts = oval_path(frame, turns=3 if fast else 1,
                    points=20 if fast else 8)
    total = max(200, len(pts) * 6) if fast else (len(pts) - 1) * SWEEP_SEG_MS
    IO.hold_path(pts, seg_ms=SWEEP_SEG_MS, total_ms=total)
    if getattr(IO, "async_input", False):
        time.sleep(total / 1000.0 + 0.05)
    if verbose:
        print(f"[BOT] sztorm: {len(pts)} punktow, {total} ms")
    return len(pts)


def collect(frame=None, verbose=True, lines=None):
    """Zbiera scrap trzymajac: jedna dluga gestia przez caly ekran.

    Gra zbiera tylko wtedy, gdy palec/kursor jest trzymany i sie rusza -
    dlatego nie ma tu tapow. Na PC tor to kolka (szybka, plynna gestia myszy),
    na telefonie zygzak - kazdy odcinek to osobny proces `input`, wiec setki
    odcinkow bylyby wolniejsze niz samo zbieranie.
    """
    frame = frame if frame is not None else grab()
    style = SWEEP_STYLE
    if style == "auto":
        # kółeczka da sie zrobic wtedy, gdy da sie naprawde trzymac palec:
        # okno Windows albo uinput na telefonie (root)
        style = "circles" if (getattr(IO, "name", "") == "win" or
                              getattr(IO, "can_hold", False)) else "zigzag"
    if style == "circles":
        pts = circle_path(frame)
        total = SWEEP_MS
    else:
        pts = sweep_path(frame, lines)
        total = (len(pts) - 1) * SWEEP_SEG_MS
    IO.hold_path(pts, seg_ms=SWEEP_SEG_MS, total_ms=total)
    if getattr(IO, "async_input", False):
        # powloka tylko przyjela polecenia - poczekaj, az gra je wykona,
        # inaczej kolejne przejazdy i merge'e ustawilyby sie w kolejce
        time.sleep(total / 1000.0 + 0.05)
    if verbose:
        print(f"[BOT] zbieranie: {style}, {len(pts)} punktow, "
              f"{len(pts) - 1} odcinkow")
    return len(pts)


# ------------------------------------------------------------------ skaner
def scanner_loop():
    """Ciagle skanuje plansze i publikuje najnowsza liste par."""
    last_cover = 0.0
    last_boost = 0.0
    last_boost_check = 0.0
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

            # Popup oferty "Szybsze Beczki" (zielone "Tak!" + czerwone "Nie").
            # Jesli jest na ekranie - bierzemy boost: 10x szybsze beczki.
            if BOOST is not None and getattr(BOOST, "popup", False) and \
                    ts - last_boost > BOOST.cooldown and ts - last_boost_check > 0.4:
                pos = ads.find_boost_button(frame)
                last_boost_check = ts
                if pos:
                    last_boost = ts
                    print("[BOT] popup 'Szybsze Beczki' - biore boost "
                          "(10 min szybciej)")
                    ads.take_boost(IO, pos)
                    continue
            STATS["fps"] = round(1.0 / max(ts - (STATS.get("last_frame") or ts), 1e-6), 1)
            STATS["last_frame"] = ts

            # Okno (reklama/popup/anty-macro) przyciemnia plansze - wyglada
            # wtedy jak sztorm. Trzeba to sprawdzic PRZED sztormem, inaczej
            # bot zamiast obsluzyc okno zacznie zbierac scrapa.
            popup = ads.has_popup(frame)

            storm = pairs.is_storm(frame) and not STORM_MERGE and not popup
            if storm:
                with LOCK:
                    STATE["storm"] = True
                    STATE["plan"] = None
                    STATE["serial"] += 1
            else:
                boxes, _, prs = pairs.find_pairs(frame)
                # okno na ekranie = reklama/popup/ekran ulepszen.
                # Sprawdzamy plansze tylko wtedy, gdy beczek jest malo - na
                # normalnej planszy to zbedne 25 ms na kazdy skan.
                if GUARD and popup:
                    with LOCK:
                        STATE["plan"] = None
                        STATE["serial"] += 1
                    # dialog anty-macro (siatka 3x3) - rozwiazujemy zamiast
                    # zamykac, bo czeka na odpowiedz
                    if ads.solve_anti_macro(IO, frame):
                        STATS["antimacro"] = STATS.get("antimacro", 0) + 1
                        continue
                    if ads.close_screen(IO):
                        STATS["ads_closed"] = STATS.get("ads_closed", 0) + 1
                        print("[BOT] zamknalem reklame/popup - wracam do laczenia")
                    continue
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


def _near(points, p, radius):
    """Czy w liscie srodkow jest punkt blizej niz radius od p."""
    r2 = radius * radius
    return any((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 <= r2 for q in points)


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
    last_offer = t0           # kiedy ostatnio kliknieto koronke eventow
    marks = []                  # czasy ostatnich merge'y (2 s) do tempa "teraz"
    batch = 0                   # ile dragow poszlo z biezacego skanu
    human_next = random.randint(4, 20)   # za ile merge'y losowa pauza

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
            storm_sweep(verbose=False)
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

        # brak par (nawet jak plan istnieje) = plansza bez par do polaczenia
        pairs_now = len(plan["prs"]) if plan is not None else 0
        if not pairs_now:
            # brak par = dobry moment na oferte boosta (klik koronki w grze)
            if (WATCH_OFFER and BOOST is not None
                    and getattr(BOOST, "popup", False)
                    and plan is not None
                    and now - last_offer >= BOOST_OFFER_EVERY):
                last_offer = now
                try:
                    r = ads.watch_offer(IO)
                except Exception as exc:
                    print(f"[BOT] oferta: {exc}")
                    r = None
                if r == "tak":
                    print("[BOT] obejrzalem reklame - beczki 10x szybciej "
                          "przez 10 min")
                elif r == "nie":
                    print("[BOT] brak oferty boosta - odrzucilem")
                last_action = time.time()
                cur = None
                cur_id = None
                continue
            # brak par = dobry moment na zebranie scrapa trzymajac
            if SWEEP and plan is not None and now - last_sweep >= SWEEP_EVERY:
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
            batch = 0

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

        # Najnowszy skan: jesli w nim nie ma juz beczki w tym miejscu, to pole
        # zdazylo sie polaczyc/zmienic i drag bylby tylko zmarnowany (liczyl
        # sie jako merge, ale nic nie laczyl). Sprawdzamy tylko wtedy, gdy
        # najnowszy plan jest swiezy i ma normalna plansze.
        with LOCK:
            fresh = STATE["plan"]
        fresh_ok = (fresh is not None and fresh["id"] != cur_id and
                    now - fresh["ts"] < 0.6 and len(fresh["boxes"]) >= 6 and
                    fresh["ts"] > last_action + SETTLE)
        fresh_pts = [center(b) for b in fresh["boxes"]] if fresh_ok else None

        chosen = None
        cands = []
        while idx < len(prs):
            i, j, _ = prs[idx]
            idx += 1
            if i >= len(boxes) or j >= len(boxes):
                continue
            a = center(boxes[i])
            b = center(boxes[j])
            if _blocked(a, b, now, radius):
                continue
            if fresh_pts is not None and not (_near(fresh_pts, a, radius) and
                                              _near(fresh_pts, b, radius)):
                continue
            key = _pair_key(a, b)
            if now - recent.get(key, 0.0) < RETRY:
                continue
            cands.append((a, b, key))
            if len(cands) >= 8:
                break
        if cands:
            chosen = cands[0]
            # tryb "ludzki": czasem wybieramy inna pare niz najlepsza -
            # merge sie nie wykona i bot wyglada jak czlowiek, nie maszyna
            if HUMAN > 0 and len(cands) > 1 and random.random() * 100 < HUMAN:
                chosen = random.choice(cands[1:])
                print(f"[BOT] celowy blad ({HUMAN:g}%): merge ({chosen[0][0]},"
                      f"{chosen[0][1]}) -> ({chosen[1][0]},{chosen[1][1]})")

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
        batch += 1
        if MAX_BATCH and batch >= MAX_BATCH:
            # telefon: nie kolejkuj kolejnych dragow na nieaktualnym zrzucie
            cur = None
            cur_id = None
        STATS["merges"] = total

        now = time.time()
        marks.append(now)
        marks[:] = [x for x in marks if now - x <= 2.0]
        if now - last_report >= 1.0 and total != last_total:
            span = max(now - marks[0], 0.5)
            rate = len(marks) / span            # tempo teraz, nie srednia od startu
            print(f"[BOT] merge'y: {total} | {rate:.1f}/s teraz | "
                  f"beczek: {last_n} | par: {len(boxes)}")
            last_report = now
            last_total = total
            STATS["rate"] = rate
            STATS["merges"] = total

        time.sleep(MERGE_GAP)                       # czas na animacje merge'a

        # losowa pauza co 4-20 merge'y - tak jak w "ludzkim" bocie
        if HUMAN_DELAY:
            human_next -= 1
            if human_next <= 0:
                human_next = random.randint(4, 20)
                time.sleep(random.uniform(0.05, 0.40))
                last_action = time.time()

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


def setup_io(prefer="auto", tune=True):
    """Wybierze srodowisko (root/adb/win), przygotuje IO i zwroci jego nazwe."""
    global IO, BACKEND, SWIPE_MS, SETTLE, ANIM, MERGE_GAP, SCAN_INTERVAL, MAX_BATCH
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
        if tune:
            # Telefon: kazdy drag to proces `input` (~150-250 ms), wiec nie ma
            # sensu kolekcjonowac ich na zapas - po 3 dragach z jednego zrzutu
            # pola juz sie zmienily i czesc prob byla nieaktualna (falszywe
            # laczenia). Dlatego krotsza kolejka i dluzsze czasy.
            SWIPE_MS, SETTLE, ANIM = 120, 0.12, 0.40
            MERGE_GAP, SCAN_INTERVAL, MAX_BATCH = 0.05, 0.03, 3
            print("[BOT] telefon: drag 120 ms, max 3 dragi na jeden zrzut")
        if getattr(IO, "can_hold", False):
            print("[BOT] uinput: prawdziwy gest (trzymany palec) - "
                  "koleczka i szybkie merge'y jak na PC")
            if tune:
                # gest przez uinput jest dokladnie odmierzony i czekamy na
                # jego koniec - nie ma kolejki starych komend, wiec mozemy
                # byc tak szybcy jak na komputerze
                SWIPE_MS, SETTLE, ANIM = 60, 0.06, 0.30
                MERGE_GAP, MAX_BATCH = 0.0, 0
                print("[BOT] telefon z uinput: drag 60 ms, bez limitu dragow "
                      "na zrzut")
        elif getattr(IO, "touch_err", None):
            print(f"[BOT] uinput niedostepne ({IO.touch_err}) - "
                  "zbieranie zygzakiem, merge przez 'input'")
    for err in errors:
        print(f"[BOT] pominiety tryb: {err}")
    return IO.name


def main():
    global STORM_MERGE, SETTLE, ANIM, MERGE_GAP, SWIPE_MS, GUARD, BOOST
    global SWEEP, SWEEP_LINES, SWEEP_EVERY, SWEEP_SEG_MS, SCAN_INTERVAL
    global SWEEP_STYLE, CIRCLE_R, SWEEP_MS, MAX_BATCH, BOOST_OFFER_EVERY
    global WATCH_OFFER, HUMAN, HUMAN_DELAY
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
    ap.add_argument("--swipe-ms", type=int, default=None,
                    help="czas dragu w ms (krotszy = szybciej; PC 45, telefon 120)")
    ap.add_argument("--gap", type=float, default=None,
                    help="przerwa miedzy dragami (s, domyslnie 0)")
    ap.add_argument("--anim", type=float, default=None,
                    help="jak dlugo nie ufac polu po dragu (s, domyslnie 0.18)")
    ap.add_argument("--scan", type=float, default=None,
                    help="przerwa miedzy skanami (s, domyslnie 0)")
    ap.add_argument("--batch", type=int, default=None,
                    help="max dragow z jednego zrzutu (0 = bez limitu)")
    ap.add_argument("--collect", action="store_true", help="tylko zbieraj scrap")
    ap.add_argument("--no-sweep", action="store_true",
                    help="nie zbieraj scrapa przy bezczynnosci")
    ap.add_argument("--sweep-style", choices=("auto", "circles", "zigzag"),
                    default=SWEEP_STYLE,
                    help="kolka czy zygzak przy zbieraniu (auto: PC=kolka, telefon=zygzak)")
    ap.add_argument("--circle-r", type=float, default=CIRCLE_R,
                    help="promien kolka jako ulamek krotszego boku (domyslnie 0.10)")
    ap.add_argument("--sweep-ms", type=int, default=SWEEP_MS,
                    help="ile ms trwa caly tor kolek (domyslnie 1400)")
    ap.add_argument("--sweep-lines", type=int, default=SWEEP_LINES,
                    help="ile przejazdow przy zbieraniu zygzakiem (domyslnie 5)")
    ap.add_argument("--sweep-every", type=float, default=SWEEP_EVERY,
                    help="co ile sekund bez par zbierac (0 = nie zbieraj)")
    ap.add_argument("--hold-ms", type=int, default=SWEEP_SEG_MS,
                    help="czas odcinka przy zbieraniu na telefonie (ms)")
    ap.add_argument("--storm-merge", action="store_true",
                    help="lacz takze w sztormie (po kupieniu laczenia za gwiazdy)")
    ap.add_argument("--no-boost-popup", action="store_true",
                    help="nie klikaj 'Tak!' w popupie 'Szybsze Beczki'")
    ap.add_argument("--boost-every", type=int, default=BOOST_OFFER_EVERY,
                    help="jak czesto klikac koronke eventow po ostatnim boostie (s)")
    ap.add_argument("--watch-offer", action="store_true",
                    help="klikaj koronke eventow, aby ogladac oferty (domyslnie nie)")
    ap.add_argument("--human", type=float, default=0.0,
                    help="%% celowych bledow przy merge (np. 1 = 1%%; 0 = wylaczone)")
    ap.add_argument("--no-human-delay", action="store_true",
                    help="bez losowych pauz co 4-20 merge'y")
    args = ap.parse_args()

    SWEEP = not args.no_sweep
    SWEEP_STYLE = args.sweep_style
    CIRCLE_R = max(0.03, args.circle_r)
    SWEEP_MS = max(300, args.sweep_ms)
    SWEEP_LINES = max(2, args.sweep_lines)
    SWEEP_EVERY = max(0.0, args.sweep_every)
    SWEEP_SEG_MS = max(40, args.hold_ms)
    if args.swipe_ms is not None:
        SWIPE_MS = max(20, args.swipe_ms)
    if args.gap is not None:
        MERGE_GAP = max(0.0, args.gap)
    if args.anim is not None:
        ANIM = max(0.08, args.anim)
    if args.scan is not None:
        SCAN_INTERVAL = max(0.0, args.scan)
    if args.batch is not None:
        MAX_BATCH = max(0, args.batch)
    BOOST_OFFER_EVERY = max(30, args.boost_every)
    WATCH_OFFER = args.watch_offer
    HUMAN = max(0.0, min(100.0, args.human))
    # losowe pauzy tylko razem z trybem "ludzkim"
    HUMAN_DELAY = HUMAN > 0 and not args.no_human_delay
    STORM_MERGE = args.storm_merge
    GUARD = not args.no_guard
    phone_tuned = any(v is not None for v in
                      (args.swipe_ms, args.gap, args.anim, args.scan,
                       args.settle, args.batch)) or args.safe
    if args.settle is not None:
        SETTLE = args.settle
    elif args.safe:
        SETTLE, ANIM, MERGE_GAP, SWIPE_MS = 0.30, 0.90, 0.22, 220
    pairs.SAME_THRESHOLD = args.threshold

    setup_io("root" if args.root else args.backend, tune=not phone_tuned)

    cfg = ads.load()
    bcfg = cfg.get("boost") or {}
    if args.no_boost_popup:
        bcfg["popup"] = False
    BOOST = ads.Boost(bcfg)
    if args.boost and not BOOST.button:
        print("[BOT] szybsze beczki: brak przycisku w config.json "
              "(ustaw przez python pick.py)")
    if BOOST.enabled:
        print(f"[BOT] szybsze beczki: klik po {BOOST.idle:.0f} s bez par")
    if BOOST.popup:
        print("[BOT] popup 'Szybsze Beczki': bot sam kliknie 'Tak!' "
              f"(max 1 raz na {BOOST.cooldown:.0f} s)")


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
