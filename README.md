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
| wykrycie beczek i par (obraz 900x1600) | 10 ms |
| to samo dla zdjecia z telefonu 1260x2800 (skalowane do 900 px) | 12 ms |
| zrzut okna gry | 13 ms |
| jeden drag mysza (35 ms gestii) | 47 ms |
| pelny cykl merge'a (zrzut + analiza + gest) | ~55-65 ms |
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

Realny sufit to ~1 drag na 55 ms, czyli **15-20 merge'y/s** - jeden merge
to jedna gestia myszy, a gra musi ja zobaczyc i odegrac animacje. 40/s jest
niemozliwe przy jednym wskazniku, niezaleznie od jezyka.

Detekcja liczy sie na obrazie o polowe mniejszym (maska przez tablice LUT,
`np.linalg.norm` z 7,9 ms spadl do 1,7 ms), a wspolrzedne wracaja do pelnej
skali. Przy okno 900x1600 to 10 ms zamiast 60 ms.

## Zbieranie scrapa (trzymanie zamiast tapowania)

Gra zbiera scrap tylko wtedy, gdy przycisk jest **trzymany i ruszany** -
pojedyncze tapy zbieraja pojedyncze sztuki. Dlatego zbieranie to jedna dluga
gestia:

* **PC (okno BlueStacks): kolka** - 60 nachodzacych na siebie okregow pokrywa
  caly ekran, kursor krecal sie po nich jednym trzymaniem (~1,4 s). To zbiera
  magnesy rozrzucone po planszy, nie tylko te na liniach.
* **telefon/ADB: zygzak** - kazdy odcinek to osobny proces `input`, wiec setki
  odcinkow byloby wolniejsze niz samo zbieranie.
* **telefon z rootem (uinput): kółeczka jak na PC** - bot tworzy wirtualny
  ekran dotykowy (`/dev/uinput`) i wysyla do niego zdarzenia `ABS_MT_*`.
  Palec jest naprawde trzymany, wiec dzialaja te same koleczka co na
  komputerze, a merge to jeden gest (~60 ms) zamiast kolejki procesow
  `input swipe`. Wymaga uruchomienia bota z roota: `bash run_root.sh`.

Bot robi przejazd **tylko** na żądanie (`--sweep`) - domyślnie **w ogóle nie
macha kursorem po planszy**, tylko łączy. W sztormie działa osobny tryb:
zbieranie tego, co spada (patrz niżej).

Ustawienia: `--sweep-style circles|zigzag`, `--circle-r`, `--sweep-ms`,
`--sweep-every`.

## Telefon: mniej falszywych laczen

Telefon wykonuje jeden drag ~150-250 ms (`input swipe` = nowy proces), wiec
zrzut, na ktorym bot planuje, zdaza sie zestarzec. Dlatego przy `root`/`adb`
bot sam przelacza sie na spokojniejszy tryb:

| Ustawienie | PC | telefon (`input`) | telefon z uinput |
|---|---|---|---|
| drag | 45 ms | 120 ms | 60 ms |
| czekanie po dragu | 30 ms | 120 ms | 60 ms |
| blokada pola po dragu | 180 ms | 400 ms | 300 ms |
| dragi z jednego zrzutu | bez limitu | 3 | bez limitu |
| zrzut ekranu | 13 ms | ~90 ms (PNG) | ~40 ms (surowy) |

Przy uinput gest jest dokladnie odmierzony i bot czeka na jego koniec, wiec
nie ma kolejki starych polecen - dlatego mozna byc tak szybcy jak na
komputerze. Bez roota (albo gdy uinput jest niedostepne) zostaje wariant
`input`, ktory jest wolniejszy, ale bezpieczniejszy.

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
nagrody, popup, ekran ulepszen), probuje ja odzyskac. Reklame zamyka
najpierw **przyciskiem "wstecz"** BlueStacks (dziala jak X, a X w reklamie
bywa niewidoczny), dopiero potem czerwonym X-em na ekranie. Wylaczenie:
`--no-guard`.

## Tryb "ludzki" (--human N [MAX])

Bot moze sie zachowywac jak czlowiek, a nie jak maszyna:

```powershell
python bot.py                    # MAKSYMALNA szybkosc: bez limitu, 15-20 merge'ow/s
python bot.py --human 1          # 1% pomyłek + limit 3500 laczen/10 min (domyslny)
python bot.py --human 5          # 5% pomyłek, limit 3500/10 min
python bot.py --human 10 4000    # 10% pomyłek + własny limit (4000/10 min)
python bot.py --human 10 3.5k   # to samo ("3.5k" też działa)
```

