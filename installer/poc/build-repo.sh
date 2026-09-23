#!/usr/bin/env bash
# Build the PoC [orinos] repository served during the Phase 6 installer test.
#
# Usage (on an Arch host with makepkg + repo-add, as root not required):
#   ./build-repo.sh
#
# Output: a flat pacman repository in installer/poc/orinos-repo/os/x86_64
# Serve it with:  python3 -m http.server 8000 --directory os
# Then pass http://<host-ip>:8000/os/x86_64 to installer/poc/install.py.
set -euo pipefail

cd "$(dirname "$0")"
REPO_DIR="os/x86_64"
mkdir -p "$REPO_DIR"

for pkg in orinos-repo/*/; do
    name=$(basename "$pkg")
    echo "==> Building $name"
    (cd "$pkg" && makepkg -f --noconfirm)
    cp "$pkg"/*.pkg.tar.zst "$REPO_DIR/"
done

echo "==> Creating repository database"
repo-add "$REPO_DIR/orinos.db.tar.gz" "$REPO_DIR"/*.pkg.tar.zst
echo "==> Done. Serve with: python3 -m http.server 8000 --directory os"
