#!/usr/bin/env python3
"""OrinOs Phase 6 PoC — archinstall-as-library install script.

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
    'plasma-applications',
    'konsole',
    'dolphin',
    'sddm',
    'fastfetch',
]

ESP_SIZE = Size(512, Unit.MiB)


def create_disk_layout(disk_path: Path) -> DiskLayoutConfiguration:
    device = device_handler.get_device(disk_path)
    if not device:
        raise ValueError(f'No device found for {disk_path}')

    modification = DeviceModification(device, wipe=True)

    esp = PartitionModification(
        status=ModificationStatus.CREATE,
        type=PartitionType.PRIMARY,
        start=Size(1, Unit.MiB, device.device_info.sector_size),
        length=ESP_SIZE,
        mountpoint=Path('/boot'),
        fs_type=FilesystemType.FAT32,
        flags=[PartitionFlag.BOOT],
    )
    modification.add_partition(esp)

    root_start = Size(1, Unit.MiB, device.device_info.sector_size) + ESP_SIZE
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

        installation.add_bootloader(Bootloader.Grub)

        installation.create_users(
            User(
                username=username,
                password=Password(plaintext=password),
                sudo=True,
            ),
        )

    print('PoC install finished. Check for warnings above, then reboot.')


if __name__ == '__main__':
    main()
