#!/data/data/com.termux/files/usr/bin/bash
# Podlaczenie telefonu do samego siebie przez ADB (debugowanie bezprzewodowe).
# Bez tego Termux nie moze zrobic zrzutu ekranu ani klikac w gre.
# Uzycie: bash connect_phone.sh
set -e

echo "1) Na telefonie: Ustawienia > O telefonie > Numer kompilacji - kliknij 7 razy"
echo "   Ustawienia > Deweloper > Debugowanie bezprzewodowe = WL"
echo
echo "2) Wejdz w: Deweloper > Debugowanie bezprzewodowe > Paruj urzadzenie z kodem"
echo "   Zapisz sobie ADRESZ PAROWANIA (np. 192.168.1.20:37000) i 6-cyfrowy kod."
echo "   (Port parowania jest inny niz port połączenia!)"
echo
read -r -p "Adres parowania (np. 192.168.1.20:37000): " PAIR_ADDR
read -r -p "Kod parowania (6 cyfr): " PAIR_CODE

echo "-> paruje..."
adb pair "$PAIR_ADDR" "$PAIR_CODE" || {
  echo "Blad parowania. Jeszcze raz to samo polecenie - znany bug ADB 35.x."
  adb pair "$PAIR_ADDR" "$PAIR_CODE"
}

echo
echo "3) Wroc do ekranu Debugowanie bezprzewodowe i przeczytaj"
echo "   'Adres IP i port' (to jest PORT POLACZENIA, inny niz parowania)."
read -r -p "Adres polaczenia (np. 192.168.1.20:40505): " CONN_ADDR

adb connect "$CONN_ADDR"
sleep 1
echo
echo "Sprawdzenie (musi być 'device'):"
adb devices
echo
echo "Test zrzutu ekranu:"
adb shell screencap -p /sdcard/_scrap_test.png && echo "OK: /sdcard/_scrap_test.png"
echo
echo "Gotowe. Ustaw zmienne i uruchom bota:"
echo "  export ADB_PATH=\$(which adb)"
echo "  export ADB_DEVICE=$CONN_ADDR"
echo "  python bot.py --backend adb"
echo
echo "Uwaga: port polaczenia zmienia sie po restarcie telefonu - wtedy"
echo "ponow 'adb connect \$ADB_DEVICE' (parowanie wystarczy raz)."
