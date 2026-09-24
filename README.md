# OrinOs

English | [فارسی](README.fa.md)

OrinOs is an independent Arch-based Linux distribution that uses Arch Linux
as its upstream.

It is not a fork: everything that exists in the Arch repositories is consumed
from Arch as-is. OrinOs develops and maintains only what is its own — a live
ISO, a distribution configuration, a graphical installer, its own package
repository and branding — while installed systems keep updating with
`pacman -Syu` from the Arch repositories plus the OrinOs repository.

**Status:** Phases 1–6 complete. A bootable live ISO exists
(`profiles/orinos-live/`, built with `archiso`), and the installer backend
was verified end-to-end in a VM: an online install of a full Plasma desktop
with the first OrinOs package from the `[orinos]` repository. The graphical
installer frontend (Phase 6 follow-up) is the next deliverable. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the architecture, decision
statuses (DECIDED / PROVISIONAL / TO BE EVALUATED) and the phase roadmap,
and [installer/poc/README.md](installer/poc/README.md) to reproduce the
installer proof-of-concept.

## Layout

```
docs/                 Architecture and project documentation
profiles/orinos-live/ archiso live ISO profile (Phase 2)
branding/             Brand assets (Phase 5)
installer/poc/        Installer PoC: archinstall-as-library + [orinos] repo (Phase 6)
```

## Roadmap

1. ~~Architecture definition~~
2. ~~Minimal ISO~~
3. ~~Boot testing~~
4. ~~Distribution configuration~~
5. ~~Branding~~
6. ~~Installer evaluation + PoC (archinstall library — PASSED)~~ ← graphical installer frontend next
7. Automated testing
8. CI/CD
9. First public release
10. Long-term maintenance

## Requirements

Building the ISO requires Arch Linux with `archiso` installed; testing
requires a VM (`virt-manager`/`qemu` with `edk2-ovmf`). Building the PoC
repository requires `makepkg`/`repo-add` (`base-devel`).

## License

OrinOs is free and open-source software. All code and configuration in this
repository is licensed under the [GNU GPL v3](LICENSE). The brand assets in
`branding/` (logo, wordmark, wallpapers) are not covered by the GPL; see
`branding/LICENSE-BRAND.md` for their usage terms.

OrinOs is not affiliated with, endorsed by, or a fork of Arch Linux. "Arch
Linux" is a trademark of Arch Linux PKG.
