#!/usr/bin/env bash
# Build the [orinos] pacman repository from the PKGBUILDs in this directory.
#
# Usage (on an Arch host with makepkg + repo-add, as root not required):
#   ./build-repo.sh
#
# Output: a flat pacman repository in packages/os/x86_64, embedded into
# the live ISOs by build-iso.sh (and still servable over HTTP for VM tests).
set -euo pipefail

cd "$(dirname "$0")"
REPO_DIR="os/x86_64"
# Start from a clean output directory: repo-add only appends, so stale
# packages (older pkgrel builds) would otherwise linger in the database.
rm -rf os
mkdir -p "$REPO_DIR"

for pkg in orinos-*/; do
    [ -d "$pkg" ] || continue
    name=$(basename "$pkg")
    echo "==> Building $name"
    # -d skips dependency resolution: the [orinos] packages declare
    # runtime deps (archinstall, pyside6) that only exist inside the
    # OrinOs live environment, not on the build host.
    (cd "$pkg" && makepkg -f --noconfirm -d)
    cp "$pkg"/*.pkg.tar.zst "$REPO_DIR/"
done

echo "==> Creating repository database"
repo-add "$REPO_DIR/orinos.db.tar.gz" "$REPO_DIR"/*.pkg.tar.zst
echo "==> Done. Repository at packages/os/x86_64"
