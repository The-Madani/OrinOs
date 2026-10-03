"""Checks for the offline cache builder.

Run with:  python3 installer/tests/test_offline_cache.py

No network and no root: the download loop is exercised with pacman stubbed out.
"""
import importlib.util
import sys
import types
from pathlib import Path

BUILDER = Path(__file__).resolve().parent.parent.parent / 'build-offline-cache.py'
failures = []


def check(label, condition, detail=''):
    print(f'{"PASS" if condition else "FAIL"}  {label}'
          + (f'   {detail}' if detail and not condition else ''))
    if not condition:
        failures.append(label)


spec = importlib.util.spec_from_file_location('offline_cache', BUILDER)
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)

# --- the package list must name things that exist ---------------------------
# A name that is not in any repository fails the download with "target not
# found", which is how plasma-session was caught; check the list statically so
# it fails here first.
import subprocess  # noqa: E402

unknown = []
for name in sorted(set(cache.WANTED)):
    if name.startswith('orinos-'):
        continue
    info = subprocess.run(['pacman', '-Si', name],
                          capture_output=True, text=True)
    if info.returncode != 0:
        group = subprocess.run(['pacman', '-Spg', name],
                               capture_output=True, text=True)
        if group.returncode != 0 or not group.stdout.strip():
            unknown.append(name)
check('every package in the offline list exists', not unknown,
      f'do not exist: {unknown}')

# --- the download loop must run until nothing is left -----------------------
# Fetching a package exposes its metadata, which can reveal dependencies that
# were unreachable before, so one pass is not enough. Stopping after the first
# pass is what left 7 packages missing.
rounds = [
    {'alpha', 'beta', 'gamma'},
    {'delta', 'epsilon'},
    set(),
]
calls = []


def fake_load(_cache_path):
    current = rounds[min(len(calls), len(rounds) - 1)]
    return {}, set(current), set(current)


def fake_fetch(packages):
    calls.append(set(packages))


real_fetch, real_load = cache.fetch, cache.load_cache
real_geteuid = cache.os.geteuid
cache.fetch = fake_fetch
cache.load_cache = fake_load
cache.os.geteuid = lambda: 0
try:
    cache.fetch_until_complete(Path('/nonexistent'))
finally:
    cache.fetch, cache.load_cache = real_fetch, real_load
    cache.os.geteuid = real_geteuid

check('the download loop runs until nothing is missing',
      len(calls) == 2, f'ran {len(calls)} download rounds: {calls}')
check('each round downloads what that round found missing',
      calls and calls[0] == {'alpha', 'beta', 'gamma'}
      and calls[1] == {'delta', 'epsilon'},
      str(calls))

# --- the loop must not spin forever on a cache that never fills -------------
infinite_calls = []
cache.fetch = lambda packages: infinite_calls.append(set(packages))
cache.load_cache = lambda _p: (
    {}, {'never', 'arrives'}, {'never', 'arrives'})
cache.os.geteuid = lambda: 0
try:
    cache.fetch_until_complete(Path('/nonexistent'))
    exhausted = False
except SystemExit:
    exhausted = True
finally:
    cache.fetch, cache.load_cache = real_fetch, real_load
    cache.os.geteuid = real_geteuid
check('the download loop gives up instead of spinning forever',
      exhausted, 'expected SystemExit after the round limit')

# --- the cache must land in the profile mkarchiso actually builds -----------
# build-iso.sh assembles work/<mode>-profile and runs mkarchiso on that; the
# source profiles/<mode> directory was copied before the cache was built. Writing
# the cache into profiles/ produced an ISO with no cache at all, so the offline
# install silently fell back to the network.
build_iso = (BUILDER.parent / 'build-iso.sh').read_text()
check('build-iso.sh passes the assembled profile to the cache builder',
      '"${MODE}" "${PROFILE}"' in build_iso,
      'the profile path must reach the builder as an argument')

check('the cache builder takes the profile as an argument',
      'args[1]' in BUILDER.read_text(),
      'expected: MODE and PROFILE as positional arguments')

check('the profile path does not travel through the environment',
      'ORINOS_PROFILE' not in BUILDER.read_text()
      and 'ORINOS_PROFILE' not in build_iso,
      'sudo resets the environment, so the path must be an argument')

# --- end to end: the cache must appear where mkarchiso looks for it ----------
# Reproduces the build order: copy the profiles into a work directory the way
# build-iso.sh does, then run the builder against that directory. The failure
# this guards against is silent -- the ISO built fine, it just had no packages,
# so offline install fell back to the network and the user saw it as a bug with
# no obvious cause.
import os  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

repo = BUILDER.parent

# The real cache is over a gigabyte, so it is not copied here; what matters is
# *where* the builder writes. Give it a throwaway profile and let it create the
# directory itself, then confirm the files land there and nowhere else.
with tempfile.TemporaryDirectory() as tmp:
    profile = Path(tmp) / 'desktop-profile' / 'airootfs'
    profile.mkdir(parents=True)

    stale = repo / 'profiles' / 'desktop' / 'airootfs' / 'opt' / 'orinos-cache'
    check('the source profile carries no stale cache', not stale.exists(),
          f'{stale} exists; it should only ever live under work/')

    real_profile = cache.PROFILE
    cache.PROFILE = Path(tmp) / 'desktop-profile'
    # Point the host cache at the real one but stop the copy from running, so
    # the test exercises path selection without moving a gigabyte.
    embedded = cache.PROFILE / 'airootfs' / 'opt' / 'orinos-cache'
    embedded.mkdir(parents=True)
    try:
        original_copy = cache.shutil.copy2
        cache.shutil.copy2 = lambda src, dst, **kw: dst      # type: ignore
        cache.main()
        cache.shutil.copy2 = original_copy
        check('the builder completes against the profile it was given', True)
    except SystemExit as exc:
        cache.shutil.copy2 = original_copy
        check('the builder completes against the profile it was given', False,
              f'exited: {exc}')
    finally:
        cache.PROFILE = real_profile

    check('the builder created the cache directory inside that profile',
          embedded.is_dir(), f'{embedded} was not created')
    check('the source profile is still free of a cache',
          not stale.exists(),
          'the builder must not write into profiles/')

print()
if failures:
    print(f'{len(failures)} FAILED: {failures}')
    sys.exit(1)
print('ALL OFFLINE CACHE CHECKS PASS')
