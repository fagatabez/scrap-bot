# Scrap Clicker 2 - bot

Bot do Scrap Clicker 2 (BlueStacks / telefon): automatycznie laczy identyczne
beczki (merge) i zbiera scrap podczas sztormu.

Rozpoznanie beczek jest bez biblioteki skinow - kazda beczka jest porownywana
z kazda na tym samym zrzucie (histogram HSV + krawedzie), wiec dziala przy
kazdej rozdzielczosci i motywie.

## Szybki start (Windows, gra w BlueStacks)

```powershell
pip install -r requirements.txt
python bot.py            # tryb ciagly, F8 pauza, F9 stop
python bot.py --dry      # tylko plan, bez dotykania gry
python bot.py --backend adb   # sterowanie telefonem przez ADB
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

Najprościej skrypt instalacyjny:

```bash
pkg install git
git clone https://github.com/fagatabez/scrap-bot.git
cd scrap-bot
bash setup_termux.sh
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
