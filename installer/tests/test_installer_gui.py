"""Headless checks for the installer frontend.

Run with:  QT_QPA_PLATFORM=offscreen python3 installer/tests/test_installer_gui.py

Covers the behaviours that regressed before: the language switch rebuilding
every page, the Back button contract, and the recommended-option defaults.
"""
import importlib.util
import os
import re
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

GUI = Path(__file__).resolve().parent.parent / 'gui' / 'orinos_installer.py'
spec = importlib.util.spec_from_file_location('orinos_gui', GUI)
oi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oi)

from PySide6.QtWidgets import (QApplication, QLabel, QPushButton,  # noqa: E402
                               QRadioButton, QCheckBox)

app = QApplication([])
failures = []


def check(label, condition, detail=''):
    print(f'{"PASS" if condition else "FAIL"}  {label}'
          + (f'   {detail}' if detail and not condition else ''))
    if not condition:
        failures.append(label)


def page_texts(page):
    out = []
    for cls in (QLabel, QPushButton, QRadioButton, QCheckBox):
        out += [w.text() for w in page.findChildren(cls) if w.text()]
    return out


# --- translation parity -----------------------------------------------------
en, fa = set(oi.LANGUAGES['en']), set(oi.LANGUAGES['fa'])
check('EN/FA key parity', en == fa,
      f'en-only={sorted(en - fa)} fa-only={sorted(fa - en)}')
print(f'      ({len(en)} keys)')

# --- Persian really is Persian ---------------------------------------------
wizard = oi.Wizard()
wizard.pick_language('fa')
pages = ['welcome', 'location', 'keyboard', 'disk', 'user',
         'summary', 'progress', 'done']
labels = [t for key in pages for t in page_texts(wizard.pages[key])]
allowed = {'OrinOs', 'ext4', 'btrfs', 'xfs', 'f2fs', 'fat32', 'GRUB',
           'systemd-boot', 'rEFInd', '/boot', '/', '/home', 'MiB', 'UTC'}
untranslated = [t for t in labels
                if t.strip() and t not in allowed and not re.search(r'[؀-ۿ]', t)]
check('no English text after switching to Persian', not untranslated,
      f'{len(untranslated)} untranslated: {untranslated[:5]}')
print(f'      ({len(labels)} labels checked)')

# --- Back button contract ---------------------------------------------------
wizard.show()
app.processEvents()
wizard.pick_language('fa')
app.processEvents()


def visible_back():
    return [k for k, b in wizard._back_buttons.items() if b.isVisible()]


wizard.show_location()
app.processEvents()
check('location page shows its own Back', visible_back() == ['location'],
      str(visible_back()))
wizard.show_disk_page()
app.processEvents()
check('disk page shows its own Back', visible_back() == ['disk'],
      str(visible_back()))
for _ in range(5):
    wizard.go_back()
    app.processEvents()
check('Back walks all the way to the language page',
      wizard.stack.currentIndex() == 0, f'stopped at {wizard.stack.currentIndex()}')
check('welcome page has no Back button', visible_back() == [],
      str(visible_back()))

# --- recommended defaults survive a language switch -------------------------
wizard2 = oi.Wizard()

# The install mode follows connectivity, not the language switch, and a test
# host usually has no network — so it is excluded from the comparison and
# checked separately below.
DEFAULTS = ('fs', 'boot', 'swap', 'label', 'hostname',
            'auto_disk', 'no_enc', 'swapfile')


def defaults(w):
    return {
        'fs': w.fs_combo.currentData(),
        'boot': w.bootloader_combo.currentData(),
        'swap': w.swap_spin.value(),
        'label': w.label_edit.text(),
        'hostname': w.hostname_edit.text(),
        'auto_disk': w.rb_auto.isChecked(),
        'no_enc': w.rb_enc_none.isChecked(),
        'swapfile': w.rb_swap_file.isChecked(),
    }


before = defaults(wizard2)
wizard2.pick_language('fa')
after = defaults(wizard2)
check('recommended defaults survive a language switch', before == after,
      f'{before} != {after}')
check('root filesystem default is ext4', after['fs'] == 'ext4', str(after['fs']))
check('bootloader default is GRUB', after['boot'] == 'grub', str(after['boot']))

# --- connectivity gates the install -----------------------------------------
# Packages are downloaded during the install, so there is nothing to install
# without a network. Rather than letting the user walk into a failure on the
# disk page, the Next button is blocked and the reason is shown.
oi.network_online = lambda: False
wizard3 = oi.Wizard()
wizard3._probe_network()
check('no internet blocks the install',
      not wizard3._next_welcome.isEnabled(),
      'Next must be disabled when the probe fails')
check('no internet explains why',
      wizard3.net_label.text() == wizard3.t['net_missing_blocked'],
      repr(wizard3.net_label.text()))
check('the internet check is reported as failed',
      wizard3.req_table.item(1, 1).text() == wizard3.t['req_fail'],
      'the requirements table must show the internet check failing')

oi.network_online = lambda: True
wizard4 = oi.Wizard()
wizard4._probe_network()
check('with internet the install is allowed',
      wizard4._next_welcome.isEnabled(),
      'Next must be enabled when the probe succeeds')
check('with internet the check passes',
      wizard4.req_table.item(1, 1).text() == wizard4.t['req_ok'],
      'the requirements table must show the internet check passing')

# Both desktop variants stay selectable: there is no offline mode to
# constrain them any more.
check('the full desktop is selectable',
      wizard4.rb_desktop_full.isEnabled(),
      'the full desktop must not be restricted')
check('the full desktop is the default',
      wizard4.rb_desktop_full.isChecked(),
      'full desktop should be preselected as the recommended option')

# --- the plan must not carry a display string ------------------------------
wizard2._confirm = lambda msg: True
for key, label in (('welcome', 'بعدی'), ('location', 'بعدی'),
                   ('keyboard', 'بعدی'), ('disk', 'بعدی')):
    for b in wizard2.pages[key].findChildren(QPushButton):
        if b.text() == label:
            b.click()
            break
wizard2.username_edit.setText('amir')
wizard2.password_edit.setText('orinos123')
wizard2.password2_edit.setText('orinos123')
for b in wizard2.pages['user'].findChildren(QPushButton):
    if b.text() == 'بعدی':
        b.click()
        break
plan = wizard2.build_plan()
check('plan root_fs is a bare filesystem name',
      plan['root_fs'] in ('ext4', 'btrfs', 'xfs'), repr(plan['root_fs']))
check('plan bootloader is a bare id',
      plan['bootloader'] in ('grub', 'systemd-boot', 'refind', 'none'),
      repr(plan['bootloader']))

print()
if failures:
    print(f'{len(failures)} FAILED: {failures}')
    sys.exit(1)
print('ALL GUI CHECKS PASS')
