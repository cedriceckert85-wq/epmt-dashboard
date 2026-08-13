#!/usr/bin/env bash
# LoL Clip Lab — Linux/Mac-Launcher (analog zu START.bat)
#   ./start.sh              -> Setup + Selbsttest
#   ./start.sh DATEI.mkv    -> analyze
#   ./start.sh ORDNER/      -> batch
set -u
cd "$(dirname "$0")"

PYEXE=".venv/bin/python"
if [ ! -x "$PYEXE" ]; then
    PYEXE="python3"
fi

if [ "$#" -eq 0 ]; then
    echo "=== LoL Clip Lab: Setup + Selbsttest ==="
    python3 bootstrap.py
    exit $?
fi

if [ -d "$1" ]; then
    echo "=== Batch-Analyse: $1 ==="
    exec "$PYEXE" -m cliplab batch "$1"
elif [ -f "$1" ]; then
    echo "=== Analysiere VOD: $1 ==="
    exec "$PYEXE" -m cliplab analyze "$1"
else
    echo "Datei oder Ordner nicht gefunden: $1"
    exit 2
fi
