# Scrap Clicker 2 - bot

Bot do Scrap Clicker 2 (BlueStacks / telefon): automatycznie laczy identyczne
beczki (merge) i zbiera scrap podczas sztormu.

Rozpoznanie beczek jest bez biblioteki skinow - kazda beczka jest porownywana
z kazda na tym samym zrzucie (histogram HSV + krawedzie), wiec dziala przy
kazdej rozdzielczosci i motywie.

## Szybki start

```powershell
pip install -r requirements.txt
python bot.py            # sam rozpozna srodowisko, F8 pauza, F9 stop
python bot.py --dry      # tylko plan, bez dotykania gry
python bot.py --boost    # + klikanie "szybsze beczki" (patrz nizej)
```

## Rozpoznawanie srodowiska

`--backend auto` (domyslne) sprawdza po kolei i bierze pierwsze dzialajace:

| Kolejnosc | Tryb | Kiedy pasuje |
|---|---|---|
| 1 | `root` | Termux na telefonie z rootem (`su`), gra na tym telefonie |
| 2 | `adb` | telefon/emulator widoczny po ADB (takze `localhost:PORT`) |
| 3 | `win` | okno BlueStacks na pulpicie (zrzut + mysz) |

Wymuszenie: `--backend root|adb|win`. Bot wypisuje, co wybral, np.
`[BOT] srodowisko: adb 127.0.0.1:5555`.

## Szybkosc

Zmierzone na tym komputerze:

| Operacja | Czas |
|---|---|
| wykrycie beczek i par (obraz 900x1600) | 60 ms |
| to samo dla zdjecia z telefonu 1260x2800 (skalowane do 900 px) | 69 ms |
| uruchomienie jednego procesu `adb` | 22 ms |

Dlatego bot nie odpala procesu na kazdy klik: trzyma jedna stala powloke
(`adb shell` albo `su -c sh`) do tapow i jedna stala rure `screencap` do
zrzutow. Drag trwa 45 ms, przerwa po dragu 0,03 s, miedzy dragami 0 s, a pola
dotkniete dragiem sa ignorowane 0,18 s (gra w tym czasie dokupuje beczke).
Skan nie ma juz sztywnej pauzy i nie liczy pola gry, gdy widzi >= 8 beczek.

Tempo ustawisz bez zmiany kodu:

```powershell
python bot.py --swipe-ms 45 --gap 0 --anim 0.18 --scan 0
python bot.py --swipe-ms 35 --anim 0.12      # agresywniej, mniej pewnie
python bot.py --swipe-ms 90 --anim 0.30      # spokojniej, pewniej
```

Realny sufit to ~1 drag na 50-60 ms, czyli **15-20 merge'y/s** - jeden merge
to jedna gestia myszy, a gra musi ja zobaczyc i odegrac animacje. 40/s jest
niemozliwe przy jednym wskazniku, niezaleznie od jezyka.

## Zbieranie scrapa (trzymanie zamiast tapowania)

Gra zbiera scrap tylko wtedy, gdy przycisk jest **trzymany i ruszany** -
pojedyncze tapy zbieraja pojedyncze sztuki. Dlatego zbieranie to jedna dluga
gestia:

* **PC (okno BlueStacks): kolka** - 60 nachodzacych na siebie okregow pokrywa
  caly ekran, kursor krecal sie po nich jednym trzymaniem (~1,4 s). To zbiera
  magnesy rozrzucone po planszy, nie tylko te na liniach.
* **telefon/ADB: zygzak** - kazdy odcinek to osobny proces `input`, wiec setki
  odcinkow byloby wolniejsze niz samo zbieranie.

Bot robi przejazd w sztormie i wtedy, gdy przez 1,5 s nie ma czego laczyc.
Ustawienia: `--sweep-style circles|zigzag`, `--circle-r`, `--sweep-ms`,
`--sweep-every`; wylaczenie: `--no-sweep`.

## Telefon: mniej falszywych laczen

Telefon wykonuje jeden drag ~150-250 ms (`input swipe` = nowy proces), wiec
zrzut, na ktorym bot planuje, zdaza sie zestarzec. Dlatego przy `root`/`adb`
bot sam przelacza sie na spokojniejszy tryb:

| Ustawienie | PC | telefon |
|---|---|---|
| drag | 45 ms | 120 ms |
| czekanie po dragu | 30 ms | 120 ms |
| blokada pola po dragu | 180 ms | 400 ms |
| dragi z jednego zrzutu | bez limitu | 3 |

Dodatkowo kazda para musi przejsc **druga bramke koloru**: srednia barwa,
nasycenie i jasnosc obu beczek musza byc zblizone. Wczesniej wystarczyl
podobny histogram, wiec beczki roznych typow o tym samym ukladzie cieni
(rozniaste skory, metaliki) potrafily byc ciagniete bez efektu.

Wymuszenie wlasnych czasow wylacza ten automat: dowolna z opcji `--swipe-ms`,
`--gap`, `--anim`, `--scan`, `--settle`, `--batch`, `--safe`.

## Detekcja beczek

Tlo planszy jest wykrywane z obrazu, wiec dziala przy kazdym motywie. Prog
roznicy koloru (`BG_DIFF`) jest celowo niski: jasny, szary korpus beczki
roznisz sie od zielonego tla tylko o ~35-40, a przy wyzszym progu szare
beczki rozpadaly sie na dwa kawalki i znikaly z listy. Puste pole od prawdziwej
szarej beczki odroznia czarny otwor (czapa), nie sam kolor.

## Reklamy, popupy i "szybsze beczki"

