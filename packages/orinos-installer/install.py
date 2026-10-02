#!/usr/bin/env python3
"""OrinOs installer backend — archinstall-as-library install script.

Usage (as root, inside the live environment):
    python3 install.py PLAN_JSON

The plan file is a JSON document (produced by the graphical frontend or
hand-written) describing the whole installation:

    {
      "disk": "/dev/vda",
      "wipe": true,
      "partitions": [
        {"kind": "create", "start_mib": 1, "size_mib": 512,
         "fs": "fat32", "mountpoint": "/boot"},
        {"kind": "create", "start_mib": 513, "size_mib": 0,
         "fs": "ext4", "mountpoint": "/"}
      ],
      "user": "orin",
      "password": "secret",
      "hostname": "orinos",
      "repo_url": "file:///orinos-repo/x86_64"
    }

- wipe=true  → "erase disk" mode: the disk is wiped and the 'create'
  entries are the new layout (size_mib=0 means "rest of the disk").
- wipe=false → dual-boot mode: the disk is NOT wiped. 'existing' entries
  keep their data and filesystem untouched — only the mountpoint is
  written to the target's fstab. 'create' entries carve new partitions
  out of free space (size_mib=0 means "rest of the free gap").

A file:// repo_url is copied into the installed system, so the target's
pacman.conf keeps consuming the [orinos] repository after reboot.
"""

import json
import shlex
import shutil
import sys
from pathlib import Path

from archinstall.lib.disk.device_handler import device_handler
from archinstall.lib.disk.filesystem import FilesystemHandler
from archinstall.lib.installer import Installer
from archinstall.lib.mirror.mirror_handler import MirrorListHandler
from archinstall.lib.models.device import (
    DeviceModification,
    DiskEncryption,
    DiskLayoutConfiguration,
    DiskLayoutType,
    EncryptionType,
    FilesystemType,
    ModificationStatus,
    PartitionFlag,
    PartitionModification,
    PartitionType,
    Size,
    Unit,
)
from archinstall.lib.models.mirrors import (
    CustomRepository,
    MirrorConfiguration,
    SignCheck,
    SignOption,
)
from archinstall.lib.models.users import Password, User
from archinstall.lib.models.bootloader import Bootloader

BASE_PACKAGES = [
    'base',
    'linux',
    'linux-firmware',
    'grub',
    'efibootmgr',
    'networkmanager',
    'openssh',
    'sudo',
    'fish',
    'sddm',
    'fastfetch',
    'orinos-branding',
    # Wallpaper + colour scheme. Installed in the base set so it lands in
    # every installation, not only the full-desktop variant.
    'orinos-desktop',
]

DESKTOP_PACKAGES = {
    # Minimal Plasma: core desktop + session, terminal, file manager.
    'minimal': [
        'plasma-desktop',
        'plasma-session',
        'konsole',
    ],
    # Full Plasma: the complete 'plasma' group (apps, system settings, ...).
    # Recommended for most users.
    'full': [
        'plasma',
    ],
}


def desktop_packages(variant: str) -> list:
    return DESKTOP_PACKAGES.get(variant, DESKTOP_PACKAGES['full'])


def load_plan(path: Path) -> dict:
    with open(path) as fh:
        plan = json.load(fh)
    for key in ('disk', 'wipe', 'partitions', 'user', 'password',
                'hostname', 'repo_url'):
        if key not in plan:
            raise ValueError(f'plan is missing required key: {key}')
    plan.setdefault('desktop', 'full')
    if plan['desktop'] not in DESKTOP_PACKAGES:
        raise ValueError(f'unknown desktop variant: {plan["desktop"]}')
    plan.setdefault('timezone', 'UTC')
    plan.setdefault('keyboard', 'us')
    plan.setdefault('locale', 'en_US.UTF-8')
    plan.setdefault('autologin', False)
    plan.setdefault('encryption', None)
    plan.setdefault('swap', 'swapfile')
    plan.setdefault('swap_size_mib', 0)
    plan.setdefault('root_fs', 'ext4')
    plan.setdefault('bootloader', 'grub')
    plan.setdefault('disk_label', 'orinos')
    plan.setdefault('install_mode', 'online')
    plan.setdefault('full_name', '')
    plan.setdefault('root_password', '')
    return plan


def _build_encryption(plan: dict) -> DiskEncryption | None:
    """LUKS encryption when the plan requests it, else None."""
    spec = plan.get('encryption')
    if not spec:
        return None
    return DiskEncryption(
        encryption_type=EncryptionType.LUKS,
        encryption_password=Password(plaintext=spec['password']),
    )


