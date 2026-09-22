#!/usr/bin/env bash
# Build an OrinOs ISO with mkarchiso.
# Usage: ./build-iso.sh [profile-dir]
# Output: out/ ; working dir: work/ (both gitignored)

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="${1:-${SCRIPT_DIR}/../profiles/orinos-live}"
OUT_DIR="${SCRIPT_DIR}/../out"
WORK_DIR="${SCRIPT_DIR}/../work"

if [[ ! -f "${PROFILE}/profiledef.sh" ]]; then
    echo "error: not a valid archiso profile: ${PROFILE}" >&2
    exit 1
fi

for dep in mkarchiso; do
    if ! command -v "${dep}" >/dev/null 2>&1; then
        echo "error: required tool not found: ${dep}" >&2
        echo "install it with: pacman -S archiso" >&2
        exit 1
    fi
done

mkdir -p "${OUT_DIR}" "${WORK_DIR}"

export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git -C "${SCRIPT_DIR}/.." log -1 --pretty=%ct)}"

echo "==> profile:        ${PROFILE}"
echo "==> SOURCE_DATE_EPOCH: ${SOURCE_DATE_EPOCH} ($(date -u -d "@${SOURCE_DATE_EPOCH}" 2>/dev/null || date -u -r "${SOURCE_DATE_EPOCH}"))"
echo "==> output dir:    ${OUT_DIR}"

mkarchiso -v -w "${WORK_DIR}" -o "${OUT_DIR}" "${PROFILE}"
