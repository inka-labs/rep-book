#!/bin/bash
# Installs, or updates, Rep Book for this Mac user. Double-click it (first time: right-click → Open).
#
#   ~/Library/Application Support/RepBook-app/   app/ (the app and its environment), bin/pixi, the uninstaller
#   ~/Applications/Rep Book.app                  opens Rep Book (starts it if needed)
#   ~/Library/Application Support/RepBook/       your data: never touched here
#
# No administrator password; nothing outside your home folder is touched. Built by packaging/build_release.py.
set -euo pipefail

PIXI_VERSION="__PIXI_VERSION__"
APP_VERSION="__APP_VERSION__"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HOME/Library/Application Support/RepBook-app"
APP="$HOME/Applications/Rep Book.app"
PY="$ROOT/app/.pixi/envs/default/bin/python"
# This installation's server, as the launcher starts it (launch.server_command), for pgrep/pkill (a regex)
SERVER="$ROOT/app/\\.pixi/envs/default/bin/python[0-9.]* -X utf8 -m repbook"

# REPBOOK_UNATTENDED=1: no prompts and no browser (automated tests, and a future self-update)
LAUNCH_ARGS=()
[ -n "${REPBOOK_UNATTENDED:-}" ] && LAUNCH_ARGS=(--no-browser)
finish() {
  [ -n "${REPBOOK_UNATTENDED:-}" ] && return 0
  echo
  read -n1 -rsp "Press any key to close this window." || true
  echo
}
fail() {
  echo
  echo "✗ $1"
  echo
  echo "  Your workout log were not changed."
  finish
  exit 1
}
trap 'fail "The installation stopped (see the messages above). Check your internet connection and try again."' ERR

clear 2>/dev/null || true
echo "Rep Book $APP_VERSION ($(date))"
echo "──────────────────────────────"
[ -f "$HERE/app/pixi.toml" ] || fail "Open this from the unzipped Rep Book folder (its app folder is missing)."

mkdir -p "$ROOT/bin"

# 1. pixi: installs the Python and packages Rep Book uses.
if [ "$("$ROOT/bin/pixi" --version 2>/dev/null || true)" != "pixi $PIXI_VERSION" ]; then
  case "$(uname -m)" in
    arm64) TARGET=aarch64-apple-darwin ;;
    *) TARGET=x86_64-apple-darwin ;;
  esac
  echo "→ Downloading pixi $PIXI_VERSION (installs the Python packages Rep Book uses)…"
  curl -fsSL "https://github.com/prefix-dev/pixi/releases/download/v$PIXI_VERSION/pixi-$TARGET.tar.gz" | tar -xz -C "$ROOT/bin" pixi
  chmod +x "$ROOT/bin/pixi"
fi

# 2. An update: stop this installation's Rep Book if it's running (only this one: matched by its path).
if pgrep -f "$SERVER" >/dev/null 2>&1; then
  echo "→ Stopping the Rep Book that's running…"
  pkill -f "$SERVER" 2>/dev/null || true
  for _ in $(seq 1 50); do pgrep -f "$SERVER" >/dev/null 2>&1 || break; sleep 0.2; done
  pkill -9 -f "$SERVER" 2>/dev/null || true
fi

# 3. The app's files (its environment, .pixi, is kept so an update is quick).
echo "→ Copying Rep Book…"
mkdir -p "$ROOT/app"
rsync -a --delete --exclude "/.pixi/" "$HERE/app/" "$ROOT/app/"

# 4. Its Python and packages.
echo "→ Installing Rep Book's Python and packages (a few minutes the first time)…"
"$ROOT/bin/pixi" install --manifest-path "$ROOT/app/pixi.toml" --frozen

# 5. The app you open it with.
echo "→ Adding Rep Book to your Applications…"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$ROOT/app/packaging/mac/icon.icns" "$APP/Contents/Resources/icon.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Rep Book</string>
  <key>CFBundleDisplayName</key><string>Rep Book</string>
  <key>CFBundleIdentifier</key><string>com.repbook.launcher</string>
  <key>CFBundleVersion</key><string>$APP_VERSION</string>
  <key>CFBundleShortVersionString</key><string>$APP_VERSION</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>Rep Book</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST
cat > "$APP/Contents/MacOS/Rep Book" <<LAUNCH
#!/bin/bash
# Opens Rep Book: starts it in the background if needed, then opens it in your browser. If its Python went
# missing (an interrupted update, a clean-up tool), it's reinstalled first, so opening Rep Book always works.
if [ ! -x "$PY" ]; then
  osascript -e 'display notification "Finishing the installation (a few minutes)…" with title "Rep Book"' || true
  "$ROOT/bin/pixi" install --manifest-path "$ROOT/app/pixi.toml" --frozen >> "\$HOME/Library/Logs/repbook-install.log" 2>&1
fi
cd "$ROOT/app" && exec "$PY" -m repbook.launch
LAUNCH
chmod +x "$APP/Contents/MacOS/Rep Book"
touch "$APP"

# 6. The uninstaller, next to the app.
cp "$ROOT/app/packaging/mac/uninstall.command" "$ROOT/Uninstall Rep Book.command"
chmod +x "$ROOT/Uninstall Rep Book.command"

trap - ERR
echo
echo "✓ Rep Book $APP_VERSION is installed. Opening it in your browser…"
echo "  Next time, open Rep Book from Applications (or Spotlight: ⌘ Space, type Rep)."
(cd "$ROOT/app" && "$PY" -m repbook.launch ${LAUNCH_ARGS[@]+"${LAUNCH_ARGS[@]}"}) || true  # same as opening the app (it shows its own error dialog)
sleep 1
finish
