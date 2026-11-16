#!/bin/bash
# Removes Rep Book (the app) from this Mac. Your data folder is never deleted.
set -uo pipefail

ROOT="$HOME/Library/Application Support/RepBook-app"
APP="$HOME/Applications/Rep Book.app"
PY="$ROOT/app/.pixi/envs/default/bin/python"

clear 2>/dev/null || true
echo "Uninstall Rep Book"
echo "────────────────────"
if [ -n "${REPBOOK_UNATTENDED:-}" ]; then yes=y  # automated tests: no questions
else read -rp "Remove Rep Book from this Mac? Your data is kept. [y/N] " yes; fi
[[ "$yes" =~ ^[Yy] ]] || { echo "Nothing was changed."; exit 0; }

DATA=""
if [ -x "$PY" ]; then
  DATA="$(cd "$ROOT/app" && "$PY" -c 'from repbook.paths import data_dir; print(data_dir())' 2>/dev/null || true)"
fi
pkill -f "$ROOT/app/\\.pixi/envs/default/bin/python[0-9.]* -X utf8 -m repbook" 2>/dev/null || true  # only this installation's
sleep 1
rm -rf "$APP"
rm -rf "$ROOT"
echo "✓ Removed the Rep Book app."
echo
if [ -n "$DATA" ]; then
  echo "Your data (workout log, backups) is kept in:"
  echo "  $DATA"
else
  echo "Your data (workout log, backups) is kept, in ~/Library/Application Support/RepBook"
fi
echo "Installing Rep Book again picks it up. Delete that folder yourself only if you're sure."
if [ -z "${REPBOOK_UNATTENDED:-}" ]; then echo; read -n1 -rsp "Press any key to close this window."; echo; fi
