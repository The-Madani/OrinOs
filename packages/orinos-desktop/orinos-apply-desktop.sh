#!/usr/bin/env bash
# Apply the OrinOs Plasma desktop look (wallpaper + colour scheme).
#
# The wallpaper goes through plasma-apply-wallpaperimage, the tool plasma
# ships for exactly this purpose. An earlier version wrote
# plasma-org.kde.plasma.desktop-appletsrc by hand with a guessed plugin id
# (org.kde.plasma.wallpaper.image); the real one is org.kde.image, so Plasma
# silently ignored the file and the desktop kept the default wallpaper.
set -euo pipefail

WALLPAPER="${ORINOS_WALLPAPER:-/usr/share/backgrounds/orinos.png}"
SCHEME="${ORINOS_SCHEME:-OrinOsDark}"

log() { printf 'orinos-desktop: %s\n' "$*" >&2; }

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

if ! command -v plasma-apply-wallpaperimage >/dev/null 2>&1; then
    log "ERROR: plasma-apply-wallpaperimage not found (plasma-workspace?)"
    exit 1
fi

# The tool talks to plasmashell over the session bus, so it can only work once
# the shell is up. systemd orders it after plasma-plasmashell.service, but a
# shell that is still starting answers nothing; retry rather than writing a
# config the shell would overwrite on exit.
#
# -f preserveAspectCrop fills the screen without distorting the image.
applied=no
for attempt in 1 2 3 4 5; do
    if plasma-apply-wallpaperimage "${WALLPAPER}" -f preserveAspectCrop; then
        applied=yes
        break
    fi
    log "attempt ${attempt} failed (plasmashell not ready?), retrying"
    sleep 3
done

if [[ "${applied}" == yes ]]; then
    log "wallpaper applied via plasma-apply-wallpaperimage"
else
    log "WARNING: the wallpaper could not be applied"
fi

log "done"