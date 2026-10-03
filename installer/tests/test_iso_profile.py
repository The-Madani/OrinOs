"""Check that the ISO profile assembly produces a usable package list.

Run with:  python3 installer/tests/test_iso_profile.py

This reproduces what build-iso.sh does when it layers the profiles, without
running mkarchiso. A package list that lost entries fails the build with a
message about a boot loader, which is a long way from the cause.
"""
import subprocess  # noqa: E402
import sys
import tempfile  # noqa: E402
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
MODES = ['terminal', 'desktop']
failures = []


def check(label, condition, detail=''):
    print(f'{"PASS" if condition else "FAIL"}  {label}'
          + (f'   {detail}' if detail and not condition else ''))
    if not condition:
        failures.append(label)


build_iso = (REPO / 'build-iso.sh').read_text()

# The merge has to happen inside build-iso.sh; without it the mode file simply
# replaces the common one and every package only listed there is dropped.
check('build-iso.sh merges both package lists',
      'sort -u -o "${PROFILE}/packages.x86_64"' in build_iso,
      'no merge step found')
check('the merge keeps the common list',
      'profiles/common/packages.x86_64' in build_iso,
      'the common list is not part of the merge')

# The [orinos] repository ships on the medium and is served from
# /orinos-repo at runtime. Build-time pacstrap runs on the host, where that
# path does not exist, so the profile copy has to be rewritten to the host
# path. Losing that rewrite makes pacman look for the database at a path that
# only exists on the installed machine.
check('build-iso.sh rewrites the [orinos] URL for the build host',
      's|^Server = file:///orinos-repo/x86_64$' in build_iso,
      'the profile would point at /orinos-repo, which does not exist here')
check('the rewrite targets the profile pacman.conf',
      '"${PROFILE}/pacman.conf"' in build_iso,
      'the rewrite must apply to the assembled profile')

with tempfile.TemporaryDirectory() as tmp:
    for mode in MODES:
        profile = Path(tmp) / mode
        profile.mkdir()
        merged = sorted(set(
            (REPO / 'profiles' / 'common' / 'packages.x86_64')
            .read_text().split()
        ) | set(
            (REPO / 'profiles' / mode / 'packages.x86_64')
            .read_text().split()
        ))

        # Everything mkarchiso validates against the boot mode must be there.
        for required in ('syslinux', 'linux', 'base'):
            check(f'{mode}: {required} is in the merged list',
                  required in merged, f'missing from the assembled profile')

        # Every entry must be a real package, otherwise pacstrap aborts with
        # "target not found" part-way through the build. Our own packages are
        # exempt: they come from the [orinos] repository, which the profile
        # pacman.conf points at.
        unknown = []
        for name in merged:
            if name.startswith('orinos-'):
                continue
            info = subprocess.run(['pacman', '-Si', name],
                                  capture_output=True, text=True)
            if info.returncode != 0:
                group = subprocess.run(['pacman', '-Spg', name],
                                       capture_output=True, text=True)
                if group.returncode != 0 or not group.stdout.strip():
                    unknown.append(name)
        check(f'{mode}: every listed package exists', not unknown,
              f'do not exist: {unknown}')

        # The desktop profile carries Plasma; the terminal one must not, or
        # the terminal ISO is not a terminal ISO.
        has_plasma = 'plasma' in merged
        check(f'{mode}: plasma is {"present" if mode == "desktop" else "absent"}',
              has_plasma == (mode == 'desktop'),
              'the terminal profile must not pull in the desktop')

        # The repository database has to exist for the rewrite above to point
        # at something; a missing one fails the sync with "Could not open file".
        db = REPO / 'packages' / 'os' / 'x86_64' / 'orinos.db.tar.gz'
        check(f'{mode}: the [orinos] database is built', db.is_file(),
              f'{db} is missing; run packages/build-repo.sh')

        print(f'      ({mode}: {len(merged)} packages)')

# Every step the assembly depends on must be present. Three separate build
# failures came from a step going missing while another part of the script was
# edited, so each one is named explicitly rather than inferred.
for step, needle, why in [
        ('layers the common profile',
         'cp -a "${REPO_ROOT}/profiles/common/."', 'base system and boot mode'),
        ('layers the mode profile',
         'cp -a "${REPO_ROOT}/profiles/${MODE}/."', 'the desktop'),
        ('embeds the [orinos] repository',
         'orinos.db.tar.gz', 'orinos-branding and orinos-installer'),
        ('rewrites the repository URL',
         'Server = file://${REPO_ROOT}/packages/os/x86_64', 'build-time sync'),
        ('merges the package lists',
         'sort -u -o "${PROFILE}/packages.x86_64"', 'syslinux, linux, base'),
        ('runs mkarchiso on the assembled profile',
         'mkarchiso -v', 'the ISO itself'),
]:
    check(f'build-iso.sh {step}', needle in build_iso,
          f'missing: {why} would be dropped')

print()
if failures:
    print(f'{len(failures)} FAILED: {failures}')
    sys.exit(1)
print('ALL ISO PROFILE CHECKS PASS')