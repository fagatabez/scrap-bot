#!/data/data/com.termux/files/usr/bin/bash
# Uruchamia bota z roota - potrzebne do uinput (trzymany palec, kółeczka
# i merge'y jednym gestem, tak jak na komputerze).
#
# Uzycie: bash run_root.sh [opcje bota, np. --sweep-style circles]
set -e
PREFIX=/data/data/com.termux/files/usr
export PATH="$PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$PREFIX/lib"
export TMPDIR="$PREFIX/tmp"
export HOME=/data/data/com.termux/files/home

cd "$HOME/scrap-bot" || { echo "Brak katalogu ~/scrap-bot - sklonuj repo"; exit 1; }

su -c "PATH=$PREFIX/bin:$PATH LD_LIBRARY_PATH=$PREFIX/lib TMPDIR=$TMPDIR HOME=$HOME python bot.py --root $*"
