# OrinOs

English | [فارسی](README.fa.md)

OrinOs is an independent Arch-based Linux distribution that uses Arch Linux
as its upstream.

It is not a fork: everything that exists in the Arch repositories is consumed
from Arch as-is. OrinOs develops and maintains only what is its own — a live
ISO, a distribution configuration, a graphical installer, its own package
repository and branding — while installed systems keep updating with
`pacman -Syu` from the Arch repositories plus the OrinOs repository.

**Status:** early architecture phase. There is no ISO, installer or package
repository yet. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the
architecture, decision statuses (DECIDED / PROVISIONAL / TO BE EVALUATED)
and the phase roadmap.

## Layout

```
docs/       Architecture and project documentation
```

Further directories (`profiles/`, `build/`, `packages/`, `installer/`, `ci/`)
are created together with their first real files in their respective phases.

## Roadmap

1. Architecture definition ← current
2. Minimal ISO
3. Boot testing
4. Distribution configuration
5. Branding
6. Graphical installer (evaluation: archinstall library vs Calamares)
7. Automated testing
8. CI/CD
9. First public release
10. Long-term maintenance

## Requirements (for later phases)

Building the ISO requires Arch Linux with `archiso` installed; testing
requires `qemu` and `edk2-ovmf`. Exact tooling and instructions will be
documented as each phase lands.
