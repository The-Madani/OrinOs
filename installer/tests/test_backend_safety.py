"""Backend checks that need neither a disk nor a network.

Run with:  python3 installer/tests/test_backend_safety.py

archinstall is stubbed out so the module imports on a build host that has no
installer environment. This exercises the safety layer: pre-flight checks,
package ordering and the encrypted-root wiring.
"""
import importlib.util
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

# --- offline install --------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    cache = Path(tmp) / 'cache'
    cache.mkdir()
    (cache / 'base-3-3-any.pkg.tar.zst').write_bytes(b'')
    (cache / 'linux-7.2.7.arch1-1-x86_64.pkg.tar.zst').write_bytes(b'')
    original = backend.OFFLINE_CACHE
    backend.OFFLINE_CACHE = cache
    try:
        path = Path(tmp) / 'plan.json'
        path.write_text(json.dumps(dict(good, install_mode='online')))
        backend.load_plan(path)
        check('an online plan loads without a cache', True)

        path.write_text(json.dumps(dict(good, install_mode='offline')))
        try:
            backend.load_plan(path)
            check('an offline plan loads when the cache exists', True)
        except ValueError as exc:
            check('an offline plan loads when the cache exists', False, str(exc))

        path.write_text(json.dumps(dict(good, install_mode='carrier-pigeon')))
        try:
            backend.load_plan(path)
            check('an unknown install mode is rejected', False)
        except ValueError:
            check('an unknown install mode is rejected', True)

        # An empty cache must be refused, not discovered halfway through pacman.
        empty = Path(tmp) / 'empty'
        empty.mkdir()
        backend.OFFLINE_CACHE = empty
        path.write_text(json.dumps(dict(good, install_mode='offline')))
        try:
            backend.load_plan(path)
            check('an offline plan without packages is rejected', False)
        except ValueError:
            check('an offline plan without packages is rejected', True)
    finally:
        backend.OFFLINE_CACHE = original

check('install_offline_cache() is defined',
      callable(getattr(backend, 'install_offline_cache', None)))
check('check_offline_cache() is defined',
      callable(getattr(backend, 'check_offline_cache', None)))

# --- a plan that claims offline must not install silently online -----------
print()
if failures:
    print(f'{len(failures)} FAILED: {failures}')
    sys.exit(1)
print('ALL BACKEND SAFETY CHECKS PASS')