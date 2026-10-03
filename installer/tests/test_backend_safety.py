"""Backend checks that need neither a disk nor a network.

Run with:  python3 installer/tests/test_backend_safety.py

archinstall is stubbed out so the module imports on a build host that has no
installer environment. This exercises the safety layer: pre-flight checks,
package ordering and the encrypted-root wiring.
"""
import importlib.util
import subprocess
import sys
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / 'install.py'
failures = []


def check(label, condition, detail=''):
    print(f'{"PASS" if condition else "FAIL"}  {label}'
          + (f'   {detail}' if detail and not condition else ''))
    if not condition:
        failures.append(label)


def stub_archinstall():
    names = [
        'archinstall', 'archinstall.lib', 'archinstall.lib.disk',
        'archinstall.lib.disk.device_handler',
        'archinstall.lib.disk.filesystem', 'archinstall.lib.installer',
        'archinstall.lib.mirror', 'archinstall.lib.mirror.mirror_handler',
        'archinstall.lib.models', 'archinstall.lib.models.device',
        'archinstall.lib.models.mirrors', 'archinstall.lib.models.users',
        'archinstall.lib.models.bootloader',
    ]
    for name in names:
        sys.modules.setdefault(name, types.ModuleType(name))

    def mk(module, *attrs):
        mod = sys.modules[module]
        for attr in attrs:
            setattr(mod, attr, type(attr, (), {}))
        return mod

    mk('archinstall.lib.disk.device_handler', 'device_handler')
    mk('archinstall.lib.disk.filesystem', 'FilesystemHandler')
    mk('archinstall.lib.installer', 'Installer')
    mk('archinstall.lib.mirror.mirror_handler', 'MirrorListHandler')
    mk('archinstall.lib.models.device', 'DeviceModification',
       'DiskEncryption', 'DiskLayoutConfiguration', 'DiskLayoutType',
       'EncryptionType', 'FilesystemType', 'ModificationStatus',
       'PartitionFlag', 'PartitionModification', 'PartitionType', 'Size',
       'Unit')
    mk('archinstall.lib.models.mirrors', 'CustomRepository',
       'MirrorConfiguration', 'SignCheck', 'SignOption')
    mk('archinstall.lib.models.users', 'Password', 'User')
    mk('archinstall.lib.models.bootloader', 'Bootloader')


stub_archinstall()
spec = importlib.util.spec_from_file_location('orinos_backend', BACKEND)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)

# --- the safety layer exists ------------------------------------------------
for fn in ('preflight', 'verify_install', 'unmount_all', 'check_not_busy',
           'check_target_empty', 'check_boot_mode', 'check_encryption_support'):
    check(f'{fn}() defined', callable(getattr(backend, fn, None)))
check('PreflightError defined', issubclass(backend.PreflightError, RuntimeError))

# --- load_plan rejects incomplete plans -------------------------------------
import json  # noqa: E402
import tempfile  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / 'plan.json'

    missing = {'disk': '/dev/vda', 'wipe': True, 'partitions': [],
               'user': 'a', 'password': 'b', 'hostname': 'c'}
    path.write_text(json.dumps(missing))
    try:
        backend.load_plan(path)
        check('load_plan rejects a plan without repo_url', False)
    except ValueError as exc:
        check('load_plan rejects a plan without repo_url',
              'repo_url' in str(exc), str(exc))

    good = dict(missing, repo_url='file:///orinos-repo/x86_64')
    path.write_text(json.dumps(good))
    plan = backend.load_plan(path)
    check('load_plan fills in defaults', plan['desktop'] == 'full'
          and plan['bootloader'] == 'grub', str(plan))

    path.write_text(json.dumps(dict(good, desktop='kde')))
    try:
        backend.load_plan(path)
        check('load_plan rejects an unknown desktop variant', False)
    except ValueError:
        check('load_plan rejects an unknown desktop variant', True)

# --- encrypted-root ordering ------------------------------------------------
check('cryptsetup is a pre-initramfs package',
      'cryptsetup' in backend.PRE_INITRAMFS_PACKAGES,
      str(backend.PRE_INITRAMFS_PACKAGES))
check('cryptsetup is not in BASE_PACKAGES',
      'cryptsetup' not in backend.BASE_PACKAGES)

src = BACKEND.read_text()
installer_call = src[src.index('with Installer('):src.index(') as installation:')]
check('Installer receives base_packages', 'base_packages=' in installer_call)
check('base_packages repeats archinstall defaults',
      all(p in installer_call or p in src for p in
          ('base', 'sudo', 'linux-firmware', 'mkinitcpio')))
check('no redundant mkinitcpio -P call', 'mkinitcpio -P' not in src)
check('verify_install inspects the initramfs with lsinitcpio',
      'lsinitcpio' in src)

# --- every package we ask for must actually exist ---------------------------
# A typo here is invisible until an install dies deep in pacman, which is why
# it is checked here instead. Our own packages are exempt: they come from the
# [orinos] repository, not from Arch.
wanted = list(backend.BASE_PACKAGES) + list(backend.PRE_INITRAMFS_PACKAGES)
for variant in backend.DESKTOP_PACKAGES:
    wanted += backend.DESKTOP_PACKAGES[variant]

unknown = []
for name in sorted(set(wanted)):
    if name.startswith('orinos-'):
        continue
    info = subprocess.run(['pacman', '-Si', name],
                          capture_output=True, text=True)
    if info.returncode != 0:
        group = subprocess.run(['pacman', '-Spg', name],
                               capture_output=True, text=True)
        if group.returncode != 0 or not group.stdout.strip():
            unknown.append(name)

check('every package the installer requests exists', not unknown,
      f'do not exist in any repository: {unknown}')

print()
if failures:
    print(f'{len(failures)} FAILED: {failures}')
    sys.exit(1)
print('ALL BACKEND SAFETY CHECKS PASS')