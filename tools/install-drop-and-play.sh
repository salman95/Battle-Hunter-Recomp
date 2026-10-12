#!/bin/sh
# install-drop-and-play.sh — register the Battle Hunter launchers with your
# desktop: a GUI launcher (file picker → recompile with progress bar → play)
# and the terminal "Drop & Play" entry.
#
#   sh tools/install-drop-and-play.sh            # install
#   sh tools/install-drop-and-play.sh --remove   # uninstall
#
# Either way, you can always run the tools directly:
#   python3 tools/launcher_gui.py            # GUI launcher
#   python3 tools/drop_and_play.py your.ecm  # terminal pipeline
set -e

REPO="$(cd "$(dirname "$0")/.." && pwd)"
GUI_TPL="$REPO/tools/BattleHunterRecomp-Launcher.desktop"
TUI_TPL="$REPO/tools/BattleHunterRecomp-DropAndPlay.desktop"
GUI_ID="battle-hunter-launcher"
TUI_ID="battle-hunter-drop-and-play"
ACTION="${1:-install}"

if [ "$ACTION" = "--remove" ]; then
    rm -f "$HOME/.local/share/applications/$GUI_ID.desktop"
    rm -f "$HOME/.local/share/applications/$TUI_ID.desktop"
    rm -f "$HOME/Desktop/Battle Hunter — Launcher.desktop" 2>/dev/null || true
    rm -f "$HOME/Desktop/Battle Hunter — Drop & Play.desktop" 2>/dev/null || true
    command -v update-desktop-database >/dev/null && update-desktop-database \
        "$HOME/.local/share/applications" 2>/dev/null || true
    echo "removed (re-run without --remove to reinstall)"
    exit 0
fi

# sanity: the tools must be runnable
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" \
    || { echo "Python 3.11+ required"; exit 1; }

install_one() {
    tpl="$1"; app_id="$2"; desktop_name="$3"
    mkdir -p "$HOME/.local/share/applications"
    sed "s|@REPO@|$REPO|g" "$tpl" \
        > "$HOME/.local/share/applications/$app_id.desktop"
    command -v gio >/dev/null && gio set \
        "$HOME/.local/share/applications/$app_id.desktop" \
        metadata::trusted true 2>/dev/null || true
    # desktop icon (best effort; GNOME needs the file marked trusted too)
    if [ -d "$HOME/Desktop" ]; then
        cp "$HOME/.local/share/applications/$app_id.desktop" \
           "$HOME/Desktop/$desktop_name.desktop" 2>/dev/null || true
        command -v gio >/dev/null && gio set \
            "$HOME/Desktop/$desktop_name.desktop" \
            metadata::trusted true 2>/dev/null || true
    fi
}

install_one "$GUI_TPL" "$GUI_ID" "Battle Hunter — Launcher"
install_one "$TUI_TPL" "$TUI_ID" "Battle Hunter — Drop & Play"
command -v update-desktop-database >/dev/null && update-desktop-database \
    "$HOME/.local/share/applications" 2>/dev/null || true

GUI_HINT=""
python3 - <<'PY' || GUI_HINT="
   (no GTK3 GUI available:  Debian/Ubuntu: sudo apt install python3-gi
    gir1.2-gtk-3.0  ·  Arch: sudo pacman -S gtk3 python-gobject — the
    terminal Drop & Play entry below works regardless)"
import sys
sys.path.insert(0, ".")
try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gtk  # noqa: F401
except Exception:
    raise SystemExit(1)
PY

cat <<EOF

Installed. The easy way to play:

  ★ GUI LAUNCHER — "Battle Hunter — Launcher" (app grid / desktop icon):
    open it, pick your BATTLE HUNTER.iso.ecm, press Recompile (live
    progress bar + console), then press Play. You can also drag your
    .ecm onto the launcher icon — it opens with the file pre-selected.$GUI_HINT

  · DROP & PLAY (terminal) — drag your .ecm onto the "Battle Hunter —
    Drop & Play" icon, or right-click → Open With, for the same pipeline
    with streaming text output.

First run ≈ 10 minutes (unsqueeze → translate → compile), then every
run after that is seconds.

Remove anytime:  sh tools/install-drop-and-play.sh --remove
EOF
