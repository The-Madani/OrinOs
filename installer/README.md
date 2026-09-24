# OrinOs Installer

Installs OrinOs onto a target disk using archinstall's documented library
APIs (the Phase 6 decision — see
[docs/INSTALLER-EVALUATION.md](../docs/INSTALLER-EVALUATION.md)). This is
the verified backend the graphical installer frontend will be built on.

## What it does

`install.py` (running inside the live environment, as root) installs OrinOs
onto a target disk with:

1. Partitioning: ESP (512 MiB, `/boot`) + ext4 root, whole-disk wipe.
2. `[orinos]` custom repository via `MirrorConfiguration` /
   `CustomRepository` — served over HTTP from the test host.
3. Base install + `plasma-meta` + `sddm` + `fish` + branding package
   (`orinos-branding` from `[orinos]`).
4. GRUB bootloader install, `NetworkManager` + `sddm` enabled.
5. A regular sudo user with fish as their shell.

## Files

```
install.py                     archinstall library install script
../packages/                   OrinOs package sources (PKGBUILDs)
../packages/build-repo.sh      builds the [orinos] repo from ../packages/
```

## Status — backend verified (2026-09-24)

The full flow was verified in a virt-manager/KVM VM: online install of
base + Plasma + sddm + fish + `orinos-branding` from the locally served
`[orinos]` repo; the installed system booted via GRUB into SDDM/Plasma with
`os-release` reporting OrinOs and fish as the user's shell. Findings and
fixes are recorded in
[docs/INSTALLER-EVALUATION.md](../docs/INSTALLER-EVALUATION.md).

## Test procedure (host = Arch machine, test in a VM only)

Prerequisites on the host: `makepkg`, `repo-add` (base-devel), `qemu`
desktop with KVM, and the built OrinOs live ISO.

```bash
# 1. Build the [orinos] repository
cd ../packages && ./build-repo.sh

# 2. Serve it (note the port, default 8000)
python3 -m http.server 8000 --directory os
```

```bash
# 3. Boot the live ISO in a VM on the same network as the host,
#    then inside the VM (as root):
python3 install.py /dev/sda http://<host-ip>:8000/os/x86_64 orin <password>

# 4. Reboot the VM and verify:
#    - GRUB boots the installed system
#    - SDDM shows a graphical Plasma login
#    - fastfetch reports OS: OrinOs (from orinos-branding)
#    - the created user logs in with fish
```

## Pass criteria

- Install completes without archinstall errors; post-install check passes.
- Installed system boots to a working Plasma (SDDM) session.
- `/etc/os-release` on the installed system is the OrinOs branding file
  (proving `[orinos]` was consumed during install).
- `pacman.conf` on the installed system contains the `[orinos]` block.