def build_disk_layout(plan: dict) -> DiskLayoutConfiguration:
    disk_path = Path(plan['disk'])
    device = device_handler.get_device(disk_path)
    if not device:
        raise ValueError(f'No device found for {disk_path}')

    sector_size = device.device_info.sector_size
    disk_end = device.device_info.total_size
    wipe = bool(plan['wipe'])

    modification = DeviceModification(device, wipe=wipe)

    existing = {str(info.path): info for info in device.partition_infos}

    for entry in plan['partitions']:
        mp = entry.get('mountpoint')
        mountpoint = Path(mp) if mp else None

        if entry['kind'] == 'create':
            start = Size(int(entry.get('start_mib', 0)), Unit.MiB,
                         sector_size)
            size_mib = int(entry.get('size_mib', 0))
            length = (disk_end - start if size_mib <= 0
                      else Size(size_mib, Unit.MiB, sector_size))
            fs_type = FilesystemType(entry['fs'])
            flags = []
            # ESP flag makes archinstall mount the ESP in the target's
            # fstab; without it /boot stays unmounted after reboot.
            if mountpoint == Path('/boot'):
                flags = [PartitionFlag.BOOT, PartitionFlag.ESP]
            modification.add_partition(PartitionModification(
                status=ModificationStatus.CREATE,
                type=PartitionType.PRIMARY,
                start=start,
                length=length,
                mountpoint=mountpoint,
                fs_type=fs_type,
                flags=flags,
                mount_options=[],
            ))
        else:  # 'existing' — keep data, just assign a mountpoint
            info = existing.get(entry['dev'])
            if info is None:
                raise ValueError(
                    f'{entry["dev"]} is not a partition of {disk_path}')
            if not mountpoint:
                continue  # untouched partition — not part of OrinOs
            flags = list(info.flags)
            if mountpoint == Path('/boot') \
                    and PartitionFlag.ESP not in flags:
                flags = flags + [PartitionFlag.BOOT, PartitionFlag.ESP]
            modification.add_partition(PartitionModification(
                status=ModificationStatus.EXIST,
                type=info.type,
                start=info.start,
                length=info.length,
                fs_type=info.fs_type,
                dev_path=info.path,
                partn=info.partn,
                partuuid=info.partuuid,
                uuid=info.uuid,
                flags=flags,
                mountpoint=mountpoint,
                mount_options=[],
            ))

    return DiskLayoutConfiguration(
        config_type=DiskLayoutType.Default,
        device_modifications=[modification],
        disk_encryption=_build_encryption(plan),
    )


def create_mirror_config(orinos_repo_url: str) -> MirrorConfiguration:
    mirror_config = MirrorConfiguration()
    mirror_config.custom_repositories = [
        CustomRepository(
            name='orinos',
            url=orinos_repo_url,
            sign_check=SignCheck.Optional,
            sign_option=SignOption.TrustedOnly,
        ),
    ]
    return mirror_config


