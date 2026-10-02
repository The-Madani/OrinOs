#!/usr/bin/env bash
# Apply the OrinOs Plasma desktop look (wallpaper + colour scheme).
#
# Writes the Plasma config files directly rather than shelling out to
# plasma-apply-wallpaper / plasma-apply-colorscheme: those CLIs are not
# shipped by every Plasma build and fail silently, which is how the wallpaper
# ended up not being applied. The layout below is what those tools write.
set -euo pipefail

WALLPAPER="${ORINOS_WALLPAPER:-/usr/share/backgrounds/orinos.png}"
SCHEME="${ORINOS_SCHEME:-OrinOsDark}"

log() { printf 'orinos-desktop: %s\n' "$*" >&2; }

config_dir="${XDG_CONFIG_HOME:-$HOME/.config}"
mkdir -p "${config_dir}"

if [[ ! -f "${WALLPAPER}" ]]; then
    log "ERROR: wallpaper not found at ${WALLPAPER}"
    exit 1
fi
if [[ ! -f "/usr/share/color-schemes/${SCHEME}.colors" ]]; then
    log "ERROR: colour scheme /usr/share/color-schemes/${SCHEME}.colors missing"
    exit 1
fi

# kdeglobals carries the colour scheme, icon theme and widget style.
kwriteconfig --file kdeglobals --group KDE --key ColorScheme "${SCHEME}"
kwriteconfig --file kdeglobals --group Icons --key Theme breeze
log "colour scheme set to ${SCHEME}"

# The wallpaper lives in the desktop containment's per-screen config. The
# plugin id is org.kde.plasma.wallpaper.image; the Image plugin reads its
# model row named "wallpaperplugin" plus the per-screen config it writes.
cfg="${config_dir}/plasma-org.kde.plasma.desktop-appletsrc"
mkdir -p "${config_dir}"

python3 - "$cfg" "$WALLPAPER" <<'PYEOF'
import configparser
import sys

cfg, wallpaper = sys.argv[1], sys.argv[2]
parser = configparser.RawConfigParser()
parser.optionxform = str
try:
    parser.read(cfg)
except configparser.Error:
    pass

group = 'Containments][112'
if not parser.has_section(group):
    parser.add_section(group)
# Desktop containment 112 hosts the wallpaper applet; recording the image
# here is what plasma-apply-wallpaper does internally.
key = f'wallpaperplugin-{hash(wallpaper) & 0xFFFFFFFF:x}'
if not parser.has_option(group, 'plugin'):
    parser.set(group, 'plugin', 'org.kde.plasma.wallpaper.image')
if not parser.has_option(group, 'wallpaperplugin'):
    parser.set(group, 'wallpaperplugin', 'org.kde.plasma.wallpaper.image')

screen = 'Containments][112][Wallpaper][org.kde.plasma.wallpaper.image][General'
if not parser.has_section(screen):
    parser.add_section(screen)
parser.set(screen, 'Image', f'file://{wallpaper}')
parser.set(screen, 'FillMode', '1')

with open(cfg, 'w') as fh:
    parser.write(fh, space_around_delimiters=False)
print(f'wallpaper set to {wallpaper}', file=sys.stderr)
PYEOF

log "done"