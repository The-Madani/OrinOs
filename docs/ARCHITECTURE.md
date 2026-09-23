# OrinOs Architecture

Status: Phase 5 complete (branding verified in VM). Phase 6 (installer
evaluation) is next.

OrinOs is an independent Arch-based Linux distribution that uses Arch Linux
as its upstream.

This document is the normative architecture reference. Every architectural
decision carries a status:

- **DECIDED** — settled; changing it requires a new written decision.
- **PROVISIONAL** — chosen for now, revisited when the phase that depends on
  it begins.
- **TO BE EVALUATED** — no decision yet; options are listed and a dedicated
  evaluation is planned.

## 1. What OrinOs is (and is not)

OrinOs is a distribution built **on top of** Arch Linux, not a fork of it.
The distinction matters:

| Model | Description | OrinOs? |
|---|---|---|
| Custom Arch ISO | A single archiso profile with tweaks; still "Arch" in name, identity and tooling | No — that is an artifact, not a distribution |
| Arch-based independent distribution | Binary-compatible with Arch; own branding, own installer, own packages, own repository; keeps Arch as upstream | **Yes** |
| Partial rebuild fork | Rebuilds a subset of upstream packages (e.g. optimized kernels) | Not currently |
| Full fork | Rebuilds the entire package base | Explicitly rejected |

**Boundary rule:** OrinOs never rebuilds anything that already exists in the
Arch repositories. A package is only built in OrinOs' own repository if it is
new (does not exist upstream) or requires a patch (which triggers a
maintenance commitment and is decided case by case).

## 2. Relationship with Arch Linux

### Comes from Arch (consumed, never rebuilt)

- The entire `core` and `extra` repositories (kernel, glibc, systemd, pacman,
  all userspace tools), plus `multilib` if ever needed.
- The pacman package management system itself, its signing infrastructure and
  the official Arch mirrors.
- Upstream tools used as packaged dependencies: `archiso`, `arch-install-scripts`.
- `archinstall`, if it is chosen as the installer backend (see section 6).

### Belongs to OrinOs (developed and maintained by this project)

- **Live ISO profile** — an archiso profile owned by OrinOs
  (Phase 2).
- **Distribution configuration** — `/etc` defaults, `os-release`, MOTD,
  enabled services, default user environment, packaged so that installed
  systems receive updates via pacman (Phase 4).
- **Graphical installer** — OrinOs' own installer
  (Phase 6).
- **Package repository** — a pacman repository named `[orinos]` holding
  OrinOs-built packages (Phase 4+).
- **Signing infrastructure** — OrinOs' own GPG keys, separate from the Arch
  keyring (the Arch keyring is still required to verify upstream packages).
- **Branding** — name, logo, artwork, boot themes, release process.

**Infrastructure — DECIDED (Phase 2):** all infrastructure uses free
services — GitHub for git, CI (GitHub Actions) and ISO distribution
(Releases); GitHub Pages for serving the `[orinos]` pacman repository (a
pacman repo is just static files). No paid hosting, no custom domain; URLs
point to `github.com/The-Madani/OrinOs` unless a domain is acquired later.

## 3. Package management — DECIDED (with a deferred component)

**Current state (until the OrinOs repository exists):** stock pacman against
the official Arch repositories. The ISO installs packages from Arch mirrors
at build time via the profile's `pacman.conf`.

**Planned `[orinos]` repository — DECIDED in principle, TO BE EVALUATED for
hosting:**

- A standard pacman repository: `[orinos]` with an `orinos.db` and signed
  packages, served over HTTPS.
- Built with the standard Arch tooling: `makepkg` to build packages,
  `repo-add` to create/update the repository database. No new tooling.
- Repository ordering in `pacman.conf` matters: `[orinos]` is listed **before**
  `[core]`/`[extra]` so that same-named OrinOs packages win. (Same-named
  packages should be rare — they only exist where a patch was justified.)
- Signature level: `Required DatabaseOptional` (the Arch default) — packages
  must be signed with the OrinOs key, never `TrustAll`.
- The OrinOs signing key is provided to installed systems via an
  `orinos-keyring` package (hypothetical name; final naming in Phase 4).
