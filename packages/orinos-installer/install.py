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
import os
import re
import shlex
import shutil
import subprocess
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

# Packages that must exist before archinstall runs mkinitcpio.
#
# The mkinitcpio 'encrypt' hook does `add_binary 'cryptsetup'`, which resolves
# the binary through PATH and calls `error` (and therefore fails the whole
# build) when it is absent. minimal_installation() runs mkinitcpio before
# add_additional_packages(), so anything needed by that hook has to be part of
# the base package set handed to the Installer constructor instead.
PRE_INITRAMFS_PACKAGES = [
    'cryptsetup',
]

DESKTOP_PACKAGES = {
    # Minimal Plasma: core desktop, terminal and file manager.
    # plasma-desktop pulls in plasma-workspace (which carries kwin, the
    # session and the applets), so naming a session package separately would
    # only risk naming one that does not exist.
    'minimal': [
        'plasma-desktop',
        'konsole',
        'dolphin',
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
    plan.setdefault('install_mode', 'online')
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
    plan.setdefault('full_name', '')
    plan.setdefault('root_password', '')
    _validate_plan(plan)
    return plan


USERNAME_RE = re.compile(r'^[a-z_][a-z0-9_-]{0,31}$')
HOSTNAME_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$')
LOCALE_RE = re.compile(r'^[A-Za-z]{2,3}_[A-Za-z]{2}(\.[A-Za-z0-9-]+)?(@\w+)?$')
TZ_RE = re.compile(r'^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+){0,2}$')
KEYMAP_RE = re.compile(r'^[A-Za-z0-9_.-]+$')


def _validate_plan(plan: dict) -> None:
    """Reject values that are later interpolated into commands or files.

    The plan comes from a GUI or is hand-written; none of these fields may
    carry whitespace, quotes or shell metacharacters.
    """
    if not USERNAME_RE.match(plan['user']):
        raise ValueError(f'invalid user name: {plan["user"]!r}')
    if not HOSTNAME_RE.match(plan['hostname']):
        raise ValueError(f'invalid hostname: {plan["hostname"]!r}')
    if not LOCALE_RE.match(plan['locale']):
        raise ValueError(f'invalid locale: {plan["locale"]!r}')
    if not TZ_RE.match(plan['timezone']):
        raise ValueError(f'invalid timezone: {plan["timezone"]!r}')
    if not KEYMAP_RE.match(plan['keyboard']):
        raise ValueError(f'invalid keyboard layout: {plan["keyboard"]!r}')
    if not str(plan['disk']).startswith('/dev/'):
        raise ValueError(f'disk must be a /dev path: {plan["disk"]!r}')
    full_name = plan.get('full_name') or ''
    if any(c in full_name for c in ':\n\r,='):
        raise ValueError('full_name must not contain : , = or newlines')
    for key in ('password', 'root_password'):
        value = plan.get(key) or ''
        if '\n' in value or '\r' in value:
            raise ValueError(f'{key} must not contain newlines')
    swap_mib = plan.get('swap_size_mib', 0)
    if not isinstance(swap_mib, int) or swap_mib < 0:
        raise ValueError('swap_size_mib must be a non-negative integer')
    enc = plan.get('encryption')
    if enc and not enc.get('password'):
        raise ValueError('encryption requires a non-empty password')


def _build_encryption(plan: dict, modification: DeviceModification
                      ) -> DiskEncryption | None:
    """LUKS encryption when the plan requests it, else None.

    archinstall only encrypts the partitions listed in ``partitions`` and
    refuses an empty list for plain LUKS. The root partition is encrypted;
    /boot stays readable so the bootloader can load the kernel.
    """
    spec = plan.get('encryption')
    if not spec:
        return None
    to_encrypt = [p for p in modification.partitions
                  if p.mountpoint == Path('/')]
    if not to_encrypt:
        raise ValueError('encryption requested but the plan has no / '
                         'partition to encrypt')
    return DiskEncryption(
        encryption_type=EncryptionType.LUKS,
        encryption_password=Password(plaintext=spec['password']),
        partitions=to_encrypt,
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
    # Keep 1 MiB free at the end: the backup GPT header lives there, and
    # archinstall rejects a partition that overlaps it.
    usable_end = disk_end.gpt_end()

    for entry in plan['partitions']:
        mp = entry.get('mountpoint')
        mountpoint = Path(mp) if mp else None

        if entry['kind'] == 'create':
            start = Size(int(entry.get('start_mib', 0)), Unit.MiB,
                         sector_size)
            size_mib = int(entry.get('size_mib', 0))
            if size_mib > 0:
                length = Size(size_mib, Unit.MiB, sector_size)
            else:
                # "Rest of the free gap": stop at the next existing
                # partition after `start` (dual-boot), else at the disk end.
                limit = usable_end
                if not wipe:
                    later = [i.start for i in device.partition_infos
                             if i.start > start]
                    if later:
                        limit = min(later)
                length = (limit - start).align()
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
        disk_encryption=_build_encryption(plan, modification),
    )


def create_mirror_config(orinos_repo_url: str) -> MirrorConfiguration:
    """Mirror configuration for the target's pacman.conf.

    Only the OrinOs repository is pinned. Arch's own mirrors are left to
    archinstall, which writes a generated mirrorlist.
    """
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


class PreflightError(RuntimeError):
    """A pre-flight safety check failed; nothing has been written yet."""


def run(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def findmnt_value(mountpoint: Path, column: str) -> str:
    """Single findmnt column for the filesystem mounted at `mountpoint`."""
    proc = run(['findmnt', '-n', '-o', column, '--target', str(mountpoint)])
    return proc.stdout.strip() if proc.returncode == 0 else ''


def check_not_busy(disk: str) -> None:
    """Refuse to touch a disk that is mounted, in use or has holders.

    Partitioning a mounted disk corrupts whatever is running from it, and a
    disk with active holders (LVM, mdraid, dm-crypt) must be torn down by the
    operator first -- guessing here loses data.
    """
    proc = run(['lsblk', '-nrpo', 'NAME,TYPE,MOUNTPOINTS', disk])
    if proc.returncode != 0:
        raise PreflightError(
            f'lsblk could not inspect {disk}: {proc.stderr.strip()}')

    mounted = []
    holders = []
    for line in proc.stdout.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        name, kind, mounts = fields[0], fields[1], fields[2:]
        # lsblk lists the disk's *children*; anything that is neither the
        # disk itself nor a plain partition is a stacked device on top of
        # it (LVM, mdraid, dm-crypt, multipath ...).
        if kind not in ('disk', 'part'):
            holders.append(f'{name} ({kind})')
        mounted += mounts

    if mounted:
        raise PreflightError(
            f'{disk} has mounted partitions or active swap: '
            f'{", ".join(sorted(set(mounted)))}. Unmount them before '
            'installing.')
    if holders:
        raise PreflightError(
            f'{disk} is in use by {", ".join(holders)}. Tear down the '
            'LVM / RAID / encrypted mappings before installing.')


def check_target_empty(mountpoint: Path) -> None:
    """A stale /mnt from an aborted run must not be reused silently."""
    if not mountpoint.exists():
        return
    entries = [p for p in mountpoint.iterdir() if p.name not in ('lost+found',)]
    if entries:
        raise PreflightError(
            f'{mountpoint} is not empty ({len(entries)} entries) — a '
            'previous install may have been interrupted. Clear it before '
            'retrying.')


def check_boot_mode() -> str:
    """Return 'uefi' or 'bios'; the bootloader must match the firmware."""
    if Path('/sys/firmware/efi').is_dir():
        return 'uefi'
    return 'bios'


def check_encryption_support() -> None:
    """cryptsetup must exist before an encrypted layout is attempted."""
    if shutil.which('cryptsetup') is None:
        raise PreflightError(
            'cryptsetup is not installed, so LUKS encryption cannot be '
            'used. Reinstall without encryption or add the package.')


def preflight(plan: dict, mountpoint: Path) -> str:
    """Run every safety check before a single byte is written."""
    disk = plan['disk']
    if not Path(disk).exists():
        raise PreflightError(f'Target disk {disk} does not exist.')

    # Both modes: partitioning or formatting under a mounted filesystem
    # corrupts it, and dual-boot still rewrites the partition table.
    check_not_busy(disk)

    check_target_empty(mountpoint)

    if plan.get('encryption'):
        check_encryption_support()

    mode = check_boot_mode()
    boot_choice = plan.get('bootloader', 'grub')
    if boot_choice == 'systemd-boot' and mode == 'bios':
        raise PreflightError(
            'systemd-boot needs UEFI firmware, but this machine booted '
            'in BIOS mode. Choose GRUB or rEFInd instead.')
    if mode == 'bios' and plan.get('encryption'):
        raise PreflightError(
            'Encrypted root requires UEFI firmware for the bootloader to '
            'unlock it at boot; this machine is in BIOS mode.')

    if plan.get('install_mode', 'online') == 'offline':
        raise PreflightError(
            'This installer cannot install without a network connection. '
            'Connect the machine to the internet and start the installer '
            'again.')

    print(f'Pre-flight checks passed (firmware: {mode}, '
          f'target: {disk}, mountpoint: {mountpoint}).')
    return mode


def unmount_all(mountpoint: Path) -> None:
    """Best-effort teardown so a failed run does not leave a half-mounted
    /mnt behind. Never raises: it runs on the error path."""
    try:
        subprocess.run(
            ['umount', '-R', str(mountpoint)],
            capture_output=True, text=True, check=False, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pass


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    # The very first thing a user sees if something is wrong is this banner,
    # so say who is running and what is available before anything else.
    print(f'OrinOs installer backend starting '
          f'(uid={os.geteuid()}, python={sys.version.split()[0]})', flush=True)

    if os.geteuid() != 0:
        print('This installer must run as root.', file=sys.stderr)
        sys.exit(1)

    plan = load_plan(Path(sys.argv[1]))
    repo_url = plan['repo_url']
    mountpoint = Path('/mnt')

    # Every destructive check runs before anything is written, so a refusal
    # leaves the machine exactly as it was.
    stage('preparing')
    try:
        firmware = preflight(plan, mountpoint)
    except PreflightError as exc:
        print(f'PREFLIGHT FAILED: {exc}', file=sys.stderr)
        sys.exit(2)

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

    try:
        _install(plan, disk_config, mirror_list_handler, mirror_config,
                 repo_url, mountpoint, firmware)
    except BaseException:
        # (BaseException so Ctrl-C mid-pacstrap is cleaned up as well.)
        # The Installer context manager already unmounts on a clean exit, but
        # a hard failure (or a KeyboardInterrupt mid-pacstrap) can leave the
        # tree mounted. Tear it down so a retry starts from a clean slate
        # instead of hitting the "target is not empty" pre-flight check.
        unmount_all(mountpoint)
        raise
    stage('done')
    print('OrinOs install finished. Check for warnings above, then reboot.')


def _install(plan, disk_config, mirror_list_handler, mirror_config,
             repo_url, mountpoint, firmware):
    """Run the installation inside the archinstall Installer context."""
    # base_packages replaces archinstall's default set, so the defaults
    # (base, sudo, linux-firmware, mkinitcpio) have to be repeated here.
    base_packages = ['base', 'sudo', 'linux-firmware', 'mkinitcpio']
    if plan.get('encryption'):
        base_packages += PRE_INITRAMFS_PACKAGES

    with Installer(
        mountpoint,
        disk_config,
        base_packages=base_packages,
        kernels=['linux'],
    ) as installation:
        installation.set_mirrors(mirror_list_handler, mirror_config)
        stage('mounting')
        installation.mount_ordered_layout()

        # A file:// [orinos] repo only exists in the live system; copy it
        # into the target (at the SAME path, because pacman.conf will say
        # file:///orinos-repo/x86_64) so the installed system keeps
        # resolving it after reboot. HTTP(S) URLs need no copy.
        if repo_url.startswith('file://'):
            src = Path(repo_url[len('file://'):])
            if src.is_dir():
                dest = installation.target / src.relative_to('/')
                shutil.copytree(src, dest, dirs_exist_ok=True)

        stage('base-system')
        installation.minimal_installation(hostname=plan['hostname'])

        # minimal_installation() leaves the target with the stock
        # pacman.conf; without this call [orinos] only exists on the live
        # system and `pacman -Syu` after reboot never sees OrinOs packages.
        installation.set_mirrors(mirror_list_handler, mirror_config,
                                 on_target=True)

        # Locale, timezone and keyboard layout as picked in the GUI.
        # archinstall's arch_chroot() does NOT run a shell (the command is
        # shlex-split), so '>', '&&', '||' and '|' would be passed to the
        # program as literal arguments. Plain files are written from Python.
        locale, timezone, keyboard = (
            plan['locale'], plan['timezone'], plan['keyboard'])
        target = installation.target

        (target / 'etc/locale.conf').write_text(f'LANG={locale}\n')
        # Keep the FONT= line archinstall wrote; only replace KEYMAP=.
        vconsole = target / 'etc/vconsole.conf'
        kept = [ln for ln in (vconsole.read_text().splitlines()
                              if vconsole.is_file() else [])
                if not ln.startswith('KEYMAP=')]
        vconsole.write_text('\n'.join([f'KEYMAP={keyboard}'] + kept) + '\n')

        localtime = target / 'etc/localtime'
        localtime.unlink(missing_ok=True)
        installation.arch_chroot(
            f'ln -s /usr/share/zoneinfo/{shlex.quote(timezone)} '
            '/etc/localtime')

        # X11/SDDM layout. /etc/default/keyboard is Debian-only; on Arch the
        # equivalent is an xorg.conf.d snippet.
        xorg_dir = target / 'etc/X11/xorg.conf.d'
        xorg_dir.mkdir(parents=True, exist_ok=True)
        (xorg_dir / '00-keyboard.conf').write_text(
            'Section "InputClass"\n'
            '    Identifier "system-keyboard"\n'
            '    MatchIsKeyboard "on"\n'
            f'    Option "XkbLayout" "{keyboard}"\n'
            'EndSection\n')

        # Writing LANG into /etc/locale.conf is not enough: the locale itself
        # only exists after locale-gen has compiled it. locale.gen lines are
        # "<name> <charset>" (not the bare name), and en_US stays available
        # as a fallback for programs that do not ship the chosen locale.
        wanted = []
        for loc in (locale, 'en_US.UTF-8'):
            charset = loc.split('.', 1)[1].split('@')[0] \
                if '.' in loc else 'UTF-8'
            line = f'{loc} {charset}'
            if line not in wanted:
                wanted.append(line)
        (target / 'etc/locale.gen').write_text('\n'.join(wanted) + '\n')
        installation.arch_chroot('locale-gen')

        # What is actually mounted at / decides how swap and the label are
        # handled; plan['root_fs'] is only a hint and can disagree with the
        # partition list.
        root_fs = findmnt_value(mountpoint, 'FSTYPE') or plan['root_fs']

        # Swap: either a swap partition (created by the GUI as a partition
        # with mountpoint None) or a swapfile sized by the plan. The file is
        # only created and listed in fstab; swapon inside the chroot is
        # pointless and the swap is enabled by fstab on first boot.
        swap_mib = int(plan.get('swap_size_mib', 0))
        if plan.get('swap') == 'swapfile' and swap_mib > 0:
            if root_fs == 'btrfs':
                # A plain dd file on btrfs is a COW file and swapon rejects
                # it; mkswapfile creates a correct NOCOW one.
                installation.arch_chroot(
                    f'btrfs filesystem mkswapfile --size {swap_mib}m '
                    '/swapfile')
            else:
                installation.arch_chroot(
                    f'dd if=/dev/zero of=/swapfile bs=1M '
                    f'count={swap_mib} status=none')
                installation.arch_chroot('chmod 600 /swapfile')
                installation.arch_chroot('mkswap /swapfile')
            with open(target / 'etc/fstab', 'a') as fstab:
                fstab.write('/swapfile none swap defaults 0 0\n')

        stage('packages')
        installation.add_additional_packages(
            BASE_PACKAGES + desktop_packages(plan['desktop']))
        installation.enable_service('NetworkManager.service')
        installation.enable_service('sddm.service')

        # Optional automatic desktop login (off by default, like every
        # mainstream distro: a password-protected session is the default).
        if plan.get('autologin'):
            sddm_dir = target / 'etc/sddm.conf.d'
            sddm_dir.mkdir(parents=True, exist_ok=True)
            (sddm_dir / '00-autologin.conf').write_text(
                '[Autologin]\n'
                f'User={plan["user"]}\n'
                'Session=plasma\n'
                'Relogin=true\n')

        # GRUB names its menu entry from GRUB_DISTRIBUTOR (not os-release);
        # set it before add_bootloader so grub-mkconfig writes "OrinOs".
        grub_default = target / 'etc/default/grub'
        if grub_default.is_file():
            text = grub_default.read_text()
            text, n = re.subn(r'(?m)^GRUB_DISTRIBUTOR=.*$',
                              'GRUB_DISTRIBUTOR="OrinOs"', text)
            if n == 0:
                text += '\nGRUB_DISTRIBUTOR="OrinOs"\n'
            grub_default.write_text(text)

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
        # usermod -c is the root-side way to set GECOS (chfn can ask for
        # authentication, and the old "2>/dev/null || true" tail was handed
        # to chfn as arguments because there is no shell here).
        installation.arch_chroot(
            f'usermod -c {shlex.quote(gecos)} {shlex.quote(username)}')

        if plan.get('root_password'):
            # Set the *root* password (the old code changed the user's), in
            # plaintext through stdin so it never appears in a command line.
            subprocess.run(
                ['arch-chroot', '-S', str(target), 'chpasswd'],
                input=f'root:{plan["root_password"]}\n', text=True,
                check=True)

        # orinos-desktop applies the OrinOs wallpaper and colour scheme from
        # a user unit, so it has to be enabled inside the user's home or the
        # account would boot into stock Breeze. Done as the user (before the
        # shell switch below) so every directory has the right owner, and
        # including default.target.wants, which the old code never created.
        unit_dir = f'/home/{username}/.config/systemd/user'
        installation.arch_chroot(
            f'runuser -u {username} -- mkdir -p {unit_dir}/default.target.wants')
        installation.arch_chroot(
            f'runuser -u {username} -- ln -sf '
            '/usr/lib/systemd/user/orinos-desktop.service '
            f'{unit_dir}/default.target.wants/orinos-desktop.service')

        # archinstall's User model has no shell field and useradd defaults
        # to bash; fish is in BASE_PACKAGES so make it the login shell.
        installation.arch_chroot(f'usermod -s /usr/bin/fish {username}')

        # orinos-branding places /etc/os-release + /etc/issue via a rule in
        # /etc/tmpfiles.d (higher precedence than Arch's /usr/lib rule, which
        # would otherwise be treated as duplicate). The explicit path applies
        # the rule immediately; at boot systemd applies it anyway.
        stage('branding')
        installation.arch_chroot(
            'systemd-tmpfiles --create /etc/tmpfiles.d/orinos-branding.conf'
        )

        # Volume label on the root filesystem so it is identifiable in a
        # file manager or parted. Done from the host against the real mount:
        # inside the chroot findmnt reports btrfs sources as /dev/x[/@] and
        # the old script needed a shell for its if/fi, which does not exist.
        label = (plan.get('disk_label') or 'orinos')
        root_dev = (findmnt_value(mountpoint, 'SOURCE') or '').split('[')[0]
        if root_dev and root_fs.startswith('ext'):
            r = run(['e2label', root_dev, label[:16]])
        elif root_dev and root_fs == 'btrfs':
            r = run(['btrfs', 'filesystem', 'label', str(mountpoint), label])
        else:
            r = None  # xfs/f2fs/... cannot be relabelled while mounted
        if r is not None and r.returncode != 0:
            print(f'WARNING: could not set volume label: {r.stderr.strip()}',
                  file=sys.stderr)

        verify_install(plan, mountpoint, firmware)


def verify_install(plan: dict, mountpoint: Path, firmware: str) -> None:
    """Check the installed system is actually bootable before declaring done.

    Runs while /mnt is still mounted, so a missing bootloader or an unusable
    initramfs is reported now rather than as a black screen after reboot.
    """
    problems = []

    def check(label: str, cmd: list):
        proc = run(cmd)
        if proc.returncode != 0:
            problems.append(f'{label}: {proc.stderr.strip() or "failed"}')

    check('kernel image', ['test', '-e', str(mountpoint / 'boot/vmlinuz-linux')])
    check('initramfs', ['test', '-e', str(mountpoint / 'boot/initramfs-linux.img')])
    check('root filesystem', ['test', '-d', str(mountpoint / 'etc')])
    check('user account', ['test', '-d',
                           str(mountpoint / f'home/{plan["user"]}')])

    boot_choice = plan.get('bootloader', 'grub')
    if boot_choice == 'grub':
        if firmware == 'uefi':
            check('GRUB EFI image',
                  ['test', '-e', str(mountpoint / 'boot/grub/x86_64-efi')])
        else:
            check('GRUB BIOS image',
                  ['test', '-e', str(mountpoint / 'boot/grub/i386-pc')])
    elif boot_choice == 'systemd-boot':
        check('systemd-boot loader',
              ['test', '-e', str(mountpoint /
                                 'boot/EFI/systemd/systemd-bootx64.efi')])

    if plan.get('encryption'):
        # The encrypt hook does `add_binary cryptsetup`; if cryptsetup was
        # missing at build time mkinitcpio exits non-zero and the initramfs
        # ships without it, which boots into an emergency shell instead of
        # asking for the LUKS password. Verify the binary is really inside.
        initramfs = mountpoint / 'boot/initramfs-linux.img'
        if initramfs.is_file():
            listing = run(['lsinitcpio', str(initramfs)])
            # lsinitcpio prints symlinks as "path -> target".
            entries = [e.split(' -> ')[0].strip().lstrip('./')
                       for e in listing.stdout.splitlines()]
            if listing.returncode != 0:
                problems.append(
                    f'initramfs unreadable: {listing.stderr.strip()}')
            elif 'usr/bin/cryptsetup' not in entries:
                problems.append(
                    'initramfs has no cryptsetup binary — an encrypted root '
                    'would boot into an emergency shell')
        else:
            problems.append('initramfs missing, cannot verify LUKS support')

    if problems:
        raise RuntimeError(
            'The installation finished but verification failed:\n  - '
            + '\n  - '.join(problems))

    print('Verification passed: kernel, initramfs, bootloader and user '
          'account are all in place.')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nInterrupted by the user.', file=sys.stderr)
        sys.exit(130)
    except Exception:
        # The traceback is the only thing that says why a run stopped, and a
        # failure with no output is indistinguishable from a success in the
        # log the user is asked to read. Print it in full and exit non-zero.
        import traceback
        traceback.print_exc()
        print('\nThe installation failed. Nothing further was attempted.',
              file=sys.stderr)
        sys.exit(1)