**Bez `--human` bot nie ma żadnego limitu** - łączy tak szybko, jak potrafi
(na tym komputerze 15-20 merge'ów/s). **`--human` włącza limit 3,5 tys.
łączeń na 10 minut** (5,8/s) — tyle robią normalni gracze; drugi parametr
pozwala to zmienić.

Przy `--human N` bot:

* z szansą N% **przeciąga beczkę na złą beczkę** (inną niż ta, z którą się
  łączy) - merge się nie wykona, dokładnie jak przy pomyłce gracza. W logu
  widać to jako „celowy blad”. Takich pomyłek **nie liczy** jako merge'y,
  żeby licznik zgadzał się z grą,
* co 4-20 merge'y robi **losową pauzę** 50-400 ms,
* łączy **po wzorcu** (jak człowiek), a nie "najbliższa para".

Drugi parametr to **limit łączeń na 10 minut** (3500 = 5,8 merge'a/s). Bot
mierzy swoje tempo i jak jest za szybki - **zwalnia**, z losowymi wahaniami
(raz wolniej, raz szybciej, ±30%), więc wygląda jak człowiek, a nie jak
limitowarka. Dla porównania: normalni gracze robią ok. 3,5 tys. łączeń na
booscie w 10 min, najlepsi 4-4,5 tys.

Bez `--human` bot jest pełnomaszynowy: 0 błędów, zero pauz, bez limitu.

## Wzorzec laczenia (jak u ludzi)

Bot nie ciagnie "najblizszej" pary - trzyma **wzorzec**: najpierw sasiednie
beczki w jednym rzedzie, od lewej do prawej, potem kolejny rzed. Tak wlasnie
laczna ludzie przy "speed merge" (z wiki gry: szybkie laczenie wymaga
wlaczenia boosta "Szybsze Beczki" i laczenia po wzorcu). Efekt jest taki sam
za kazdym razem, wiec plansza nie zaplata sie i bot nie robi dziwnych ruchow.

Wylaczenie: `--no-pattern` (wtedy laczy najblizsza para).

## Obrocone okno i obce gry

* **Ekran obrocony** (telefon/emulator w poziomie): bot rozpoznaje to po
  ikonie magnesu w HUD, prostuje obraz i mapuje wspolrzedne z powrotem -
  laczy normalnie, a okna gry (oferta, anty-macro) tez.
* **Obca gra w emulatorze**: bot sprawdza, czy to na pewno Scrap Clicker 2
  (jasnozielona plansza albo zlota korona z okna oferty). Jesli nie - **nic
  nie klika**, tylko czeka i pisze w logu. Nie macha myszka w innej grze.

## Reklama a sztorm

Oba ekrany sa ciemne, wiec bot rozroznia je po **zielonym pasku gry** u
dolu (reklama go nie ma). Wczesniej reklama byla mylona ze sztormem - bot
zamiast zamknac reklame zaczynal zbierac scrapa po niej.

## Okna gry a sztorm

Pod oknem (reklama, popup, anty-macro) plansza jest **przyciemniona** i wyglada
jak sztorm. Bot najpierw sprawdza, czy na ekranie jest jasnoszare okno
(`ads.has_popup`) - dopiero potem uznaje ciemna plansze za sztorm. Bez tego
bot zamiast obsluzyc okno zaczalby zbierac scrapa po nim.

## Auto ogladanie boosta (koronka w prawym gornym rogu)

W grze, w prawym gornym rogu nad plansza, jest **zlota koronka** (przycisk
eventow). Klikniecie jej otwiera okno z oferta "Szybsze Beczki" albo
"Auto Laczenie". Bot sam to robi:

1. kliknie koronke (szukamy zoltej korony w prawym gornym rogu, nad plansza),
2. jesli to okno **"Szybsze Beczki"** - kliknie zielone **"Tak!"**, przewija
   reklame, zamyka ja i wraca do laczenia (beczki 10x szybciej przez 10 min),
3. jesli to **inne** okno (np. "Auto Laczenie") - kliknie czerwone **"Nie"**
   i czeka,
4. dalej laczy beczki.

**Uwaga: gdy boost ju�� działa, koronka znika** z prawego gornego rogu, a w
jego miejscu jest niebieski licznik czasu (np. 02:56). Wtedy bot nie ma czego
klikać i po prostu łączy - w logu wypisze "boost 'Szybsze Beczki' aktywny".
Koronka wraca później z kolejną ofertą.

**Koronka:** bot sprawdza ją **co 0,3 s** (koszt ~1 ms - patrzy tylko na
prawy górny wycinek obrazu) i **klika od razu**, gdy się pojawi - nie musisz
czekać 2 minut. Minimalny odstęp między kliknięciami to 120 s
(`--boost-every`), a po odrzuceniu oferty 30 s, żeby nie wpaść w pętlę
popupów. W trybie domyślnym bot jest skupiony na szybkim łączeniu - przerwy
są tylko wtedy, gdy sama reklama się pojawi. Gdy wyskoczy
oferta **nie**będąca boostec, bot ją odrzuca ("Nie") i ** próbuje ponownie
za 12 s** - koronka wraca szybko, a wybór oferty jest losowy, więc "Szybsze
Beczki" w końcu się trafia. Po
kliknieciu **"Nie"** koronka znika na jakis czas i po chwili wraca z innym
boostem - wtedy bot znów klika. **"Szybsze Beczki"** (10x szybciej przez
10 min) bot bierze ("Tak!" + reklama), a inne oferty odrzuca ("Nie").

Wylaczenie: `--no-watch-offer` (sama reklama przy "Szybsze Beczki", ktora
pojawi sie sama, jest i tak obslugiwana).

## Ulepszenia (menu "Ulepszenia")

Bot co jakiś czas (domyślnie co 180 s, `--upgrade-every`) sam wchodzi w menu
ulepszeń i **kupuje wszystko, co się da**:

1. klika pomarańczową **strzałkę** na dole planszy (to otwiera menu),
2. w menu klika **zielone przyciski z ceną** - szybko, trzy razy w to samo
   miejsce (przycisk zostaje, więc da się kupić kolejny poziom),
3. przyciski z napisem **"MAX"** (już wykupione) **pomija** - rozpoznaje je
   po wzorcu tekstu, nie po OCR,
4. przyciski **szare** (nie starczy scrapu, cena na czerwono) też **pomija** -
   sprawdza kolor tła każdego przycisku,
5. zamyka menu czerwonym X-em i wraca do łączenia.

Wykrywanie strzałki i przycisków jest odporne na rozdzielczość (skaluje się
z rozmiarem menu). Wyłączenie: `--upgrade-every 0`.

## Dialog anty-macro

Gra co jakis czas pokazuje okno "Event" z siatka 3x3: trzeba zaznaczyc
wszystkie pola z szukana beczka. Bot:

* rozpoznaje panel (jasnoszare okno z niebieskim "!" u gory),
* znajduje szukana beczke (prawy gorny rog napisu) i porownuje jej barwe
  z beczkami w siatce,
* klika tylko jak dopasowanie jest **jednoznaczne** (najlepszy zawodnik
  musi byc wyraznie lepszy od nastepnego) - inaczej nie klika nic i czeka,
* po zaznaczeniu kliknie niebieski przycisk nagrody.

Wariant z **liczbami** (sprzed wersji 6.0) wymaga OCR - bot go nie rozwiazuje
i czeka, az rozwiazesz go recznie.

Uwaga (z wiki gry): automaty i makra sa w tej grze uznawane za cheating, a
gra ma ekran anty-cheat i moderatorow. Bot jest wiec celowo mniej "mądry"
niz człowiek: ogranicza liczbe bledow, nie robi wszystkiego naraz.

## Sztorm: zbieranie tego, co spada

W sztormie laczenie jest zablokowana, wiec bot zbiera itemsy. **Nie robi
kolek** - chmury sa statyczne, wiec porownuje dwie klatki i szuka plam, ktore
sie zmienily: to spadajace przedmioty. Gest idzie prosto do nich (najwyzej
lezyace najpierw), a tlo chmury jest pomijane, bo sie nie rusza. Gdy nic nie
spada, bot wraca do szybkich kolek.

Test wykrywania (offline, na sztucznej klatce ze chmurami i spadajacym
przedmiotem): trafia w przedmiot, na statycznych chmurach nie reaguje.

## Rozpoznawanie okna "Szybsze Beczki"

Bot rozpoznaje okno oferty po trzech rzeczach: zielony
przycisk "Tak!" (z bialym napisem, obok czerwonego "Nie"), **zlota korone**
(szablon `assets/boost_crown.png`) **i tytul okna** (szablon
`assets/boost_title.png`).

Korona sama nie wystarcza - okno **"Auto Łączenie"** ma dokladnie ta sama
korone, ten sam zielony "Tak!" i ten sam uklad. Rozroznia je napis w tytule,
ktory bot porownuje jako profil ksztaltu liter (24 liczby, bez OCR). Dlatego
bot bierze tylko "Szybsze Beczki" (10x szybciej przez 10 min), a "Auto
Laczenie" zostawia w spokoju.

Wszystko skaluje sie razem z przyciskiem, wiec dziala na kazdej rozdzielczosci
telefonu (sprawdzone w skali 0,4x-2,6x na 6 zrzutach). Bot klika "Tak!",
przewija reklame, zamyka ja i wraca do laczenia. Sprawdzanie okna kosztuje
~4 ms i leci raz na 0,4 s, wiec nie spowalnia mergowania. Wylaczenie:
`--no-boost-popup` (albo `"popup": false` w `config.json`).

Przycisk boosta na planszy (stare podejscie) ustawiasz raz, klikajac go
na zrzucie:

```powershell
python pick.py
```

Zapisuje sie w `config.json` jako ulamek planszy (dziala przy kazdej
rozdzielczosci). Potem `python bot.py --boost`: jesli przez `idle` sekund nie
ma czego laczyc, bot klika boost, czeka na reklame, zamyka ja i wraca do gry.

```json
{ "boost": { "button": [0.83, 0.12], "idle": 8, "cooldown": 120, "popup": true } }
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
bash run_root.sh          # z roota: uinput, koleczka, gesty jak na PC
```

`run_root.sh` uruchamia bota z roota, bo `/dev/uinput` wymaga roota. Dopiero
wtedy bot moze naprawde trzymac palec (koleczka przy zbieraniu) i robic
merge'y jednym gestem. Bez roota (`python bot.py --root`) bot dziala, ale
zbiera zygzakiem przez procesy `input`.

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