- **DECIDED (Phase 2):** packages that exist only in the AUR but are wanted
  in the default installation (first case: `yay`) will be built and published
  in the `[orinos]` repository. This is the repository's first real use case;
  `yay` lands in the ISO once the repository exists (Phase 4).

**Hosting — TO BE EVALUATED:** a pacman repository is only static files
(database + packages + signatures), so static hosting (e.g. GitHub Pages) is
sufficient. The choice is deferred until Phase 4.

## 4. ISO build with archiso — DECIDED

OrinOs uses **archiso** (the official Arch Linux ISO build tool) to build its
ISO. Facts below are taken from the archiso package documentation
(`README.rst`, `README.profile.rst` shipped with archiso; verified against
archiso 90-1 — version-dependent details are marked).

An archiso profile consists of:

```
profile/
├── airootfs/          # file overlay applied directly onto the live system's /
├── efiboot/           # systemd-boot configuration for UEFI boot
├── syslinux/          # syslinux/isolinux configuration for BIOS boot
├── grub/              # GRUB configuration for UEFI boot
├── packages.x86_64    # package list for the live environment (one per line)
├── pacman.conf        # pacman configuration used at build time
└── profiledef.sh      # profile metadata and build options
```

Key mechanics (from the official profile documentation):

- `profiledef.sh` defines `iso_name`, `iso_label`, `iso_publisher`,
  `iso_version`, `bootmodes`, `buildmodes` and the airootfs image type. This
  is where OrinOs branding enters the ISO.
- `packages.x86_64` is a plain list; `mkinitcpio` and `mkinitcpio-archiso`
  are mandatory entries.
- `airootfs/` is an overlay: files placed there appear at the same path in
  the live system. Distribution configuration lives here.
- The ISO filename is constructed as `<iso_name>-<iso_version>-<arch>.iso`.
- archiso honors `SOURCE_DATE_EPOCH` for reproducible metadata (used by the
  shipped baseline profile for `iso_label` and `iso_version`).
- Build invocation: `mkarchiso -w <work_dir> -o <out_dir> <profile>`.
- Build modes are `iso`, `bootstrap` and `netboot`. OrinOs uses `iso` only;
  `bootstrap` and `netboot` are out of scope (section 16).

**Starting point — DECIDED:** OrinOs starts from the **baseline** profile
(minimal, ~13 packages) rather than **releng** (the official rescue/install
medium, 120+ packages). Rationale: baseline is small enough to understand
completely; every added package is then a conscious decision. Packages will
be added deliberately as phases progress.

**Full byte-level reproducibility — PROVISIONAL / known limitation:** archiso
supports `SOURCE_DATE_EPOCH`, but packages are pulled from rolling Arch
mirrors at build time, so two builds at different times get different package
versions. The achievable goal is *reproducible builds from a given state of
the Arch repositories*, not byte-identical ISOs across time. Defining
exactly how much reproducibility to target is revisited in Phase 2.

## 5. ISO testing — DECIDED (tooling), PROVISIONAL (scope)

archiso ships **`run_archiso`**, an official helper that boots the built ISO
in QEMU with BIOS (`run_archiso -i file.iso`) or UEFI
(`run_archiso -u -i file.iso`). OrinOs uses this as its local test tool.

Automated CI boot testing (headless QEMU, checking the system reaches a login
prompt) is planned for Phase 7 — PROVISIONAL until designed.

## 6. Graphical installer — TO BE EVALUATED

No decision has been made. Phase 6 will run a proof-of-concept and
compatibility evaluation for each candidate before choosing.

### Candidate A: custom frontend on top of archinstall as a library

Facts (from official archinstall sources and documentation as of 2026):

- archinstall is developed by Arch Linux, written in Python, and its stated
  mission is to be used "primarily as a flexible library for installing Arch
  and managing services and packages, with the guided installer built on top
  of it."
- It performs installation via `pacstrap` against configured repositories.
- It supports custom mirrors and custom repositories through its
  `MirrorConfiguration` and `PacmanConfig` APIs, and declarative installs via
  JSON configuration files.
- Its API is not frozen: breaking changes are pushed to major releases, and
  major releases with rewrites have occurred repeatedly in recent years.
- The upstream-guided installer is a TUI. There is no official GUI frontend
  and no branding system — a GUI would be OrinOs' own frontend code.