Bot laczy tylko wtedy, gdy widzi plansze gry. Gdy plansza zniknie (reklama
nagrody, popup, ekran ulepszen), probuje ja odzyskac: czerwony X -> klawisz
WSTECZ -> rogi ekranu. Wylaczenie: `--no-guard`.

Przycisk boosta ustawiasz raz, klikajac go na zrzucie:

```powershell
python pick.py
```

Zapisuje sie w `config.json` jako ulamek planszy (dziala przy kazdej
rozdzielczosci). Potem `python bot.py --boost`: jesli przez `idle` sekund nie
ma czego laczyc, bot klika boost, czeka na reklame, zamyka ja i wraca do gry.

```json
{ "boost": { "button": [0.83, 0.12], "idle": 8, "cooldown": 120 } }
```

## Sterowanie z telefonu (panel webowy)

Bot dziala na komputerze, a telefon jest pilotem:

```powershell
python server.py
```

Serwer wypisuje adres, np. `http://192.168.1.20:8765`. Wpisz go w przegladarce
telefonu (ten sam Wi-Fi). Panel pokazuje liczbe merge'ow, predkosc, liczbe beczek
i par, oraz przyciski START / PAUZA / STOP / PLAN.

## Uruchomienie na telefonie (Termux, Android)

### Wariant z rootem (najprostszy, bez ADB)

Telefon z rootem: bot robi zrzut ekranu i klika przez `su`, więc nie ma
ani ADB, ani debugowania bezprzewodowego.

```bash
pkg install git
git clone https://github.com/fagatabez/scrap-bot.git
cd scrap-bot
bash setup_termux_root.sh
python bot.py --backend root
```

Wymagania:
- root (Magisk itp.) z przyznanym dostępem dla Termuxa,
- `opencv-python` i `numpy` z `pkg` (pip ich nie zainstaluje),
- gra otwarta i widoczna na ekranie; telefon niezablokowany.

### Wariant bez roota (ADB)

```bash
pkg install git
git clone https://github.com/fagatabez/scrap-bot.git
cd scrap-bot
bash setup_termux.sh
bash connect_phone.sh          # parowanie telefonu z samym soba
export ADB_PATH=$(which adb)
export ADB_DEVICE=127.0.0.1:40505
python bot.py --backend adb
```

### Wariant: gra w emulatorze na PC, sterowanie z telefonu

Bot na telefonie, gra w BlueStacks na komputerze - telefon laczy sie z
emulatorem po ADB po Wi-Fi:

```bash
export ADB_DEVICE=192.168.1.20:5555
python bot.py --backend adb
```

Ręcznie:

```bash
pkg update && pkg install python x11-repo opencv-python python-numpy android-tools
export ADB_PATH=$(which adb)
export ADB_DEVICE=<IP_GRA>:5555     # IP komputera z emulatorem
adb connect $ADB_DEVICE
python bot.py --backend adb
```

Bot łączy się z emulatorem po ADB (dodaje `adb connect` przy starcie),
więc po jednorazowym `adb connect` nie musisz nic więcej ustawiać.

Uwagi:
- `opencv-python` i `numpy` instaluj z `pkg`, nie z `pip` (pip na Androidzie
  nie ma gotowych paczek i próbuje kompilować OpenCV, co się nie udaje).
- ADB na telefonie wymaga włączonego debugowania USB i zezwolenia na
  „debugowanie przez Wi-Fi" (Ustawienia > Deweloper > Debugowanie przez Wi-Fi).
- Do sterowania tapami/scrollami używany jest `adb shell input`, więc gra musi
  być na urządzeniu widocznym przez ADB.

## Zmienne środowiskowe

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `ADB_PATH` | `C:\ADB\adb.exe` | ścieżka do adb |
| `ADB_DEVICE` | `127.0.0.1:5555` | serial urządzenia ADB |
| `SCRAP_USE_ROOT` | - | `1` = zrzut i tapy przez `su` (telefon z rootem) |

## Pliki

- `bot.py` - skaner + robotnik, kolejka par, kontrola jakości merge'a
- `pairs.py` - wykrywanie beczek i parowanie (kolor + struktura)
- `win.py` - zrzut okna i mysz (bez ADB), tylko Windows
- `server.py` - panel webowy do sterowania z telefonu
- `ui.py` - rozpoznawanie ekranów gry (viewport, przyciski)
- `ocr.py` / `ocr.ps1` - OCR ekranu przez Windows.Media.Ocr
- `bs.py`, `map_window.py`, `detect.py` - starsze skrypty kalibracji/kalibracji okna

## Jak to działa

1. **Skaner** co 30 ms robi zrzut planszy i publikuje listę par.
2. **Robotnik** bierze pary i przeciąga beczkę na beczkę.
3. Kontrola jakości: zrzut musi być nowszy niż poprzedni drag + `SETTLE`,
   pola dotknięte dragiem są ignorowane przez `ANIM` sekund, ta sama para
   nie powtarza się częściej niż co `RETRY` sekund.
4. W sztormie (przyciemniona plansza) bot zamiast łączyć zbiera scrap:
   tap po 20 polach siatki 4x5.

## Ustawienia w `bot.py`

| Stała | Znaczenie |
|---|---|
| `SCAN_INTERVAL` | odstęp między skanami (s) |
| `SETTLE` | ile czekać po dragu przed zaufaniem nowego zrzutu |
| `ANIM` | ile czasu ignorować pola dotknięte dragiem |
| `RETRY` | jak długo nie powtarzać tej samej pary |
| `SAME_THRESHOLD` (w `pairs.py`) | próg uznania dwóch beczek za identyczne |
