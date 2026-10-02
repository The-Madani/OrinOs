# OrinOs Installer

Installs OrinOs onto a target disk using archinstall's documented library
APIs (the Phase 6 decision — see
[docs/INSTALLER-EVALUATION.md](../docs/INSTALLER-EVALUATION.md)).

## What it does

`install.py` (running inside the live environment, as root) installs OrinOs
onto a target disk from a JSON plan file:

1. **Erase-disk mode** (`wipe: true`): ESP (512 MiB, `/boot`) + ext4 root,
   whole-disk wipe.
2. **Dual-boot mode** (`wipe: false`): the disk is NOT wiped. Existing
   partitions assigned to OrinOs (`/boot`, `/`) keep their data and are
   only written into the target's fstab; new partitions are carved out of
   free space. Windows/other partitions are never touched.
3. `[orinos]` custom repository via `MirrorConfiguration` /
   `CustomRepository` — from the repo embedded in the live ISO
   (`file:///orinos-repo`, copied into the target) or an HTTP test URL.
4. Base install + `plasma` + `sddm` + `fish` + branding package
   (`orinos-branding` from `[orinos]`).
5. GRUB bootloader install (menu entry "OrinOs"), `NetworkManager` +
   `sddm` enabled.
6. A regular sudo user with fish as their shell.

## Files

```
install.py                     archinstall library install script (plan JSON)
gui/orinos_installer.py        graphical installer frontend (PySide6)
../packages/orinos-installer/  packaging (launcher, .desktop, polkit rule)
../packages/                   OrinOs package sources (PKGBUILDs)
../packages/build-repo.sh      builds the [orinos] repo from ../packages/
```

## Graphical frontend

`gui/orinos_installer.py` wraps the same backend:

language (English/Persian) → welcome → disk (auto-erase or manual
partitioning for dual-boot, with Verify) → user → summary → install →
done.

- The manual disk mode matches EndeavourOS-level completeness:
  per-disk partition tables, mountpoint assignment, partition creation
  in free space, and layout validation before continuing.
- Ships packaged as `orinos-installer` (`/usr/bin/orinos-installer`,
  desktop entry "Install OrinOs", polkit rule for the passwordless live
  user).
- The repo URL is resolved automatically: `ORINOS_REPO_URL` env var →
  the offline `file:///orinos-repo` embedded in the live ISO → the VM
  test host fallback.

## Status — backend verified (2026-09-24)

The full flow was verified in a virt-manager/KVM VM: online install of
base + Plasma + sddm + fish + `orinos-branding` from the locally served
`[orinos]` repo; the installed system booted via GRUB into SDDM/Plasma with
`os-release` reporting OrinOs and fish as the user's shell. Findings and
fixes are recorded in
[docs/INSTALLER-EVALUATION.md](../docs/INSTALLER-EVALUATION.md).

Since then the backend gained the JSON-plan interface (erase-disk +
dual-boot modes) and the graphical frontend ships as the
`orinos-installer` package inside the desktop live ISO. GUI click-through
verification in a VM is the current test target.

## Test procedure (host = Arch machine, test in a VM only)

Prerequisites on the host: `makepkg`, `repo-add` (base-devel), `qemu`
desktop with KVM, and the built OrinOs live ISO.

```bash
# 1. Build the desktop live ISO (also builds the [orinos] repo if missing)
./build-iso.sh desktop

# 2. Boot out/orinos-desktop-*.iso in a VM on the same network as the
#    host; the live session auto-logs into Plasma as `liveuser` and a
#    desktop icon "Install OrinOs" starts the graphical installer.

# 3. After the install completes, reboot the VM and verify:
#    - GRUB boots the installed system
#    - SDDM shows a graphical Plasma login
#    - fastfetch reports OS: OrinOs (from orinos-branding)
#    - the created user logs in with fish
```

The backend can also be driven directly inside the live environment
(as root):

```bash
python3 /usr/lib/orinos-installer/install.py /path/to/plan.json
```

## Pass criteria

- Install completes without archinstall errors; post-install check passes.
- Installed system boots to a working Plasma (SDDM) session.
- `/etc/os-release` on the installed system is the OrinOs branding file
  (proving `[orinos]` was consumed during install).
- `pacman.conf` on the installed system contains the `[orinos]` block.
