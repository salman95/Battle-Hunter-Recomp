#!/usr/bin/env bash
# Bundled-release AppImage driver: stage the validated payload with the
# shared packager (STAGE_ONLY), then wrap it with the shared AppImage packager
# using this title's rendered inputs (scripts/appimage/AppRun + .desktop).
#
# Both steps are the framework's (psxrecomp/tools/package_game_release.sh,
# package_appimage.sh — see psxrecomp/docs/ci/BUNDLED_RELEASES.md); this
# wrapper only supplies this title's names and metadata. The AppImage ships
# the same payload as the zip: the compiled game, bundled OpenBIOS, mod
# catalog, overlay toolchain — never sources, generated C, or dumps.
#
# Usage: scripts/package_appimage.sh <build-dir> [recompiler-build-dir]
# Writes: dist/BattleHunter-Recompiled-v<VERSION>-x86_64.AppImage (+ .sha256)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="${1:-}"
RECOMPILER_BUILD="${2:-build-recompiler}"

if [[ -z "${BUILD_DIR}" ]]; then
  echo "usage: $0 <build-dir> [recompiler-build-dir]" >&2
  exit 2
fi
STAMP="${BUILD_DIR}/psx_game_version.txt"
if [[ ! -f "${STAMP}" ]]; then
  echo "error: ${STAMP} missing — build the game first (see the release workflow)" >&2
  exit 1
fi
VERSION="$(tr -d '[:space:]' <"${STAMP}")"

# 1. Stage (and gate) the payload exactly as the zip packager does.
STAGE_ONLY=1 "${ROOT}/scripts/package_release.sh" "${BUILD_DIR}" linux-x64 "${RECOMPILER_BUILD}" >/dev/null
STAGE="${ROOT}/dist/stage-game-linux-x64"
if [[ ! -f "${STAGE}/BattleHunter_Recompiled.execution.json" ]]; then
  echo "error: staging did not produce ${STAGE}" >&2
  exit 1
fi

# 2. Wrap it. The output path must be fresh for the packager; clear stale
#    artifacts from previous local runs first.
OUT="${ROOT}/dist/BattleHunter-Recompiled-v${VERSION}-x86_64.AppImage"
rm -f "${OUT}" "${OUT}.sha256"
bash "${ROOT}/psxrecomp/tools/package_appimage.sh" \
  --payload "${STAGE}" \
  --exe-name BattleHunter_Recompiled \
  --payload-name battle-hunter \
  --app-run "${ROOT}/scripts/appimage/AppRun" \
  --desktop-file "${ROOT}/scripts/appimage/battle-hunter-recompiled.desktop" \
  --icon "${ROOT}/assets/psxrecomp.png" \
  --output "${OUT}"

echo "AppImage: ${OUT}"