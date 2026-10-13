#!/usr/bin/env bash
# Thin wrapper around the shared psxrecomp bundled-release packager.
# Rendered from psxrecomp/tools/new_project_layout/templates/package_release.sh.in.
#
# Ships the COMPILED game built from this repo's committed generated/ C:
# executable, runtime data, bundled OpenBIOS, mod catalog, overlay toolchain.
# No sources, emitters, CLI, generated C, or BIOS dumps.
#
# Usage:
#   scripts/package_release.sh <build-dir> <artifact-tag> [recompiler-build-dir]
#
# Writes: dist/bh-<VERSION>-<artifact-tag>.zip
# (or, with STAGE_ONLY=1, just the validated dist/stage-game-<artifact> payload
# that scripts/package_appimage.sh wraps — no ZIP compression.)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="${1:-}"
ARTIFACT_TAG="${2:-}"
RECOMPILER_BUILD="${3:-build-recompiler}"

if [[ -z "${BUILD_DIR}" || -z "${ARTIFACT_TAG}" ]]; then
  echo "usage: $0 <build-dir> <artifact-tag> [recompiler-build-dir]" >&2
  exit 2
fi

PACKAGER="${ROOT}/psxrecomp/tools/package_game_release.sh"
if [[ ! -f "${PACKAGER}" ]]; then
  echo "error: missing ${PACKAGER} (psxrecomp submodule predates bundled releases -- bump it)" >&2
  exit 1
fi
chmod +x "${PACKAGER}" 2>/dev/null || true

EXTRA=()
# Overlay shard cache. It is compiled FROM THE DISC, so CI (no disc) cannot
# build one: the bundled overlay_toolchain/ compiles everything from the
# player's disc at runtime. A developer packaging locally with a cache can
# ship it instead:
#   PSX_OVERLAY_CACHE_ROOT=/path/to/cache scripts/package_release.sh ...
if [[ -n "${PSX_OVERLAY_CACHE_ROOT:-}" ]]; then
  EXTRA+=(--overlay-cache-root "${PSX_OVERLAY_CACHE_ROOT}")
else
  EXTRA+=(--ship-without-overlay-cache-because \
    "no disc at package time: overlay_toolchain/ autocompiles overlays from the player's own disc on their machine")
fi
if [[ "${STAGE_ONLY:-0}" == "1" ]]; then
  EXTRA+=(--stage-only)
fi
# Extra docs shipped at the zip root (DISC.md tells players which dump works).
for _doc in DISC.md; do
  if [[ -f "${ROOT}/${_doc}" ]]; then
    EXTRA+=(--doc "${_doc}")
  fi
done

cd "${ROOT}"
exec bash "${PACKAGER}" \
  --root "${ROOT}" \
  --build-dir "${BUILD_DIR}" \
  --artifact "${ARTIFACT_TAG}" \
  --zip-prefix bh \
  --exe-name BattleHunter_Recompiled \
  --display-name "Battle Hunter Recompiled" \
  --recompiler-build "${RECOMPILER_BUILD}" \
  --version-env RELEASE_VERSION \
  --disc-hint "your own Battle Hunter dump (USA, SLUS-01335): point the launcher at your .cue/.bin" \
  "${EXTRA[@]}"