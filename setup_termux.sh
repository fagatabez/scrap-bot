#!/data/data/com.termux/files/usr/bin/bash
# Instalacja scrap-bota w Termuxie (Android).
# Uzycie: bash setup_termux.sh
set -e

echo "== aktualizacja paczek =="
pkg update -y
pkg upgrade -y

echo "== python i biblioteki =="
# opencv i numpy instalujemy z pkg (pip nie ma wheeli dla Androida)
pkg install -y python python-numpy x11-repo opencv-python
pkg install -y android-tools      # dostarcza adb
pkg install -y git

echo "== sprawdzenie =="
python -c "import cv2, numpy; print('cv2', cv2.__version__, '| numpy', numpy.__version__)"

echo "== repo =="
mkdir -p ~/scrap-bot
cd ~/scrap-bot
if [ ! -d .git ]; then
  git clone https://github.com/fagatabez/scrap-bot.git .
fi

echo
echo "Gotowe. Uruchom:"
echo "  python bot.py --backend adb"
echo
echo "Przed tym ustaw urzadzenie ADB:"
echo "  export ADB_PATH=\$(which adb)"
echo "  export ADB_DEVICE=<IP>:5555     # np. 192.168.1.20:5555"
echo "  adb connect \$ADB_DEVICE"
echo
echo "Sprawdzenie:  adb devices"
