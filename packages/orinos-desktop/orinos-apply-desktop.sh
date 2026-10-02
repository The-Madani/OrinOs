#!/usr/bin/env bash
# Apply the OrinOs Plasma desktop look (wallpaper + colour scheme) for the
# calling user. Idempotent: running it again just re-applies the same config.
#
# Uses KDE's own tools instead of hand-writing config files, because the
# applet layout format changes between Plasma releases. Must run inside a
# user session (needs a running D-Bus / kwriteconfig works headless too).
set -euo pipefail

WALLPAPER="${ORINOS_WALLPAPER:-/usr/share/backgrounds/orinos.png}"
SCHEME="${ORINOS_SCHEME:-BreezeDark}"

log() { printf 'orinos-desktop: %s\n' "$*" >&2; }

# Colour scheme: kdeglobals carries [KDE] ColorScheme=SchemeName.
if command -v plasma-apply-colorscheme >/dev/null 2>&1; then
    # plasma-apply-colorscheme wants the .colors file name without a path.
    name="$(basename "${SCHEME}")"
    plasma-apply-colorscheme "${name}" >/dev/null 2>&1 \
        && log "color scheme ${name} applied" \
        || log "WARNING: could not apply colour scheme ${name}"
else
    log "plasma-apply-colorscheme not found; skipping colour scheme"
fi

# Wallpaper: plasma-apply-wallpaper takes a path and writes it into the
# desktop containment for every screen.
if command -v plasma-apply-wallpaper >/dev/null 2>&1; then
    if [[ -f "${WALLPAPER}" ]]; then
        plasma-apply-wallpaper "${WALLPAPER}" >/dev/null 2>&1 \
            && log "wallpaper applied: ${WALLPAPER}" \
            || log "WARNING: could not apply wallpaper"
    else
        log "WARNING: wallpaper not found at ${WALLPAPER}"
    fi
else
    log "plasma-apply-wallpaper not found; skipping wallpaper"
fi

# Icons: Breeze is the Plasma default; only set it when the user has none,
# so an existing choice is never overwritten.
if command -v kwriteconfig >/dev/null 2>&1; then
    if [[ -z "$(kwriteconfig --file kdeglobals --group Icons --key Theme 2>/dev/null)" ]]; then
        kwriteconfig --file kdeglobals --group Icons --key Theme breeze
        log "icon theme set to breeze"
    fi
fi