def stage(name: str) -> None:
    """Emit a machine-readable stage marker for the GUI progress bar."""
    print(f'[orinos-stage] {name}', flush=True)


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    plan = load_plan(Path(sys.argv[1]))
    repo_url = plan['repo_url']

    stage('preparing')
    disk_config = build_disk_layout(plan)

    stage('partitioning')
    fs_handler = FilesystemHandler(disk_config)
    if plan['wipe']:
        print(f'WARNING: erasing {plan["disk"]} completely.')
    else:
        print(f'Dual-boot install on {plan["disk"]}: existing partitions '
              'assigned to OrinOs keep their data.')
    fs_handler.perform_filesystem_operations()

    mirror_list_handler = MirrorListHandler()
    mirror_config = create_mirror_config(repo_url)

    with Installer(
        Path('/mnt'),
        disk_config,
        kernels=['linux'],
    ) as installation:
        installation.set_mirrors(mirror_list_handler, mirror_config)
        stage('mounting')
        installation.mount_ordered_layout()

        # A file:// [orinos] repo only exists in the live system; copy it
        # into the target so the installed system's pacman.conf keeps
        # resolving it after reboot. HTTP(S) URLs need no copy.
        if repo_url.startswith('file://'):
            src = Path(repo_url[len('file://'):])
            if src.is_dir():
                shutil.copytree(src, installation.target / 'orinos-repo')

        stage('base-system')
        installation.minimal_installation(hostname=plan['hostname'])

        # Locale, timezone and keyboard layout as picked in the GUI.
        locale, timezone, keyboard = (
            plan['locale'], plan['timezone'], plan['keyboard'])
        installation.arch_chroot(
            f'printf "%s\\n" "LANG={locale}" > /etc/locale.conf')
        installation.arch_chroot(
            f'ln -sf /usr/share/zoneinfo/{timezone} /etc/localtime')
        installation.arch_chroot(
            f'printf "%s\\n" "KEYMAP={keyboard}" > /etc/vconsole.conf')
        installation.arch_chroot(
            f'printf "%s\\n" "XKBMODEL=pc105" "LAYOUT={keyboard}" '
            '> /etc/default/keyboard')

        # Swap: either a swap partition (created by the GUI as a partition
        # with mountpoint None) or a swapfile sized by the plan.
        if plan.get('swap') == 'swapfile' and plan.get('swap_size_mib', 0) > 0:
            size_gib = plan['swap_size_mib'] // 1024
            installation.arch_chroot(
                f'dd if=/dev/zero of=/swapfile bs=1M '
                f'count={plan["swap_size_mib"]} status=none && '
                f'chmod 600 /swapfile && mkswap /swapfile >/dev/null && '
                f'swapon /swapfile && '
                f'printf "/swapfile none swap defaults 0 0\\n" '
                f'>> /etc/fstab')

        stage('packages')
        installation.add_additional_packages(
            BASE_PACKAGES + desktop_packages(plan['desktop']))
        installation.enable_service('NetworkManager.service')
        installation.enable_service('sddm.service')

        # Optional automatic desktop login (off by default, like every
        # mainstream distro: a password-protected session is the default).
        if plan.get('autologin'):
            installation.arch_chroot(
                'mkdir -p /etc/sddm.conf.d && printf "%s\\n" '
                f'"[Autologin]" "User={plan["user"]}" "Session=plasma" '
                '"Relogin=true" > /etc/sddm.conf.d/00-autologin.conf'
            )

        # GRUB names its menu entry from GRUB_DISTRIBUTOR (not os-release);
        # set it before add_bootloader so grub-mkconfig writes "OrinOs".
        installation.arch_chroot(
            'sed -i \'s/^GRUB_DISTRIBUTOR=.*/GRUB_DISTRIBUTOR="OrinOs"/\' '
            '/etc/default/grub'
        )

        stage('bootloader')
        boot_choice = plan.get('bootloader', 'grub')
        if boot_choice == 'none':
            print('Skipping bootloader installation (user chose none).')
        elif boot_choice == 'systemd-boot':
            installation.add_bootloader(Bootloader.Systemd)
        elif boot_choice == 'refind':
            installation.add_bootloader(Bootloader.Refind)
        else:
            installation.add_bootloader(Bootloader.Grub)

        stage('users')
        username = plan['user']
        # GECOS full name and an explicit root password when the user set one.
        gecos = plan.get('full_name') or username
        installation.create_users(
            User(
                username=username,
                password=Password(plaintext=plan['password']),
                sudo=True,
            ),
        )
        installation.arch_chroot(
            f'chfn -f {shlex.quote(gecos)} {shlex.quote(username)} '
            '2>/dev/null || true')
        if plan.get('root_password'):
            installation.arch_chroot(
                f'echo {username}:{plan["root_password"]} | chpasswd -e')

        # archinstall's User model has no shell field and useradd defaults
        # to bash; fish is in BASE_PACKAGES so make it the login shell.
        installation.arch_chroot(f'usermod -s /usr/bin/fish {username}')

        # orinos-desktop applies the OrinOs wallpaper and colour scheme from
        # a user unit, so it has to be enabled inside the user's home or the
        # account would boot into stock Breeze.
        installation.arch_chroot(
            'install -d -m 700 -o {u} -g {u} /home/{u}/.config/systemd/user'
            .format(u=shlex.quote(username)))
        installation.arch_chroot(
            'ln -sf /usr/lib/systemd/user/orinos-desktop.service '
            '/home/{u}/.config/systemd/user/default.target.wants/'
            'orinos-desktop.service'.format(u=shlex.quote(username)))

        # orinos-branding places /etc/os-release + /etc/issue via a rule in
        # /etc/tmpfiles.d (higher precedence than Arch's /usr/lib rule, which
        # would otherwise be treated as duplicate). The explicit path applies
        # the rule immediately; at boot systemd applies it anyway.
        stage('branding')
        installation.arch_chroot(
            'systemd-tmpfiles --create /etc/tmpfiles.d/orinos-branding.conf'
        )

        # Volume label on the root filesystem so it is identifiable in a
        # file manager or parted. FAT/ext use different tools than btrfs.
        label = (plan.get('disk_label') or 'orinos')[:16]
        root_fs = plan.get('root_fs', 'ext4')
        label_tool = 'btrfs filesystem label' if root_fs == 'btrfs' else 'e2label'
        installation.arch_chroot(
            f'root_dev=$(findmnt -n -o SOURCE / 2>/dev/null); '
            f'if [ -n "$root_dev" ]; then '
            f'  {label_tool} "$root_dev" {shlex.quote(label)} 2>/dev/null || true; '
            f'fi')

    stage('done')
    print('OrinOs install finished. Check for warnings above, then reboot.')


if __name__ == '__main__':
    main()