**Upside:** installation plumbing (partitioning, pacstrap, bootloader,
locale, users) comes from the same backend Arch itself uses; the OrinOs
effort is confined to the UX layer, written in the same language as the
backend.

**Risk:** API breakage across major releases must be tracked; deep use of
internals would amplify this, so usage would be confined to the documented
top-level APIs (`Installer`, `Pacman`, mirror configuration).

### Candidate B: Calamares with OrinOs branding

Facts (from official Calamares sources and documentation as of 2026):

- Calamares is an independent, mature graphical installer (development since
  2014; upstream migrated from GitHub to Codeberg in 2025). C++/Qt core with
  modules in C++, Python and QML.
- Distributions customize it via a *branding component*: a declarative
  descriptor (YAML) plus images and an optional QML slideshow — no C++ needed
  for basic branding.
- Its `packages` module natively supports pacman, making Arch-based
  distributions a supported backend.
- Arch-based distributions (e.g. EndeavourOS) commonly maintain a Calamares
  fork plus a separate branding repository — i.e. a proven but continuous
  maintenance pattern.

**Upside:** a polished, battle-tested GUI nearly out of the box; branding is
declarative; pacman is first-class.

**Risk:** Qt/C++ competence required for anything beyond declarative
branding; a fork may become necessary for behavioral changes; heavier
dependency footprint.

### Candidate C: fully independent installer

Written from scratch. Provides full control but requires re-implementing
partitioning, pacstrap orchestration and bootloader installation — the
highest-risk, highest-effort option. Listed for completeness; it is only
serious if both A and B fail evaluation.

### Evaluation plan (Phase 6)

A PoC of each viable candidate performing a minimal install in a VM,
scored on: fit with Arch upstream, maintenance burden, branding capability,
and installer quality. Decision follows the evaluation.

## 7. Configuration strategy

Most of the distribution's identity is **configuration, not code**:

- Controllable with files/overlays: `os-release`, default locale/keymap/
  timezone, MOTD, skeleton files, enabled services (symlinks in airootfs),
  boot menu entries, package lists, the installed system's `pacman.conf`.
  The live system's default shell (fish) is also pure overlay configuration
  (`passwd` + package list entry).
- Requiring actual code: the installer, any first-boot logic, build and CI
  scripts, and PKGBUILDs for OrinOs packages.

**PROVISIONAL:** configuration files will eventually be packaged (e.g. an
`orinos-config` package) so installed systems receive configuration updates
through `pacman -Syu` instead of being frozen at install time. The exact
packaging split is decided in Phase 4.

## 8. Repository layout — DECIDED (minimal for now)

```
orinos/
├── docs/
│   └── ARCHITECTURE.md   # this document
├── README.md
└── (future, each created with its first real file in its phase:)
    ├── profiles/orinos-live/   # archiso profile          (Phase 2)
    ├── build/                  # build scripts            (Phase 2)
    ├── packages/               # PKGBUILDs for OrinOs pkgs (Phase 4)
    ├── installer/              # installer source          (Phase 6)
    └── ci/                     # GitHub Actions workflows  (Phase 8)
```

No empty placeholder directories are committed: git does not track
directories, so each directory appears together with its first real file.
This keeps every commit meaningful.

## 9. Build system — DECIDED in principle, PROVISIONAL in details

- One entry point: `./build/build-iso.sh <profile>` (name provisional).
- Runs **only on Arch Linux** (stated limitation of archiso itself).
- The build script validates prerequisites before building (archiso and its
  documented dependency list: arch-install-scripts, dosfstools, e2fsprogs,
  grub, libarchive, libisoburn, mtools, openssl, pacman, squashfs-tools, and
  others per the shipped README).
- Work and output directories live outside the source tree and are
  gitignored.
- `SOURCE_DATE_EPOCH` is set from the build input (e.g. the last commit
  timestamp) so that metadata is deterministic; see the reproducibility
  caveat in section 4.

## 10. CI/CD — PROVISIONAL (design; implementation in Phase 8)

GitHub Actions, using the official `archlinux` container image (hosted
runners are not Arch):

1. **PR checks:** linting (e.g. shellcheck, YAML lint) and a build smoke test.
2. **Main branch:** full ISO build, artifact upload, automated boot test in
   QEMU.
