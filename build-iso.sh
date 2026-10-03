#!/usr/bin/env bash
# Build an OrinOs live ISO from profiles/common + the selected mode profile.
#
# Usage:
#   ./build-iso.sh terminal   terminal-only live ISO (current behavior)
#   ./build-iso.sh desktop    Plasma live session with "Install OrinOs"
#
# mkarchiso needs a single profile directory, so this script assembles
# work/<mode>-profile by layering the mode-specific files on top of
# profiles/common and then runs mkarchiso on it.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
MODE="${1:-}"
BUILD_DIR="${REPO_ROOT}/work"
OUT_DIR="${REPO_ROOT}/out"

usage() {
    echo "Usage: $0 <terminal|desktop>" >&2
    exit 1
}

[[ -n "${MODE}" ]] || usage
[[ -d "${REPO_ROOT}/profiles/${MODE}" ]] || {
    echo "Unknown mode '${MODE}'. Available: terminal, desktop" >&2
    exit 1
}

# The [orinos] repository must be built first: both modes install
# orinos-branding (desktop additionally orinos-installer) from it, and
# mkarchiso consumes it through profiles/common/pacman.conf.
if [[ ! -f "${REPO_ROOT}/packages/os/x86_64/orinos.db.tar.gz" ]]; then
    echo "==> [orinos] repo not found; building it first"
    "${REPO_ROOT}/packages/build-repo.sh"
fi

# Rebuild the repo unconditionally when package sources are newer than
# the built database, so the ISO never embeds a stale repository.
NEWEST_SRC=$(find "${REPO_ROOT}/packages" -name PKGBUILD \
    -newer "${REPO_ROOT}/packages/os/x86_64/orinos.db.tar.gz" 2>/dev/null \
    | head -1)
if [[ -n "${NEWEST_SRC}" ]]; then
    echo "==> PKGBUILD changed (${NEWEST_SRC}); rebuilding repo"
    (cd "${REPO_ROOT}/packages" && ./build-repo.sh)
fi

PROFILE="${BUILD_DIR}/${MODE}-profile"
# mkarchiso leaves root-owned read-only directories behind (airootfs image
# layout); a plain rm -rf would fail on a rebuild. Wipe the whole work dir
# with sudo (previous build's root-owned leftovers) when the user can't.
if [[ -d "${BUILD_DIR}" ]]; then
    chmod -R u+w "${BUILD_DIR}" 2>/dev/null || true
    rm -rf "${BUILD_DIR}" 2>/dev/null || {
        echo "==> Cleaning previous build leftovers (needs sudo)"
        sudo rm -rf "${BUILD_DIR}"
    }
fi
rm -rf "${PROFILE}"
mkdir -p "${PROFILE}"
cp -a "${REPO_ROOT}/profiles/common/." "${PROFILE}/"
cp -a "${REPO_ROOT}/profiles/${MODE}/." "${PROFILE}/"

# Embed the built [orinos] repository into the assembled airootfs. It is
# materialized at /orinos-repo at boot by refresh-orinos-repo.service, so
# the live environment (and the installed system) can consume it offline.
EMBED_DIR="${PROFILE}/airootfs/opt/orinos-repo"
mkdir -p "${EMBED_DIR}/x86_64"
cp "${REPO_ROOT}/packages/os/x86_64/"*.pkg.tar.zst "${EMBED_DIR}/x86_64/"
cp "${REPO_ROOT}/packages/os/x86_64/orinos.db.tar.gz" "${EMBED_DIR}/x86_64/"

# packages.x86_64 is layered per mode: the mode file may REPLACE the
# common file on a naive cp, so merge the two lists explicitly
# (common first, then mode extras; duplicates removed, order kept).
sort -u -o "${PROFILE}/packages.x86_64" \
    <(cat "${REPO_ROOT}/profiles/common/packages.x86_64") \
    <(cat "${REPO_ROOT}/profiles/${MODE}/packages.x86_64")

echo "==> Assembled ${MODE} profile at ${PROFILE}"
cd "${PROFILE}"

mkdir -p "${OUT_DIR}"
mkarchiso -v -w "${BUILD_DIR}/mkarchiso-${MODE}" \
    -o "${OUT_DIR}" "${PROFILE}"

echo "==> Done. ISO in ${OUT_DIR}"
