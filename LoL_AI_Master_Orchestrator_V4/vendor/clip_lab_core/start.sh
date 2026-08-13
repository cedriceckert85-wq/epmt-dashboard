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

# A folder -> batch-analyze everything in it; a file -> analyze it.
if [ -n "$1" ]; then
  echo
  if [ -d "$1" ]; then
    echo "=== Batch-analyzing folder $1 ==="
    "$VENVPY" -m clip_lab batch "$1"
  else
    echo "=== Analyzing $1 ==="
    "$VENVPY" -m clip_lab analyze "$1"
  fi
  echo
  echo "Done. Look in the *_clips folder(s) next to your video(s) for edit_sheet.md"
fi

echo
echo "Tips:"
echo "  ./start.sh /path/to/vod.mp4     analyze one VOD"
echo "  ./start.sh /path/to/vod_folder  analyze a whole folder"
echo "  put example clips into references/ and run: .venv/bin/python -m clip_lab learn"
