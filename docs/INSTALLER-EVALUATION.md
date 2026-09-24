# Phase 6 — Installer Evaluation

Status: **complete — DECIDED (2026-09-24): archinstall as a library +
OrinOs GUI frontend.** The PoC passed end-to-end in a VM; see section 7.

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

## 6. PoC plan

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

## 7. PoC result — PASSED (2026-09-24)

`installer/poc/install.py` ran against the OrinOs live ISO in a
virt-manager/KVM VM (40 GiB VirtIO disk, online install):

**What was proven**

- archinstall 4.4 library flow end-to-end: partitioning (512 MiB ESP on
  `/boot` + ext4 root), pacstrap of base + Plasma + sddm + fish +
  `orinos-branding` from the locally served `[orinos]` repo
  (`CustomRepository` path), GRUB bootloader, NetworkManager + sddm
  enabled, sudo user created.
- Installed system booted from disk (no ISO) into GRUB → SDDM → a working
  Plasma 6 session; `os-release` reported **OrinOs**; the user's login
  shell was **fish**.

**Bugs found and fixed during the PoC (all in `installer/poc/`)**

| Bug | Fix |
|---|---|
| `Size(512, Unit.MiB)` — archinstall 4.4 requires `sector_size` | Build sizes with the target device's `sector_size` |
| `plasma-applications` does not exist | Package group `plasma` |
| `orinos-branding` was defined in the repo but never requested | Added to the install package list |
| `/etc/issue` owned by `filesystem` → pacman conflict | Ship under `/usr/share/orinos-branding/`, place via `/etc/tmpfiles.d/` rule (`L+`) — `/usr/lib/tmpfiles.d/` is shadowed by Arch's `etc.conf` and a `C+` rule is ignored on Arch's symlink |
| os-release/issue not applied by package install | `systemd-tmpfiles --create /etc/tmpfiles.d/orinos-branding.conf` from the installer |
| GRUB menu said "Arch Linux" / then "Linux" | `GRUB_DISTRIBUTOR="OrinOs"` written before `add_bootloader` |
| ESP not in fstab → `/boot` empty after reboot | `PartitionFlag.ESP` alongside `BOOT` on the ESP partition |
| User shell was bash | `usermod -s /usr/bin/fish` after `create_users` (archinstall `User` has no shell field) |
| Live ISO lacked mirrorlist / keyring init / archinstall | Profile now ships a default mirrorlist, a `pacman-key-init.service` (init + populate at boot) and `archinstall` in `packages.x86_64` |
| fastfetch showed default logo; fish printed a greeting | `orinos-branding` now ships the fastfetch logo + `/etc/xdg/fastfetch/config.jsonc` and `/etc/fish/conf.d/orinos.fish` |

**Known noise, fixed in code, to be re-verified on the next ISO build**

- `could not register 'orinos' database (database already registered)`
  warnings during install: archinstall writes the custom-repo block more
  than once; harmless but to be silenced in the GUI installer phase.
- Host-side test-environment issues (Docker's iptables `FORWARD DROP`
  breaking libvirt NAT; vnet re-attachment after `net-destroy`) are
  environment-only, not OrinOs bugs.

**Score** — fit with Arch upstream: excellent (same backend Arch itself
uses). Maintenance burden: low (confined to documented top-level APIs).
Branding capability: full (our frontend + our packages). Installer
quality: backend proven; UX is our own work in the next phase.

**Decision:** archinstall-as-library + OrinOs GUI frontend (PySide6).
Calamares remains the documented fallback. Next step: build the graphical
frontend on `installer/poc/install.py`'s verified code path.
