#!/usr/bin/env bash
# LoL Clip Lab (local test edition) — Linux / macOS launcher.
set -e
cd "$(dirname "$0")"

echo "=== LoL Clip Lab (local test edition) ==="
echo

PY="python3"
command -v "$PY" >/dev/null 2>&1 || PY="python"

"$PY" bootstrap.py

VENVPY=".venv/bin/python"

# If a VOD path was passed, analyze it now.
if [ -n "$1" ]; then
  echo
  echo "=== Analyzing $1 ==="
  "$VENVPY" -m clip_lab analyze "$1"
  echo
  echo "Done. Look in the *_clips folder next to your VOD for edit_sheet.md"
fi

echo
echo "Tip: run  ./start.sh /path/to/your_vod.mp4  to analyze a VOD, or:"
echo "    .venv/bin/python -m clip_lab analyze /path/to/your_vod.mp4"
