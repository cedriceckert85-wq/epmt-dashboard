#!/usr/bin/env bash
# LoL AI Master Orchestrator V4 — One-Shot Start (Linux/macOS)
set -euo pipefail
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
  exec python3 bootstrap.py "$@"
elif command -v python >/dev/null 2>&1; then
  exec python bootstrap.py "$@"
else
  echo "[FEHLER] Python 3.10+ wurde nicht gefunden. Bitte installieren." >&2
  exit 3
fi
