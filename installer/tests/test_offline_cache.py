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

print()
if failures:
    print(f'{len(failures)} FAILED: {failures}')
    sys.exit(1)
print('ALL OFFLINE CACHE CHECKS PASS')
