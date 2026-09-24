#!/usr/bin/env python3
"""OrinOs installer backend — archinstall-as-library install script.

Runs inside the live ISO (or any Arch live environment with archinstall
installed). It installs OrinOs onto /dev/sda with:

- ESP + root partitioning (no /home split — single-disk desktop layout)
- [orinos] custom repository served from the local network (or localhost)
- base + linux + plasma + fish, NetworkManager enabled
- GRUB bootloader, a regular user, fish as their login shell

WARNING: wipes the target disk. Test only in a VM.

Usage (as root, inside the live environment):
    python3 install.py /dev/sda ORINOS_REPO_URL USER_NAME USER_PASSWORD

Example:
    python3 install.py /dev/sda http://192.168.122.1:8000/os/x86_64 orin secret
"""

import sys
from pathlib import Path

from archinstall.lib.disk.device_handler import device_handler
from archinstall.lib.disk.filesystem import FilesystemHandler
from archinstall.lib.installer import Installer
from archinstall.lib.mirror.mirror_handler import MirrorListHandler
from archinstall.lib.models.device import (
    DeviceModification,
    DiskLayoutConfiguration,
    DiskLayoutType,
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
from archinstall.lib.models.packages import Repository
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
    'plasma-meta',
    'plasma',
    'konsole',
    'dolphin',
    'sddm',
    'fastfetch',
    'orinos-branding',
]

def create_disk_layout(disk_path: Path) -> DiskLayoutConfiguration:
    device = device_handler.get_device(disk_path)
    if not device:
        raise ValueError(f'No device found for {disk_path}')

    sector_size = device.device_info.sector_size
    esp_size = Size(512, Unit.MiB, sector_size)

    modification = DeviceModification(device, wipe=True)

    esp = PartitionModification(
        status=ModificationStatus.CREATE,
        type=PartitionType.PRIMARY,
        start=Size(1, Unit.MiB, sector_size),
        length=esp_size,
        mountpoint=Path('/boot'),
        fs_type=FilesystemType.FAT32,
        # ESP flag makes archinstall mount the ESP in the target's fstab;
        # without it /boot stays unmounted after the first reboot.
        flags=[PartitionFlag.BOOT, PartitionFlag.ESP],
    )
    modification.add_partition(esp)

    root_start = Size(1, Unit.MiB, sector_size) + esp_size
    root = PartitionModification(
        status=ModificationStatus.CREATE,
        type=PartitionType.PRIMARY,
        start=root_start,
        length=device.device_info.total_size - root_start,
        mountpoint=Path('/'),
        fs_type=FilesystemType('ext4'),
        mount_options=[],
    )
    modification.add_partition(root)

    return DiskLayoutConfiguration(
        config_type=DiskLayoutType.Default,
        device_modifications=[modification],
    )


def create_mirror_config(orinos_repo_url: str) -> MirrorConfiguration:
    mirror_config = MirrorConfiguration()

    # orinos repository, listed before core/extra because archinstall appends
    # custom repositories to the end of pacman.conf; pacman uses the first
    # match, so we rely on orinos packages never sharing names with upstream.
    mirror_config.custom_repositories = [
        CustomRepository(
            name='orinos',
            url=orinos_repo_url,
            sign_check=SignCheck.Optional,
            sign_option=SignOption.TrustedOnly,
        ),
    ]

    return mirror_config


def main() -> None:
    if len(sys.argv) != 5:
        print(__doc__)
        sys.exit(1)

    disk_path = Path(sys.argv[1])
    orinos_repo_url = sys.argv[2]
    username = sys.argv[3]
    password = sys.argv[4]

    disk_config = create_disk_layout(disk_path)

    fs_handler = FilesystemHandler(disk_config)
    # WARNING: this wipes the target disk
    fs_handler.perform_filesystem_operations()

    mirror_list_handler = MirrorListHandler()
    mirror_config = create_mirror_config(orinos_repo_url)

    with Installer(
        Path('/mnt'),
        disk_config,
        kernels=['linux'],
    ) as installation:
        installation.set_mirrors(mirror_list_handler, mirror_config)
        installation.mount_ordered_layout()
        installation.minimal_installation(hostname='orinos')
        installation.add_additional_packages(BASE_PACKAGES)
        installation.enable_service('NetworkManager.service')
        installation.enable_service('sddm.service')

        # GRUB names its menu entry from GRUB_DISTRIBUTOR (not os-release);
        # set it before add_bootloader so grub-mkconfig writes "OrinOs".
        installation.arch_chroot(
            'sed -i \'s/^GRUB_DISTRIBUTOR=.*/GRUB_DISTRIBUTOR="OrinOs"/\' /etc/default/grub'
        )

        installation.add_bootloader(Bootloader.Grub)

        installation.create_users(
            User(
                username=username,
                password=Password(plaintext=password),
                sudo=True,
            ),
        )

        # archinstall's User model has no shell field and useradd defaults
        # to bash; fish is in BASE_PACKAGES so make it the login shell.
        installation.arch_chroot(f'usermod -s /usr/bin/fish {username}')

        # orinos-branding places /etc/os-release + /etc/issue via a rule in
        # /etc/tmpfiles.d (higher precedence than Arch's /usr/lib rule, which
        # would otherwise be treated as duplicate). The explicit path applies
        # the rule immediately; at boot systemd applies it anyway.
        installation.arch_chroot(
            'systemd-tmpfiles --create /etc/tmpfiles.d/orinos-branding.conf'
        )

    print('PoC install finished. Check for warnings above, then reboot.')


if __name__ == '__main__':
    main()
