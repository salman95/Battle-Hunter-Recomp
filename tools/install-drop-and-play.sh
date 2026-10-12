#!/bin/sh
# install-drop-and-play.sh — register the Battle Hunter "Drop & Play" launcher
# with your desktop: an "Open With" entry + a desktop icon.
#
#   sh tools/install-drop-and-play.sh            # install
#   sh tools/install-drop-and-play.sh --remove   # uninstall
#
# Either way, you can always run the tool directly:
#   python3 tools/drop_and_play.py /path/to/your.ecm
set -e

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TPL="$REPO/tools/BattleHunterRecomp-DropAndPlay.desktop"
APP_ID="battle-hunter-drop-and-play"
ACTION="${1:-install}"

if [ "$ACTION" = "--remove" ]; then
    rm -f "$HOME/.local/share/applications/$APP_ID.desktop"
    rm -f "$HOME/Desktop/Battle Hunter — Drop & Play.desktop" 2>/dev/null || true
    command -v update-desktop-database >/dev/null && update-desktop-database \
        "$HOME/.local/share/applications" 2>/dev/null || true
    echo "removed (re-run without --remove to reinstall)"
    exit 0
fi

# sanity: the tool itself must be runnable
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" \
    || { echo "Python 3.11+ required"; exit 1; }

# fill the template
sed "s|@REPO@|$REPO|g" "$TPL" > "$HOME/.local/share/applications/$APP_ID.desktop"
mkdir -p "$HOME/.local/share/applications"

# mark trusted where supported (GNOME shows "Untrusted launcher" otherwise)
command -v gio >/dev/null && gio set \
    "$HOME/.local/share/applications/$APP_ID.desktop" \
    metadata::trusted true 2>/dev/null || true
command -v update-desktop-database >/dev/null && update-desktop-database \
    "$HOME/.local/share/applications" 2>/dev/null || true

# desktop icon (best effort; GNOME needs the file marked trusted too)
if [ -d "$HOME/Desktop" ]; then
    cp "$HOME/.local/share/applications/$APP_ID.desktop" \
       "$HOME/Desktop/Battle Hunter — Drop & Play.desktop" 2>/dev/null || true
    command -v gio >/dev/null && gio set \
        "$HOME/Desktop/Battle Hunter — Drop & Play.desktop" \
        metadata::trusted true 2>/dev/null || true
fi

cat <<EOF

Installed. Three ways to use it:

  1. DRAG & DROP (KDE, and GNOME with desktop icons):
     drag 'BATTLE HUNTER.iso.ecm' (or any .bin/.cue of the game)
     onto the "Battle Hunter — Drop & Play" launcher icon.

  2. OPEN WITH (GNOME):
     right-click your .ecm → "Open With Other Application" →
     "Battle Hunter — Drop & Play".

  3. TERMINAL:
     python3 $REPO/tools/drop_and_play.py /path/to/"BATTLE HUNTER.iso.ecm"
     (paths with spaces: quote them)

First run ≈ 10 minutes (unsqueeze → translate → compile), then every
run after that is seconds. A terminal window shows progress.

Remove anytime:  sh tools/install-drop-and-play.sh --remove
EOF