3. **Releases (later):** on tag — build, sign, publish to GitHub Releases
   with checksums and signatures.

## 11. Rolling-release maintenance

Because Arch is rolling, OrinOs' ISOs are periodic snapshots. The maintenance
model follows directly:

### Updated automatically via `pacman -Syu` (no maintainer action)

- All upstream packages on installed systems.
- Everything in the live ISO, on each rebuild.

### Requires maintainer attention

| Concern | Cadence | Automatable? |
|---|---|---|
| Rebuild ISO + verify it still builds (rolling packages can break a build) | Weekly/monthly via CI schedule | Yes |
| Automated boot test against fresh upstream state | Weekly via CI schedule | Yes |
| Breaking changes in archiso itself (also rolling) | Check its changelog per rebuild | Semi (changelog check in CI) |
| Breaking changes in archinstall (if chosen as backend) | Before each release; pinned by integration test | Semi |
| OrinOs configs broken by upstream changes (e.g. systemd syntax) | On boot-test failure only | No — manual fix |

**Principle:** maintenance is primarily "rebuild + boot test, regularly,
automated" — not package curation, because OrinOs does not rebuild packages.

## 12. Versioning — DECIDED

Calendar versioning, mirroring Arch's own practice:

```
orinos-YYYY.MM.DD-x86_64.iso
```

- Derived from `SOURCE_DATE_EPOCH` (the pattern archiso itself uses).
- Rolling releases have no semver meaning; the snapshot date is the only
  meaningful differentiator.
- OrinOs' own artifacts (installer, packages) use independent semver —
  separate from the distribution version.

## 13. Security

- **Package signing:** OrinOs packages are signed with a dedicated GPG key
  (`makepkg --sign`, `repo-add -s`). The public key ships via a keyring
  package. `SigLevel Required DatabaseOptional`; `TrustAll` is forbidden.
- **Key hygiene:** separate keys for repository signing and release signing
  (compartmentalization). Private keys are never committed.
- **ISO integrity:** every release ships SHA-256 checksums plus a PGP
  signature of the ISO and checksum file, following Arch's release practice.
- **Git tags** are signed.
- **CI secrets:** minimum necessary scope; repository signing may be kept
  outside CI (manual signing by a maintainer) if risk warrants.

## 14. Technology choices — DECIDED (with one open item)

| Need | Choice | Rationale |
|---|---|---|
| ISO build | archiso (`mkarchiso`) | Official Arch tool; the tool Arch itself ships its ISO with |
| Build/glue scripts | Bash, linted with shellcheck | Sufficient for orchestrating existing tools |
| Boot testing | `run_archiso` + QEMU | Official archiso helper |
| CI | GitHub Actions + `archlinux` container | Standard for Arch-based projects |
| Installer backend/frontend | **TO BE EVALUATED** (section 6) | Decision deferred to Phase 6 |
| OrinOs packages | `makepkg` + `repo-add` | Standard Arch packaging |
| Compiled languages (C/C++/Rust) | Not planned | No technical need identified; revisit only with a concrete justification |

## 15. Roadmap

| Phase | Work |
|---|---|
| 1 | Architecture definition (this document) |
| 2 | Minimal ISO: profile from baseline, build script |
| 3 | Boot testing in QEMU (BIOS + UEFI) |
| 4 | Distribution configuration; decision on config packaging |
| 5 | Branding: final name/artwork, boot themes |
| 6 | Installer: PoC + compatibility evaluation (archinstall library vs Calamares), then decision and implementation |
| 7 | Automated testing: build + boot + installer end-to-end |
| 8 | CI/CD: GitHub Actions workflows, scheduled rebuild/boot tests |
| 9 | First public GitHub Release (signed, checksummed) |
| 10 | Long-term maintenance process |

## 16. Explicitly out of scope (for now)

- Any fork of Arch packages.
- The `[orinos]` repository, OrinOs packages, the installer — until their
  phases.
- `netboot` and `bootstrap` build modes.
- Architectures other than x86_64.
- Custom mirrors or CDN.
- Full byte-level ISO reproducibility across time (see section 4).

## 17. Immediate next step

Phase 2: create `profiles/orinos-live/` (adapted from archiso's baseline
profile) and `build/build-iso.sh`, then build and boot-test the first ISO
locally.
