#!/data/data/com.termux/files/usr/bin/bash
# Instalacja scrap-bota w Termuxie na telefonie z rootem.
# Root pozwala robic zrzut ekranu i klikać bez ADB i bez debugowania bezprzewodowego.
# Uzycie: bash setup_termux_root.sh
set -e

echo "== paczki =="
pkg update -y
pkg upgrade -y
pkg install -y python python-numpy x11-repo opencv-python git
# opencv i numpy z pkg (pip nie ma wheeli dla Androida)

echo "== sprawdzenie roota =="
if ! su -c id 2>/dev/null | grep -q uid=0; then
  echo "Brak roota. Daj Termuxowi uprawnienia roota w Magisk (superuser) albo"
  echo "uzyj wariantu bez roota: bash setup_termux.sh"
  exit 1
fi
su -c id

echo "== repo =="
mkdir -p ~/scrap-bot
cd ~/scrap-bot
if [ ! -d .git ]; then
  git clone https://github.com/fagatabez/scrap-bot.git .
fi

echo "== test zrzutu ekranu =="
su -c "screencap -p /sdcard/_scrap_test.png" && echo "zrzut: /sdcard/_scrap_test.png"
python -c "import cv2, numpy; print('cv2', cv2.__version__, '| numpy', numpy.__version__)"

echo
echo "Gotowe. Uruchom:"
echo "  python bot.py --backend adb --root"
echo
echo "Gra musi być widoczna na ekranie (otwarta, telefon niezablokowany)."
