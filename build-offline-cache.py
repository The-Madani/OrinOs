#!/usr/bin/env python3
"""Build the offline package cache embedded in the live ISOs.

    ./build-offline-cache.py             # desktop profile (both Plasma variants)
    ./build-offline-cache.py terminal    # terminal profile (no desktop)

mkarchiso runs ``pacstrap -c``, which installs from the *host* cache and leaves
nothing inside the airootfs, so the medium cannot install offline by itself.
This script resolves the dependency closure the installer will ask for and
copies those ``.pkg.tar.zst`` files into the profile's ``/opt/orinos-cache``.
``refresh-orinos-cache.service`` puts them on tmpfs at boot, because the
airootfs is read-only.

The closure is computed from the ``.PKGINFO`` of packages already in the host
cache. ``pacman -Sp`` cannot be used: with ``-p`` pacman prints only the
explicit targets and never expands dependencies, and ``--recursive`` is not a
valid option. Reading the metadata that is already on disk is both exact and
network-free.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

args = [a for a in sys.argv[1:] if a != '--fetch-only']
FETCH_ONLY = '--fetch-only' in sys.argv[1:]
MODE = args[0] if args else 'desktop'

PROFILE = REPO_ROOT / 'profiles' / MODE
if not PROFILE.is_dir():
    sys.exit(f"Unknown mode '{MODE}'; expected a profile at {PROFILE}")

BASE_PACKAGES = [
    'base', 'linux', 'linux-firmware', 'grub', 'efibootmgr', 'networkmanager',
    'openssh', 'sudo', 'fish', 'sddm', 'fastfetch', 'cryptsetup', 'mkinitcpio',
]

DESKTOP_PACKAGES = [
    'orinos-branding', 'orinos-desktop',
    # Both variants: the user chooses on the disk page, and offline there is
    # no way to fetch what the other choice would have needed.
    'plasma-desktop', 'konsole', 'dolphin',
    # The full 'plasma' group, which is what DESKTOP_PACKAGES['full'] installs.
    'plasma',
]

WANTED = BASE_PACKAGES + (DESKTOP_PACKAGES if MODE == 'desktop' else [])

PKG_RE = re.compile(r'^(.+?)-(\d[^-]*(?:-[^-]+)?)-(?:x86_64|any)\.pkg\.tar\.zst$')
DEP_RE = re.compile(r'^(.+?)\s*(?:[<>=].*)?$')


def cache_dir() -> Path:
    out = subprocess.run(['pacman-conf', 'CacheDir'],
                         capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


def index_cache(cache: Path) -> dict:
    """Map package name -> list of its .pkg.tar.zst paths in the cache."""
    found: dict = {}
    for path in cache.glob('*.pkg.tar.zst'):
        match = PKG_RE.match(path.name)
        if match:
            found.setdefault(match.group(1), []).append(path)
    return found


def read_pkginfo(path: Path) -> dict:
    out = subprocess.run(['bsdtar', '-xOf', str(path), '.PKGINFO'],
                         capture_output=True, text=True, errors='replace')
    deps, provides, opt = [], [], []
    for line in out.stdout.splitlines():
        if line.startswith('depend = '):
            value = line[9:].strip()
            if value.startswith('!'):
                continue          # conflict, never a hard dependency
            name = DEP_RE.match(value).group(1).strip()
            if name:
                deps.append(name)
        elif line.startswith('provides = '):
            value = line[10:].strip().split('=')[0].strip()
            if value:
                provides.append(value)
        elif line.startswith('optdepend = '):
            value = line[12:].strip()
            if ':' in value:
                value = value.split(':')[0].strip()
            if '!' not in value:
                name = DEP_RE.match(value).group(1).strip()
                if name:
                    opt.append(name)
    return {'deps': deps, 'provides': provides, 'opt': opt}


def group_members(group: str) -> list:
    out = subprocess.run(['pacman', '-Spg', group],
                         capture_output=True, text=True)
    members = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if line and not line.startswith('::'):
            members.extend(line.split())
    return members


def resolve_closure(index: dict, meta: dict, providers: dict, roots: list):
    """Walk dependencies until every reachable package is accounted for."""
    seen, unresolved = set(), set()
    stack = list(roots)
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        if name in meta:
            stack.extend(meta[name]['deps'])
            # A working desktop needs these optional recommends too.
            if name in ('plasma', 'plasma-desktop', 'plasma-workspace',
                        'sddm', 'kwin', 'kwayland'):
                stack.extend(meta[name]['opt'])
        elif name in providers:
            stack.extend(providers[name])
        else:
            unresolved.add(name)
    return seen, unresolved


def fetch(packages: list) -> None:
    """Download packages into the host cache (needs a network)."""
    if not packages:
        return
    print(f"==> Downloading {len(packages)} packages into the host cache")
    # -w downloadonly, -y refresh the databases first so names resolve.
    proc = subprocess.run(
        ['pacman', '-Syw', '--noconfirm', '--needed', *packages],
        capture_output=True, text=True)
    if proc.returncode != 0:
        # pacman needs write access to the cache and the sync databases, and
        # downloads as DownloadUser when one is configured. Without root it
        # fails with a message that says nothing about which package list
        # caused it, so surface the cause here instead.
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        reason = detail[-1] if detail else f'exit {proc.returncode}'
        sys.exit(
            f'Could not download {len(packages)} packages: {reason}\n'
            'pacman needs root to write to the package cache (try: sudo '
            'python3 build-offline-cache.py).')


def main() -> int:
    cache = cache_dir()
    if not cache.is_dir():
        sys.exit(f"pacman cache not found at {cache}")
    print(f"==> Host cache: {cache}")

    index = index_cache(cache)
    meta, providers = {}, {}
    for name, paths in index.items():
        info = read_pkginfo(paths[0])
        meta[name] = info
        for provided in info['provides']:
            providers.setdefault(provided, []).append(name)

    # plasma is a group, not a package: expand it the way pacman would.
    roots = sorted(set(WANTED) | set(group_members('plasma')))

    seen, unresolved = resolve_closure(index, meta, providers, roots)

    # The OrinOs packages live in our own repo and are embedded separately by
    # build-iso.sh, so they are not expected in the Arch cache.
    def is_ours(name):
        return name.startswith('orinos-')

    # Anything reachable but absent from the cache has to be fetched, because
    # a stale cache would otherwise produce an ISO that cannot install.
    fetch(sorted(n for n in unresolved if not is_ours(n)))

    if FETCH_ONLY:
        # First half of a split run (build-iso.sh calls it without root, then
        # with root, then runs this again to collect the files). Resolving the
        # closure again here is what lets the second run see the newly fetched
        # packages, whose own dependencies may pull in further files.
        if not any(index_cache(cache).get(n) for n in unresolved):
            missing = sorted(n for n in unresolved if not is_ours(n))
            sys.exit('download failed; still missing: ' + ', '.join(missing))
        print('==> Fetch complete')
        return 0

    # Re-index: fetching added packages, which may bring in new dependencies
    # of their own that were not in the closure before.
    index = index_cache(cache)
    meta, providers = {}, {}
    for name, paths in index.items():
        info = read_pkginfo(paths[0])
        meta[name] = info
        for provided in info['provides']:
            providers.setdefault(provided, []).append(name)
    seen, unresolved = resolve_closure(index, meta, providers, roots)

    missing = sorted(n for n in unresolved if not is_ours(n))
    print(f"==> Closure: {len(seen)} packages "
          f"({len(missing)} still not in the host cache)")

    embed = PROFILE / 'airootfs' / 'opt' / 'orinos-cache'
    if embed.exists():
        shutil.rmtree(embed)
    embed.mkdir(parents=True)

    copied = 0
    for name in sorted(seen):
        paths = index.get(name)
        if not paths:
            continue
        newest = max(paths, key=lambda p: p.stat().st_mtime)
        shutil.copy2(newest, embed / newest.name)
        copied += 1

    size = sum(f.stat().st_size for f in embed.iterdir())
    print(f"==> Embedded {copied} packages "
          f"({size / 1024 ** 3:.2f} GiB) into {embed}")

    if missing:
        print(f"==> ERROR: {len(missing)} packages are still missing:",
              file=sys.stderr)
        for name in missing:
            print(f"      {name}", file=sys.stderr)
        print("    Offline install would fail for these; re-run once they "
              "are downloadable.", file=sys.stderr)
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())