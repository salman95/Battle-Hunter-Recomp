#!/bin/sh
# make_appimage.sh — build BattleHunter-Recomp-Launcher-x86_64.AppImage.
#
# The AppImage carries everything except the game itself:
#   • the repo scaffold (config, seeds, psxrecomp + recomp-ui sources, tools)
#   • a portable Python + GTK3 runtime (via tools/appimage_collect.py)
#
# On first launch it deploys the scaffold to a writable work dir
# (~/.local/share/BattleHunterRecomp — override with $BH_WORKDIR), and from
# then on behaves exactly like a git checkout: insert your .ecm in the
# launcher, Recompile, Play. Build tools (cmake/ninja/clang) come from the
# system or are auto-downloaded by the framework on first recompile.
#
# Usage:   sh tools/make_appimage.sh [output.AppImage]
# Needs:   python3 (≥3.11) with gi/GTK3, mksquashfs or appimagetool
#          (appimagetool is downloaded on first use; network required once).
set -e

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$REPO/dist/BattleHunter-Recomp-Launcher-x86_64.AppImage}"
APPDIR="$REPO/build-appimage/AppDir"
APPID="battle-hunter-launcher"

# ---------------------------------------------------------------- helpers

need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1 ($2)"; exit 1; }; }
need python3 "the runtime bundle is collected with it"
need rsync "payload staging"
python3 -c 'import gi' 2>/dev/null || {
    echo "python3 needs PyGObject + GTK3 to build the bundle:";
    echo "  Debian/Ubuntu: sudo apt install python3-gi gir1.2-gtk-3.0";
    echo "  Arch:          sudo pacman -S gtk3 python-gobject";
    exit 1; }

# ---------------------------------------------------------------- AppDir

rm -rf "$APPDIR"
mkdir -p "$APPDIR/payload" "$APPDIR/usr"

# --- payload: the repo scaffold, minus junk and minus any game content
(
    cd "$REPO"
    # revision fingerprint (drives work-dir refreshes)
    {
        echo "main=$(git describe --tags --always --dirty 2>/dev/null || echo unknown)"
        echo "psxrecomp=$(git -C psxrecomp rev-parse HEAD 2>/dev/null || echo unknown)"
        echo "recomp-ui=$(git -C recomp-ui rev-parse HEAD 2>/dev/null || echo unknown)"
    } > "$APPDIR/payload/REVISION"

    for item in game.toml symbols.toml framework_pins.txt game_options.toml \
                psx_symbols.h codegen_setup.c codegen_setup.h CMakeLists.txt \
                VERSION REVISION seeds assets mods launcher_assets \
                third_party tools psxrecomp recomp-ui; do
        [ -e "$item" ] || continue
        if [ -d "$item" ]; then
            mkdir -p "$APPDIR/payload/$item"
            rsync -a --delete \
                  --exclude='.git' --exclude='.cache' --exclude='__pycache__' \
                  --exclude='/generated' --exclude='/recompiler/build' \
                  --exclude='/.pio' --exclude='/build' \
                  "$REPO/$item/" "$APPDIR/payload/$item/"
        else
            cp -a "$REPO/$item" "$APPDIR/payload/$item"
        fi
    done
)

# --- runtime: python + GTK3 (+ every lib they need)
python3 "$REPO/tools/appimage_collect.py" "$APPDIR"
. "$APPDIR/runtime.env"   # PYVER, written by the collector
rm -f "$APPDIR/runtime.env"

# --- AppRun: env + work-dir bootstrap + exec the GUI
cat > "$APPDIR/AppRun" <<EOF
#!/bin/sh
# Battle Hunter — Recomp Launcher (AppImage). Deploys the scaffold to a
# writable work dir on first run / version change, then runs the GUI.
set -e
APPDIR="\${APPDIR:-\$(dirname "\$(readlink -f "\$0")")}"

