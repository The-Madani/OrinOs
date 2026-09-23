# Phase 6 — Installer Evaluation

Status: evaluation in progress. Final decision after PoC in VM.

This document records the Phase 6 evaluation of installer candidates per
section 6 of [ARCHITECTURE.md](ARCHITECTURE.md).

## 1. Desktop context (new requirement)

OrinOs will ship **KDE Plasma with OrinOs' own configuration** (branded
Plasma setup, not upstream defaults). The installer must therefore install
`plasma` plus an OrinOs desktop-config package. Both candidates can do this;
the difference is in maintenance and branding effort, not capability.

## 2. Repository availability (verified against current Arch repos)

| Candidate | In official Arch repos? | Consequence |
|---|---|---|
| archinstall 4.4 | **Yes** — `[extra]` | Zero packaging burden; updates arrive with `pacman -Syu` |
| Calamares | **No** — absent from core/extra/multilib | OrinOs must build and maintain the package itself in `[orinos]`, against every Qt6 major update |

This is the decisive asymmetry: Calamares would immediately turn the
"[orinos] repo is for packages that don't exist upstream" rule into
"maintain a large C++/Qt package with a rolling dependency chain".

## 3. archinstall 4.x library findings (verified from upstream sources)

From `archinstall/lib/mirror/mirror_handler.py` and `models/mirrors.py`
(master, 2026-09):

- `CustomRepository(name, url, SignCheck, SignOption)` — first-class data
  model for an extra pacman repository, with signature policy per repo
  (`SignCheck.Never/Optional/Required` × `SignOption.TrustedOnly/TrustAll`).
- `MirrorConfiguration.custom_repositories` + `repositories_config()` emits
  the exact `[name] / SigLevel = ... / Server = ...` pacman.conf block —
  adding `[orinos]` is a documented code path, not a hack.
- `MirrorConfiguration` also supports custom servers and region selection
  (relevant later if OrinOs pins a mirror region).
- `examples/full_automated_installation.py` shows the documented top-level
  flow: `DeviceModification` → `DiskLayoutConfiguration` →
  `FilesystemHandler.perform_filesystem_operations()` →
  `with Installer(...) as installation:` → `mount_ordered_layout()` →
  `minimal_installation()` → `add_additional_packages()` → `create_users()`.
- Breakage policy: breaking changes only at major releases (currently 4.x),
  and usage is confined to these documented top-level APIs.
- Upstream docs site (archinstall.archlinux.page) still documents v2.3 —
  documentation lag is real; the working reference is the shipped source and
  `examples/`. This is a maintenance cost to budget for, tracked against
  major releases only.

## 4. Calamares findings

- Unchanged from ARCHITECTURE.md section 6: mature, declarative branding,
  pacman module. But all of that value is contingent on the packaging
  problem above: on Arch, distros maintain their own build (EndeavourOS
  pattern), which means a permanent fork-and-build commitment.

## 5. Provisional ranking

1. **archinstall as a library + OrinOs GUI frontend (Python/Qt via PySide,
   or a TUI first)** — primary PoC target.
2. Calamares — kept as fallback only if archinstall's API proves unstable
   during the PoC.
3. Independent installer — unchanged (last resort).

## 6. PoC plan (next step)

Build a minimal PoC, `installer/poc/`, that in a VM performs:

1. Partitioning (single-disk ESP + root, ext4 — same layout as the scripted
   example).
2. Install base + linux + networkmanager + plasma + a stub `orinos-desktop`
   config from a locally hosted `[orinos]` repo (proves the
   `CustomRepository` path end-to-end).
3. Bootloader install, user creation, fish as default shell.
4. Boot the installed system in QEMU and verify login to a Plasma session.

Score the result on: fit with Arch upstream, maintenance burden, branding
capability, installer quality. Decision (DECIDED status) is recorded in
ARCHITECTURE.md section 6 after the PoC.
