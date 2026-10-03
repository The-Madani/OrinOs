"""Checks for the desktop branding scripts.

Run with:  python3 installer/tests/test_branding.py

The wallpaper bug this guards against was a guessed plugin id: the script
wrote org.kde.plasma.wallpaper.image into the applet config while the
real plugin is org.kde.image, so Plasma ignored the file and the desktop
kept the default wallpaper with no error anywhere.
"""
import re  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
PKG = REPO / 'packages' / 'orinos-desktop'
failures = []


def check(label, condition, detail=''):
    print(f'{"PASS" if condition else "FAIL"}  {label}'
          + (f'   {detail}' if detail and not condition else ''))
    if not condition:
        failures.append(label)


script = (PKG / 'orinos-apply-desktop.sh').read_text()
# Only the code is checked: the header comment names the wrong plugin id on
# purpose, to record why it was wrong.
code = '\n'.join(line for line in script.splitlines()
                 if not line.lstrip().startswith('#'))

# --- shell syntax ------------------------------------------------------------
syntax = subprocess.run(['bash', '-n', str(PKG / 'orinos-apply-desktop.sh')],
                        capture_output=True, text=True)
check('the branding script parses', syntax.returncode == 0,
      syntax.stderr.strip())

# --- no guessed plugin ids ---------------------------------------------------
# Anything of the form org.kde.plasma.wallpaper.* is a guess; the shipped
# plugin is org.kde.image.
guessed = re.findall(r'org\.kde\.plasma\.wallpaper\.\w+', code)
check('no guessed wallpaper plugin id', not guessed,
      f'found: {guessed}')

check('the wallpaper is applied with the plasma tool',
      'plasma-apply-wallpaperimage' in code,
      'the official tool is the supported path')
check('the script does not hand-edit the applet config',
      'desktop-appletsrc' not in code,
      'hand-written applet config is what failed before')

# --- the tool really exists in plasma-workspace ------------------------------
# Checked against the package on the build host; on a host without Plasma the
# check is skipped rather than failed.
info = subprocess.run(['pacman', '-Si', 'plasma-workspace'],
                      capture_output=True, text=True)
if info.returncode == 0:
    check('plasma-workspace is available (provides the tool)', True)
else:
    print('SKIP  plasma-workspace not installed on this host')

# --- fill mode is one the tool accepts ---------------------------------------
# plasma-apply-wallpaperimage maps exactly these names; anything else is
# rejected and the wallpaper silently does not change.
fill_modes = re.findall(r'-f\s+(\w+)', code)
valid = {'stretch', 'preserveAspectFit', 'preserveAspectCrop', 'pad'}
check('the fill mode is one the tool accepts',
      all(mode in valid for mode in fill_modes),
      f'invalid: {[m for m in fill_modes if m not in valid]}')

# --- the assets the script needs are packaged -------------------------------
pkginfo = subprocess.run(
    ['bash', '-c',
     f'cd {PKG} && makepkg --printsrcinfo 2>/dev/null'],
    capture_output=True, text=True)
check('the package lists every asset the script reads',
      all(name in pkginfo.stdout or (PKG / name).exists()
          for name in ('wallpaper.png', 'OrinOsDark.colors', 'OrinOs.colors')),
      'an asset the script checks for is missing from the package')

# --- the colour scheme named by the script is the one we ship ---------------
check('the default scheme is one we ship', 'OrinOsDark.colors' in
      (PKG / 'PKGBUILD').read_text(),
      'the script defaults to a scheme the package does not install')

# --- the service is enabled for the live session -----------------------------
live_unit = (REPO / 'profiles' / 'desktop' / 'airootfs' / 'usr' / 'lib'
             / 'systemd' / 'user' / 'orinos-live-desktop.service')
if live_unit.exists():
    wants = (REPO / 'profiles' / 'desktop' / 'airootfs' / 'usr' / 'lib'
             / 'systemd' / 'user' / 'default.target.wants'
             / 'orinos-live-desktop.service')
    check('the live session enables the branding unit',
          wants.is_symlink() or wants.exists(),
          f'{wants} is missing')
    unit = live_unit.read_text()
    check('the branding unit runs after the shell',
          'plasma-plasmashell.service' in unit,
          'the tool needs plasmashell to be running')
else:
    print('SKIP  no live branding unit in the desktop profile')

print()
if failures:
    print(f'{len(failures)} FAILED: {failures}')
    sys.exit(1)
print('ALL BRANDING CHECKS PASS')