export LD_LIBRARY_PATH="\$APPDIR/usr/lib:\$LD_LIBRARY_PATH"
export GI_TYPELIB_PATH="\$APPDIR/usr/lib/girepository-1.0"
export PYTHONHOME="\$APPDIR/usr"
export PYTHONPATH="\$APPDIR/usr/python-packages"
export PYVER="$PYVER"

# gdk-pixbuf loader cache (regenerated per mount — paths differ each run)
export GDK_PIXBUF_MODULE_FILE="\${XDG_CACHE_HOME:-\$HOME/.cache}/bh-launcher/loaders.cache"
mkdir -p "\$(dirname "\$GDK_PIXBUF_MODULE_FILE")"
"\$APPDIR/usr/bin/gdk-pixbuf-query-loaders" "\$APPDIR"/usr/lib/gdk-pixbuf-2.0/*/loaders/*.so \\
    > "\$GDK_PIXBUF_MODULE_FILE" 2>/dev/null || true

# work dir: deploy scaffold on first run or when the AppImage revision changes
WORK="\${BH_WORKDIR:-\${XDG_DATA_HOME:-\$HOME/.local/share}/BattleHunterRecomp}"
REV="\$(cat "\$APPDIR/payload/REVISION" 2>/dev/null || echo unknown)"
if [ ! -f "\$WORK/REVISION" ] || [ "\$(cat "\$WORK/REVISION" 2>/dev/null)" != "\$REV" ]; then
    echo "deploying scaffold to \$WORK …" >&2
    for item in game.toml symbols.toml framework_pins.txt game_options.toml \\
                psx_symbols.h codegen_setup.c codegen_setup.h CMakeLists.txt \\
                VERSION REVISION seeds assets mods launcher_assets \\
                third_party tools psxrecomp recomp-ui; do
        [ -e "\$APPDIR/payload/\$item" ] || continue
        rm -rf "\$WORK/\$item"
        mkdir -p "\$WORK"
        cp -a "\$APPDIR/payload/\$item" "\$WORK/\$item"
    done
fi

cd "\$WORK"
exec "\$APPDIR/usr/bin/python3" "\$WORK/tools/launcher_gui.py" "\$@"
EOF
chmod +x "$APPDIR/AppRun"

# --- desktop entry + icons (needed by appimagetool)
VERSION="$(git -C "$REPO" describe --tags --always --dirty 2>/dev/null || echo dev)"
cat > "$APPDIR/$APPID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Battle Hunter — Launcher
GenericName=BattleHunterRecomp
Comment=Insert your Battle Hunter .ecm, recompile it (progress bar + console), then play
Exec=$APPID
Icon=$APPID
Terminal=false
Categories=Game;
MimeType=application/x-ecm;application/x-cd-image;application/x-iso9660-image;
Keywords=playstation;psx;ps1;battle hunter;recomp;launcher;
StartupWMClass=bh-recomp-launcher
X-AppImage-Version=$VERSION
EOF

ICON="$REPO/assets/psxrecomp.png"
cp "$ICON" "$APPDIR/$APPID.png"
ln -sf "$APPID.png" "$APPDIR/.DirIcon"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp "$ICON" "$APPDIR/usr/share/icons/hicolor/256x256/apps/$APPID.png"

# ---------------------------------------------------------------- pack

mkdir -p "$(dirname "$OUT")"
APPIMAGETOOL="$REPO/build-tools/appimagetool-x86_64.AppImage"
if [ ! -x "$APPIMAGETOOL" ]; then
    mkdir -p "$REPO/build-tools"
    echo "downloading appimagetool (one-time)…"
    curl -fL --retry 3 -o "$APPIMAGETOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$APPIMAGETOOL"
fi

echo "packing $OUT …"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGETOOL" --comp zstd \
    "$APPDIR" "$OUT"

sha256sum "$OUT" > "$OUT.sha256"
echo
echo "✓ $OUT"
echo "  $(du -h "$OUT" | cut -f1) — test it:  BH_WORKDIR=/tmp/bh-test \"$OUT\" --smoke"
