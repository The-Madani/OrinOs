#!/usr/bin/env python3
"""OrinOs graphical installer frontend (PySide6).

Runs on top of the verified archinstall-library backend in
installer/install.py. The wizard is modelled on the EndeavourOS/Calamares
flow: language -> welcome -> location -> keyboard -> disk (auto erase or
manual partitioning for dual-boot) -> user -> review -> install -> done.

Manual mode shows each disk's partition table (type, size, filesystem,
mountpoint, OS label), lets the user pick existing partitions for /boot
and /, create new partitions in free space, and validates the combination
with a Verify button before continuing. Windows/other partitions are never
touched unless explicitly assigned a mountpoint.
"""

import json
import os
import re
import subprocess
import sys
import threading

from PySide6.QtCore import Qt, QTimer, QObject, Signal, QProcess
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

def _self_dir():
    # Works both from a git checkout (installer/gui/) and from the
    # installed package (/usr/lib/orinos-installer/).
    return os.path.dirname(os.path.abspath(__file__))

SELF_DIR = _self_dir()
if os.path.isfile(f'{SELF_DIR}/install.py'):
    # installed package layout (orinos-installer ships the backend next
    # to the frontend); branding comes from the orinos-branding package
    BACKEND = f'{SELF_DIR}/install.py'
    BRANDING_LOGO = '/usr/share/icons/hicolor/scalable/apps/orinos-logo.png'
else:
    # git checkout: backend and branding live in the repo tree
    REPO_ROOT = subprocess.run(
        ['git', 'rev-parse', '--show-toplevel'],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    BACKEND = f'{REPO_ROOT}/installer/install.py'
    BRANDING_LOGO = f'{REPO_ROOT}/branding/logo.png'

# Teal brand palette, kept in sync with branding/.
BRAND_TEAL = '#00b4aa'
BRAND_TEAL_DIM = '#0a7d77'
BRAND_BG = '#11161c'
BRAND_PANEL = '#1a2029'
BRAND_TEXT = '#e6edf3'

THEME = f"""
QWidget {{
    background: {BRAND_BG};
    color: {BRAND_TEXT};
    font-size: 14px;
}}
QLabel#pageTitle {{
    font-size: 26px;
    font-weight: 700;
    color: {BRAND_TEAL};
    padding-bottom: 4px;
}}
QLabel#pageSubtitle {{
    font-size: 14px;
    color: #9fb0c0;
}}
QLabel#brandMark {{
    color: {BRAND_TEAL};
    font-size: 40px;
    font-weight: 800;
}}
QPushButton {{
    background: {BRAND_PANEL};
    border: 1px solid #2b3440;
    border-radius: 8px;
    padding: 10px 18px;
    color: {BRAND_TEXT};
}}
QPushButton:hover {{
    border-color: {BRAND_TEAL};
    color: {BRAND_TEAL};
}}
QPushButton:disabled {{
    color: #5a6b7a;
    border-color: #232c36;
}}
QPushButton#primary {{
    background: {BRAND_TEAL};
    color: #06231f;
    font-weight: 700;
    border: none;
}}
QPushButton#primary:hover {{ background: #17c7bd; }}
QPushButton#primary:disabled {{ background: #2c4a49; color: #7d8f8e; }}
QPushButton#langButton {{
    font-size: 20px;
    padding: 22px;
    min-width: 190px;
}}
QPushButton#langButton:hover {{ border: 2px solid {BRAND_TEAL}; }}
QComboBox, QLineEdit, QSpinBox {{
    background: #0d1117;
    border: 1px solid #2b3440;
    border-radius: 6px;
    padding: 8px;
    color: {BRAND_TEXT};
    selection-background-color: {BRAND_TEAL_DIM};
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{
    border-color: {BRAND_TEAL};
}}
QTableWidget {{
    background: #0d1117;
    border: 1px solid #2b3440;
    border-radius: 6px;
    gridline-color: #1c242e;
}}
QHeaderView::section {{
    background: {BRAND_PANEL};
    color: {BRAND_TEAL};
    border: none;
    padding: 8px;
    font-weight: 600;
}}
QPlainTextEdit {{
    background: #0d1117;
    border: 1px solid #2b3440;
    border-radius: 6px;
    font-family: monospace;
    font-size: 12px;
}}
QProgressBar {{
    background: #0d1117;
    border: 1px solid #2b3440;
    border-radius: 8px;
    height: 22px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {BRAND_TEAL};
    border-radius: 7px;
}}
QRadioButton::indicator, QCheckBox::indicator {{
    width: 18px; height: 18px;
}}
QRadioButton::indicator:unchecked {{
    border: 2px solid #46535f; border-radius: 9px; background: #0d1117;
}}
QRadioButton::indicator:checked {{
    border: 5px solid {BRAND_TEAL}; border-radius: 9px; background: #0d1117;
}}
QCheckBox::indicator:unchecked {{
    border: 2px solid #46535f; border-radius: 4px; background: #0d1117;
}}
QCheckBox::indicator:checked {{
    background: {BRAND_TEAL}; border: 2px solid {BRAND_TEAL}; border-radius: 4px;
}}
QScrollBar:vertical {{ background: #0d1117; width: 10px; }}
QScrollBar::handle:vertical {{ background: #2b3440; border-radius: 5px; }}
QToolTip {{
    background: {BRAND_PANEL};
    color: {BRAND_TEXT};
    border: 1px solid {BRAND_TEAL};
    padding: 6px;
}}
"""

LANGUAGES = {
    'en': {
        'app_title': 'OrinOs Installer',
        'choose_lang': 'Choose your language',
        'fa': 'فارسی',
        'en': 'English',
        'next': 'Next',
        'back': 'Back',
        'cancel': 'Cancel',
        'welcome_title': 'Welcome to OrinOs',
        'welcome_hint': 'Every page already has the recommended option '
                        'selected — just press Next if you do not want to '
                        'change anything.',
        'welcome_text': (
            'This installer will set up OrinOs on your computer.\n\n'
            'OrinOs is an independent Arch-based distribution. Packages are '
            'downloaded during installation, so keep the machine connected '
            'to the internet.'
        ),
        'net_ok': 'Internet connection detected.',
        'net_missing': 'No internet connection detected. An internet '
                       'connection is required to download packages.',
        'net_missing_offline_hint': 'No internet connection detected — '
                                 'offline installation has been '
                                 'selected using the packages bundled on '
                                 'this medium.',
        'location_title': 'Location',
        'timezone': 'Time zone',
        'clock_format': 'Clock format',
        'clock_24': '24-hour',
        'clock_12': '12-hour (AM/PM)',
        'keyboard_title': 'Keyboard',
        'keyboard_layout': 'Keyboard layout',
        'disk_title': 'Installation destination',
        'disk_help': (
            '<b>Erase disk</b> — every partition on the selected disk is '
            'destroyed and OrinOs is installed fresh.<br><br>'
            '<b>Manual partitioning</b> — install OrinOs next to another '
            'operating system. Pick existing partitions for /boot and /, or '
            'create new ones in free space. Windows and other partitions are '
            'never touched unless you assign them a mountpoint yourself.'
        ),
        'auto_erase': 'Erase disk and install OrinOs',
        'manual': 'Manual partitioning (for dual-boot)',
        'device': 'Disk',
        'size': 'Size',
        'fstype': 'Filesystem',
        'mountpoint': 'Mountpoint',
        'label': 'Label / OS',
        'free_space': 'Free space',
        'create_partition': 'Create partition in free space…',
        'remove_assignment': 'Clear mountpoint',
        'verify': 'Verify layout',
        'verify_ok': 'Layout is valid — you can continue.',
        'verify_esp': 'Select a FAT32 EFI partition of at least 512 MiB for /boot.',
        'verify_root': 'Select one Linux partition (ext4/btrfs/xfs/f2fs) for /.',
        'verify_unique': 'Each partition may only be used for one mountpoint.',
        'verify_overlap': 'Created partitions must fit in the chosen free space.',
        'verify_encrypt_missing': 'Encryption is enabled but no password was set.',
        'bootloader': 'Install bootloader to:',
        'encryption': 'Encryption',
        'encrypt_none': 'No encryption',
        'encrypt_luks': 'Encrypt with LUKS (recommended for laptops)',
        'encryption_password': 'Encryption password',
        'encryption_confirm': 'Repeat encryption password',
        'encryption_hint': 'This password protects your data. It cannot be '
                           'recovered if forgotten.',
        'swap': 'Swap',
        'swap_none': 'No swap',
        'swap_file': 'Swapfile',
        'swap_partition': 'Swap partition',
        'swap_size': 'Swap size (MiB)',
        'user_title': 'Create your account',
        'username': 'Username',
        'password': 'Password',
        'password_again': 'Repeat password',
        'hostname': 'Computer name',
        'autologin': 'Log in automatically without asking for the password',
        'user_warn': 'All fields are required and passwords must match.',
        'password_mismatch': 'The two passwords do not match.',
        'password_weak': 'Password is too short (minimum 6 characters).',
        'username_invalid': 'Usernames must start with a letter and may only '
                            'contain lowercase letters, digits, - and _.',
        'user_exists': 'That username already exists on the system.',
        'root_fs': 'Root filesystem',
        'fstype_hint': 'ext4 is the safe default; btrfs adds snapshots',
        'disk_label': 'Volume label',
        'bootloader_none': 'Do not install a bootloader',
        'requirements': 'System check',
        'req_title': 'Before you continue',
        'req_ok': 'OK',
        'req_fail': 'Failed',
        'req_root': 'Administrative privileges',
        'req_internet': 'Internet connection',
        'req_disk': 'Target disk',
        'req_memory': 'Memory',
        'req_failed': 'Some checks failed. You can still continue, but '
                      'installation may fail.',
        'full_name': 'Full name',
        'full_name_hint': 'Optional — shown next to your username',
        'root_password': 'Root password',
        'root_password_again': 'Repeat root password',
        'root_password_hint': 'Optional — leave blank to disable root login',
        'install_mode': 'Installation mode',
        'mode_online': 'Online (recommended)',
        'mode_online_hint': 'Download the latest packages during install; '
                            'requires internet.',
        'mode_offline': 'Offline',
        'mode_offline_hint': 'Install only what is bundled on this medium; '
                             'works without internet but ships older '
                             'package versions.',
        'reboot_now': 'Reboot now when finished',
        'done_release': 'Show release notes after reboot',
        'password_strength': 'Password strength',
        'strength_weak': 'Weak',
        'strength_fair': 'Fair',
        'strength_good': 'Good',
        'strength_strong': 'Strong',
        'desktop_variant': 'Desktop',
        'desktop_full': 'Full desktop (recommended)',
        'desktop_full_hint': 'Complete Plasma desktop with all its '
                             'applications',
        'desktop_minimal': 'Minimal desktop',
        'desktop_minimal_hint': 'Core desktop, terminal and file manager only',
        'summary_title': 'Review and install',
        'summary_lang': 'Language',
        'summary_location': 'Location',
        'summary_keyboard': 'Keyboard',
        'summary_disk': 'Disk layout',
        'summary_user': 'Account',
        'summary_desktop': 'Desktop',
        'summary_encryption': 'Encryption',
        'summary_swap': 'Swap',
        'summary_erase': 'Erase {} completely',
        'summary_manual': 'Manual layout: {}',
        'install': 'Install now',
        'confirm_wipe': 'Erase {}?\n\nALL data on this disk will be lost. '
                        'This cannot be undone.',
        'confirm_encrypt': 'The encryption password cannot be recovered if '
                           'you forget it. Continue?',
        'confirm_dualboot': 'This is a dual-boot installation.\n\n'
                            'Partitions of other operating systems are left '
                            'untouched. Continue?',
        'stage_preparing': 'Preparing…',
        'stage_partitioning': 'Partitioning the disk…',
        'stage_offline_cache': 'Copying the offline package cache…',
        'stage_mounting': 'Mounting partitions…',
        'stage_base_system': 'Installing the base system…',
        'stage_packages': 'Downloading and installing packages…',
        'stage_bootloader': 'Installing the bootloader…',
        'stage_users': 'Creating your account…',
        'stage_branding': 'Applying OrinOs branding…',
        'progress_title': 'Installing OrinOs',
        'progress_text': 'Downloading packages and setting up your system. '
                         'This takes a while — do not power off the machine.',
        'done_title': 'Installation complete',
        'done_text': 'OrinOs has been installed on your computer.',
        'done_next': 'Remove the installation medium and press Reboot to '
                     'start your new system.',
        'release_notes': 'Show release notes after reboot',
        'reboot': 'Reboot now',
        'quit': 'Quit installer',
        'error': 'Error',
        'warning': 'Warning',
        'install_failed': 'The installation failed. Review the log above.',
        'preflight_failed': 'A safety check stopped the installation',
        'preflight_failed_hint': 'Nothing was written to the disk. The '
                                 'reason is in the log above — fix it and '
                                 'press Install again.',
        'network_title': 'Network',
        'recommended': 'recommended',
        'timezone_hint': 'Sets the system clock and your time zone',
        'keyboard_hint': 'Sets the console and desktop keyboard layout',
        'disk_hint': 'Choose where OrinOs should be installed',
        'username_hint': 'Lowercase letters, digits, - and _ only',
        'hostname_hint': 'Lowercase letters, digits and hyphens',
        'cancelled': 'Cancelled by the user',
        'stage_cancelled': 'Installation cancelled',
        'quit_confirm': 'Close the installer?',
        'yes': 'Yes',
        'no': 'No',
        'confirm_reboot': 'Reboot the machine now?',
        'none': 'None',
        'auto': 'Automatic',
    },
    'fa': {
        'app_title': 'نصاب OrinOs',
        'choose_lang': 'زبان خود را انتخاب کنید',
        'fa': 'فارسی',
        'en': 'انگلیسی',
        'next': 'بعدی',
        'back': 'قبلی',
        'cancel': 'انصراف',
        'welcome_title': 'به OrinOs خوش آمدید',
        'welcome_hint': 'در هر صفحه گزینه‌ی پیشنهادی از قبل انتخاب شده است — '
                        'اگر نمی‌خواهید چیزی را تغییر دهید، فقط «بعدی» را بزنید.',
        'welcome_text': (
            'این نصاب، OrinOs را روی رایانه شما نصب می‌کند.\n\n'
            'OrinOs یک توزیع مستقل بر پایه آرچ است. بسته‌ها هنگام نصب '
            'دانلود می‌شوند؛ پس رایانه باید به اینترنت متصل باشد.'
        ),
        'net_ok': 'اتصال اینترنت شناسایی شد.',
        'net_missing': 'اتصال اینترنت شناسایی نشد. برای دانلود بسته‌ها '
                       'اتصال اینترنت لازم است.',
        'net_missing_offline_hint': 'اتصال اینترنت شناسایی نشد — نصب '
                                 'آفلاین با بسته‌های داخل این رسانه '
                                 'انتخاب شد.',
        'location_title': 'موقعیت مکانی',
        'timezone': 'منطقه زمانی',
        'clock_format': 'قالب ساعت',
        'clock_24': '۲۴ ساعته',
        'clock_12': '۱۲ ساعته (AM/PM)',
        'keyboard_title': 'صفحه‌کلید',
        'keyboard_layout': 'چیدمان صفحه‌کلید',
        'disk_title': 'مقصد نصب',
        'disk_help': (
            '<b>پاک کردن دیسک</b> — همه پارتیشن‌های دیسک انتخابی پاک و '
            'OrinOs از نو نصب می‌شود.<br><br>'
            '<b>پارتیشن‌بندی دستی</b> — نصب OrinOs در کنار سیستم‌عامل دیگر. '
            'پارتیشن‌های موجود را برای /boot و / انتخاب کنید یا در فضای خالی '
            'پارتیشن جدید بسازید. پارتیشن‌های ویندوز یا سایر سیستم‌عامل‌ها '
            'دست‌نخورده می‌مانند مگر خودتان به آن‌ها نقطه اتصال بدهید.'
        ),
        'auto_erase': 'پاک کردن دیسک و نصب OrinOs',
        'manual': 'پارتیشن‌بندی دستی (برای دابل‌بوت)',
        'device': 'دیسک',
        'size': 'حجم',
        'fstype': 'فایل‌سیستم',
        'mountpoint': 'نقطه اتصال',
        'label': 'برچسب / سیستم‌عامل',
        'free_space': 'فضای خالی',
        'create_partition': 'ساخت پارتیشن در فضای خالی…',
        'remove_assignment': 'حذف نقطه اتصال',
        'verify': 'بررسی چیدمان',
        'verify_ok': 'چیدمان معتبر است — می‌توانید ادامه دهید.',
        'verify_esp': 'برای /boot یک پارتیشن FAT32 حداقل ۵۱۲ مگابایتی (EFI) انتخاب کنید.',
        'verify_root': 'برای / یک پارتیشن لینوکسی (ext4/btrfs/xfs/f2fs) انتخاب کنید.',
        'verify_unique': 'هر پارتیشن فقط برای یک نقطه اتصال قابل استفاده است.',
        'verify_overlap': 'پارتیشن‌های جدید باید در فضای خالی انتخاب‌شده جا شوند.',
        'verify_encrypt_missing': 'رمزنگاری فعال است اما رمز عبور تعیین نشده.',
        'bootloader': 'نصب بوت‌لودر روی:',
        'encryption': 'رمزنگاری',
        'encrypt_none': 'بدون رمزنگاری',
        'encrypt_luks': 'رمزنگاری با LUKS (برای لپ‌تاپ پیشنهاد می‌شود)',
        'encryption_password': 'رمز عبور رمزنگاری',
        'encryption_confirm': 'تکرار رمز عبور رمزنگاری',
        'encryption_hint': 'این رمز از داده‌های شما محافظت می‌کند. اگر آن را '
                           'فراموش کنید، قابل بازیابی نیست.',
        'swap': 'سوآپ',
        'swap_none': 'بدون سوآپ',
        'swap_file': 'فایل سوآپ',
        'swap_partition': 'پارتیشن سوآپ',
        'swap_size': 'حجم سوآپ (مگابایت)',
        'user_title': 'ساخت حساب کاربری',
        'username': 'نام کاربری',
        'password': 'رمز عبور',
        'password_again': 'تکرار رمز عبور',
        'hostname': 'نام رایانه',
        'autologin': 'ورود خودکار بدون درخواست رمز عبور',
        'user_warn': 'همه فیلدها لازم‌اند و رمزها باید یکسان باشند.',
        'password_mismatch': 'دو رمز عبور یکسان نیستند.',
        'password_weak': 'رمز عبور خیلی کوتاه است (حداقل ۶ کاراکتر).',
        'username_invalid': 'نام کاربری باید با حرف شروع شود و فقط شامل '
                            'حروف کوچک انگلیسی، ارقام، - و _ باشد.',
        'user_exists': 'این نام کاربری از قبل روی سیستم وجود دارد.',
        'root_fs': 'فایل‌سیستم ریشه',
        'fstype_hint': 'ext4 گزینه‌ی امن است؛ btrfs امکان اسنپ‌شات می‌دهد',
        'disk_label': 'برچسب پارتیشن',
        'bootloader_none': 'نصب نکردن بوت‌لودر',
        'requirements': 'بررسی سیستم',
        'req_title': 'پیش از ادامه',
        'req_ok': 'مناسب',
        'req_fail': 'نامناسب',
        'req_root': 'دسترسی مدیریتی',
        'req_internet': 'اتصال اینترنت',
        'req_disk': 'دیسک مقصد',
        'req_memory': 'حافظه',
        'req_failed': 'بعضی بررسی‌ها ناموفق بودند. می‌توانید ادامه دهید، '
                      'ولی نصب ممکن است با خطا مواجه شود.',
        'full_name': 'نام و نام خانوادگی',
        'full_name_hint': 'اختیاری — کنار نام کاربری نمایش داده می‌شود',
        'root_password': 'رمز عبور root',
        'root_password_again': 'تکرار رمز عبور root',
        'root_password_hint': 'اختیاری — اگر خالی بگذارید، ورود root غیرفعال می‌ماند',
        'install_mode': 'حالت نصب',
        'mode_online': 'آنلاین (پیشنهادی)',
        'mode_online_hint': 'بسته‌های روز را هنگام نصب دانلود می‌کند؛ '
                            'نیازمند اینترنت.',
        'mode_offline': 'آفلاین',
        'mode_offline_hint': 'فقط بسته‌های موجود روی این رسانه نصب '
                             'می‌شود؛ بدون اینترنت کار می‌کند ولی نسخه‌ها '
                             'قدیمی‌تری نصب می‌کند.',
        'reboot_now': 'راه‌اندازی دوباره در پایان',
        'done_release': 'نمایش یادداشت انتشار پس از راه‌اندازی',
        'password_strength': 'قدرت رمز عبور',
        'strength_weak': 'ضعیف',
        'strength_fair': 'متوسط',
        'strength_good': 'خوب',
        'strength_strong': 'قوی',
        'desktop_variant': 'میزکار',
        'desktop_full': 'میزکار کامل (پیشنهادی)',
        'desktop_full_hint': 'میزکار کامل پلاسما همراه با تمام برنامه‌ها',
        'desktop_minimal': 'میزکار مینیمال',
        'desktop_minimal_hint': 'فقط هسته دسکتاپ، ترمینال و مدیریت فایل',
        'summary_title': 'بازبینی و نصب',
        'summary_lang': 'زبان',
        'summary_location': 'موقعیت مکانی',
        'summary_keyboard': 'صفحه‌کلید',
        'summary_disk': 'چیدمان دیسک',
        'summary_user': 'حساب کاربری',
        'summary_desktop': 'میزکار',
        'summary_encryption': 'رمزنگاری',
        'summary_swap': 'سوآپ',
        'summary_erase': 'پاک کردن کامل {}',
        'summary_manual': 'چیدمان دستی: {}',
        'install': 'نصب کن',
        'confirm_wipe': 'پاک شدن {}؟\n\nتمام داده‌های این دیسک از بین '
                        'می‌رود و قابل بازگشت نیست.',
        'confirm_encrypt': 'رمز عبور رمزنگاری در صورت فراموشی قابل بازیابی '
                           'نیست. ادامه می‌دهید؟',
        'confirm_dualboot': 'این یک نصب دابل‌بوت است.\n\nپارتیشن‌های '
                            'سیستم‌عامل‌های دیگر دست‌نخورده می‌مانند. '
                            'ادامه می‌دهید؟',
        'stage_preparing': 'آماده‌سازی…',
        'stage_partitioning': 'پارتیشن‌بندی دیسک…',
        'stage_offline_cache': 'کپی کش بسته‌های آفلاین…',
        'stage_mounting': 'مانت کردن پارتیشن‌ها…',
        'stage_base_system': 'نصب سیستم پایه…',
        'stage_packages': 'دانلود و نصب بسته‌ها…',
        'stage_bootloader': 'نصب بوت‌لودر…',
        'stage_users': 'ساخت حساب کاربری…',
        'stage_branding': 'اعمال هویت OrinOs…',
        'progress_title': 'در حال نصب OrinOs',
        'progress_text': 'در حال دانلود بسته‌ها و راه‌اندازی سیستم. '
                         'کمی طول می‌کشد — رایانه را خاموش نکنید.',
        'done_title': 'نصب کامل شد',
        'done_text': 'OrinOs روی رایانه شما نصب شد.',
        'done_next': 'رسانه نصب را خارج کنید و دکمه راه‌اندازی دوباره را '
                     'برای ورود به سیستم جدید بزنید.',
        'release_notes': 'نمایش یادداشت انتشار پس از راه‌اندازی',
        'reboot': 'راه‌اندازی دوباره',
        'quit': 'خروج از نصاب',
        'error': 'خطا',
        'warning': 'هشدار',
        'install_failed': 'نصب ناموفق بود. لاگ بالا را بررسی کنید.',
        'preflight_failed': 'یک بررسی ایمنی نصب را متوقف کرد',
        'preflight_failed_hint': 'هیچ چیزی روی دیسک نوشته نشده. علتش در '
                                 'لاگ بالاست — مشکل رو حل کن و دوباره '
                                 'نصب کن.',
        'network_title': 'شبکه',
        'recommended': 'پیشنهادی',
        'timezone_hint': 'ساعت سیستم و منطقه زمانی را تنظیم می‌کند',
        'keyboard_hint': 'چیدمان صفحه‌کلید کنسول و میزکار را تنظیم می‌کند',
        'disk_hint': 'انتخاب کنید OrinOs کجا نصب شود',
        'username_hint': 'فقط حروف کوچک انگلیسی، ارقام، - و _',
        'hostname_hint': 'فقط حروف کوچک انگلیسی، ارقام و خط تیره',
        'cancelled': 'توسط کاربر لغو شد',
        'stage_cancelled': 'نصب لغو شد',
        'quit_confirm': 'نصاب بسته شود؟',
        'yes': 'بله',
        'no': 'خیر',
        'confirm_reboot': 'همین حالا سیستم راه‌اندازی دوباره شود؟',
        'none': 'هیچ‌کدام',
        'auto': 'خودکار',
    },
}

# Common time zones offered by the location page (a short, practical list;
# the backend writes the zoneinfo symlink verbatim).
TIMEZONES = [
    'UTC', 'Asia/Tehran', 'Asia/Dubai', 'Asia/Istanbul', 'Asia/Baghdad',
    'Europe/Moscow', 'Europe/Berlin', 'Europe/London', 'Europe/Paris',
    'Europe/Amsterdam', 'Europe/Rome', 'Europe/Madrid', 'Europe/Warsaw',
    'Europe/Kyiv', 'Europe/Athens', 'Europe/Stockholm', 'America/New_York',
    'America/Chicago', 'America/Denver', 'America/Los_Angeles',
    'America/Sao_Paulo', 'America/Toronto', 'America/Mexico_City',
    'Asia/Tokyo', 'Asia/Seoul', 'Asia/Shanghai', 'Asia/Kolkata',
    'Australia/Sydney', 'Pacific/Auckland',
]

KEYBOARD_LAYOUTS = [
    ('us', 'English (US)'), ('gb', 'English (UK)'), ('de', 'German'),
    ('fr', 'French'), ('es', 'Spanish'), ('it', 'Italian'),
    ('ru', 'Russian'), ('ir', 'Persian (Iran)'), ('tr', 'Turkish'),
    ('ara', 'Arabic'), ('brai', 'Brazilian Portuguese'),
    ('canda', 'Canadian French'), ('jp', 'Japanese'), ('kr', 'Korean'),
    ('cn', 'Chinese'), ('in', 'Indian'), ('nl', 'Dutch'),
    ('se', 'Swedish'), ('ch', 'Swiss'), ('pl', 'Polish'),
]

ASCII_WORDS = [
    'orinos', 'teal', 'plasma', 'kernel', 'package', 'install', 'wayland',
    'systemd', 'pacman', 'iso', 'boot', 'root', 'mount', 'swap', 'luks',
]


class PartitionRow:
    """One partition (or free-space gap) shown on the manual page."""

    def __init__(self, name, size_mib, fstype, mountpoint, label, start_mib=0):
        self.name = name
        self.size_mib = size_mib
        self.fstype = fstype
        self.mountpoint = mountpoint
        self.label = label
        self.start_mib = start_mib

    @property
    def is_free(self):
        return self.fstype == 'freespace'


def size_str(mib):
    if mib >= 10240:
        return f'{mib / 1024:.1f} GiB'
    return f'{mib} MiB'


def _lsblk_json(*args):
    proc = subprocess.run(
        ['lsblk', '--json', '--bytes', *args],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    return json.loads(proc.stdout).get('blockdevices', [])


def read_disks():
    """Return [(path, model, size_mib)] for fixed, writable disks."""
    disks = []
    for dev in _lsblk_json('-d', '-o', 'NAME,MODEL,SIZE,TYPE,RO,RM'):
        if dev.get('type') != 'disk':
            continue
        if dev.get('ro') or dev.get('rm'):
            continue  # read-only / removable media (sr0, ...)
        mib = int(dev.get('size', 0)) // 1024 // 1024
        if mib == 0:
            continue
        # zram and other pseudo-disks also report type=disk; they have no
        # backing device in /sys/block/<name>/device, real disks do.
        name = dev['name'] if dev['name'].startswith('/') \
            else f'/dev/{dev["name"]}'
        base = name.rsplit('/', 1)[-1]
        if not os.path.isdir(f'/sys/block/{base}/device'):
            continue
        disks.append((name, dev.get('model') or dev['name'], mib))
    return disks


free_starts = {}  # free-slot name -> start offset in MiB (module state)


def read_partitions(device):
    """Return [PartitionRow] for one disk, including free-space gaps.

    Parsed from a single lsblk --json call (no root needed); free gaps are
    inferred between/around partitions with 1 MiB alignment. The exact
    start offset of each gap is recorded in free_starts so created
    partitions can be placed precisely inside their gap.
    """
    free_starts.clear()
    base = device.rsplit('/', 1)[-1]
    dev = next(
        (d for d in _lsblk_json('-d', '-o', 'NAME,SIZE,TYPE')
         if d['name'].endswith(base)), None)
    if dev is None:
        return []
    disk_size_mib = int(dev.get('size', 0)) // 1024 // 1024
    children = []
    for entry in _lsblk_json('-o',
                             'NAME,SIZE,START,TYPE,FSTYPE,PARTLABEL'):
        if entry['name'].endswith(base):
            children = entry.get('children') or []
            break
    rows = []
    parts = []
    for child in children:
        if child.get('type') != 'part':
            continue
        parts.append((
            int(child.get('start', 0)) // 2048,
            int(child.get('size', 0)) // 1024 // 1024,
            child.get('fstype') or '',
            child.get('partlabel') or '',
            child['name'],
        ))
    parts.sort()
    cursor = 1  # MiB; our layouts start the first partition at 1 MiB
    for gap_index, (start_mib, size_mib, fstype, label, name) \
            in enumerate(parts):
        if start_mib - cursor > 1:
            slot = f'{device} free [{gap_index}]'
            rows.append(PartitionRow(
                slot, start_mib - cursor, 'freespace', '', LANG_FREE,
                start_mib=cursor))
            free_starts[slot] = cursor
        rows.append(PartitionRow(
            f'/dev/{name}', size_mib, fstype, '', label, start_mib=start_mib))
        cursor = start_mib + size_mib
    if disk_size_mib - cursor > 1:
        slot = f'{device} free [{len(parts)}]'
        rows.append(PartitionRow(
            slot, disk_size_mib - cursor, 'freespace', '', LANG_FREE,
            start_mib=cursor))
        free_starts[slot] = cursor
    return rows


def existing_usernames():
    """Login names already present in /etc/passwd (live system)."""
    names = set()
    try:
        with open('/etc/passwd') as fh:
            for line in fh:
                name = line.split(':', 1)[0]
                if name:
                    names.add(name)
    except OSError:
        pass
    return names


def network_online():
    """Cheap reachability probe: DNS resolve + TCP connect to a host."""
    try:
        probe = subprocess.run(
            ['timeout', '3', 'getent', 'hosts', 'archlinux.org'],
            capture_output=True, check=False)
        return probe.returncode == 0 and bool(probe.stdout.strip())
    except OSError:
        return False


def password_score(pw):
    """Very rough strength score 0..4 (length + variety)."""
    if not pw:
        return 0
    score = 0
    n = len(pw)
    if n >= 6:
        score += 1
    if n >= 10:
        score += 1
    classes = sum([
        bool(re.search(r'[a-z]', pw)),
        bool(re.search(r'[A-Z]', pw)),
        bool(re.search(r'[0-9]', pw)),
        bool(re.search(r'[^A-Za-z0-9]', pw)),
    ])
    if classes >= 2:
        score += 1
    if classes >= 3:
        score += 1
    return min(score, 4)


LANG_FREE = ''  # filled after translations load


# Ordered install stages emitted by the backend as `[orinos-stage] NAME`.
# The weights drive the progress bar so it advances realistically instead of
# crawling during the long package-download phase.
STAGES = [
    ('preparing', 2),
    ('partitioning', 8),
    ('mounting', 3),
    ('offline-cache', 4),
    ('base-system', 12),
    ('packages', 55),
    ('bootloader', 8),
    ('users', 4),
    ('branding', 3),
    ('done', 5),
]
STAGE_WEIGHTS = dict(STAGES)
STAGE_TOTAL = sum(weight for _, weight in STAGES)


class InstallWorker(QObject):
    """Runs the backend in a worker thread so the UI stays responsive.

    Emits: log(str), stage(str), finished(int)  (exit code), failed(str).
    """

    log = Signal(str)
    stage = Signal(str)
    finished = Signal(int)

    def __init__(self, cmd, parent=None):
        super().__init__(parent)
        self.cmd = cmd
        self.proc = None

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self.proc = subprocess.Popen(
                self.cmd, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1)
            assert self.proc.stdout is not None
            for line in self.proc.stdout:
                line = line.rstrip()
                if line.startswith('[orinos-stage]'):
                    self.stage.emit(line.split(']', 1)[1].strip())
                else:
                    self.log.emit(line)
            self.finished.emit(self.proc.wait())
        except Exception as exc:                       # noqa: BLE001
            self.log.emit(f'launch failed: {exc}')
            self.finished.emit(1)

    def cancel(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


class DiskMap(QWidget):
    """Proportional colour map of a disk's partitions and free gaps.

    Each block's width is its share of the disk, coloured by filesystem so
    the layout is readable at a glance (green=Linux, amber=EFI/FAT, blue=
    NTFS/other, dark=free space). Clicking a block selects that row in the
    partition table.
    """

    COLORS = {
        'vfat': '#d9a441',
        'fat32': '#d9a441',
        'ntfs': '#3f7fbf',
        'exfat': '#3f7fbf',
        'ext4': '#3fa46a',
        'btrfs': '#3fa46a',
        'xfs': '#3fa46a',
        'f2fs': '#3fa46a',
        'freespace': '#252c36',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.setMouseTracking(True)

    def set_rows(self, rows):
        self.rows = list(rows)
        self.update()

    def paintEvent(self, event):                     # noqa: N802
        from PySide6.QtGui import QPainter, QColor, QFont
        if not self.rows:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        total = sum(r.size_mib for r in self.rows) or 1
        x = 0.0
        width = self.width()
        height = self.height()
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        for row in self.rows:
            w = max(2.0, width * row.size_mib / total)
            color = QColor(self.COLORS.get(row.fstype, '#5a6673'))
            if row.fstype == 'freespace':
                color = QColor('#1c232d')
            painter.fillRect(int(x), 0, int(w), height, color)
            painter.setPen(QColor('#11161c'))
            painter.drawRect(int(x), 0, int(w), height)
            # Label only when the block is wide enough to read it.
            if w > 54:
                painter.setPen(QColor('#0b1016'))
                label = row.fstype if row.fstype != 'freespace' else 'free'
                painter.drawText(int(x) + 4, height - 9, label)
                painter.setPen(QColor('#cfd8e3'))
                painter.drawText(int(x) + 4, 14, row.name.rsplit('/', 1)[-1])
            x += w
        painter.end()

    def mousePressEvent(self, event):                # noqa: N802
        if not self.rows:
            return
        total = sum(r.size_mib for r in self.rows) or 1
        x = 0.0
        for idx, row in enumerate(self.rows):
            w = max(2.0, self.width() * row.size_mib / total)
            if x <= event.position().x() < x + w:
                table = self.parent().parent().findChild(
                    QTableWidget) if self.parent() else None
                if table is not None:
                    table.setCurrentCell(idx, 0)
                    table.scrollToItem(table.item(idx, 0))
                return
            x += w


class Wizard(QWidget):
    def __init__(self):
        super().__init__()
        self.lang = 'en'
        self.t = LANGUAGES['en']
        self.disk_mode = 'auto'
        self.desktop_variant = 'full'
        self.selected_device = None
        self.manual_assignments = {}   # partition name -> mountpoint
        self.created_partitions = []   # dicts for new partitions
        self.bootloader_target = None
        self.install_ok = False
        self.timezone = 'UTC'
        self.keyboard = 'us'
        self.clock_24h = True
        self.encrypt = False
        self.encrypt_password = ''
        self.swap_mode = 'swapfile'
        self.swap_size_mib = 0
        self.autologin = False
        self.install_mode = 'online'
        self.net_online = False
        self.full_name = ''
        self.root_password = ''
        self.worker = None
        self._plan_file = None
        self.stack = QStackedWidget()
        self.pages = {}
        self.page_titles = {}
        self._back_buttons = {}
        self._build()
        # Back-button visibility depends on which page is on screen, so it
        # has to follow every page change, not just explicit Back clicks.
        self.stack.currentChanged.connect(
            lambda _idx: self._sync_back_buttons())
        # The stack holds every wizard page; without a top-level layout the
        # window renders empty (the stack is never attached to the widget).
        window_layout = QVBoxLayout(self)
        window_layout.setContentsMargins(0, 0, 0, 0)
        window_layout.addWidget(self.stack)
        self.setWindowTitle(self.t['app_title'])
        if BRANDING_LOGO:
            self.setWindowIcon(QIcon(BRANDING_LOGO))
        self.setStyleSheet(THEME)
        self.resize(1000, 700)
        self.setMinimumSize(900, 640)

    # ---------- shared chrome ----------
    def _rebuild(self):
        """Rebuild every page so its widgets pick up the current language.

        Qt caches the text passed at construction time, so switching language
        cannot be done by mutating widgets. Recreate the whole stack and
        restore the user's position/answers; the install is not running yet
        at that point, so nothing is lost.
        """
        was_lang = self.pages.get('lang') is not None and \
            self.stack.currentWidget() is self.pages.get('lang')
        index = self.stack.currentIndex()
        # User answers that live in widgets are copied out before the pages
        # (and their widgets) are destroyed.
        state = self._capture_state()
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        self.pages.clear()
        self.page_titles.clear()
        self._back_buttons.clear()
        self._build()
        self._restore_state(state, index, was_lang)

    def _capture_state(self):
        """Snapshot the wizard's answers so a rebuild does not lose them."""
        st = {
            'disk_mode': self.disk_mode,
            'desktop_variant': self.desktop_variant,
            'selected_device': self.selected_device,
            'manual_assignments': dict(self.manual_assignments),
            'created_partitions': list(self.created_partitions),
            'install_mode': self.install_mode,
            'timezone': self.timezone,
            'clock_24h': self.clock_24h,
            'keyboard': self.keyboard,
            'encrypt': self.encrypt,
            'encrypt_password': self.encrypt_password,
            'swap_mode': self.swap_mode,
            'swap_size_mib': self.swap_size_mib,
            'autologin': self.autologin,
            'full_name': self.full_name,
            'root_password': self.root_password,
            'install_ok': self.install_ok,
        }
        # Widgets that exist only once the pages have been built.
        for attr, key in (('username_edit', 'user'), ('password_edit', 'pw'),
                          ('password2_edit', 'pw2'),
                          ('fullname_edit', 'fullname'),
                          ('hostname_edit', 'hostname'),
                          ('rootpass_edit', 'rootpw'),
                          ('rootpass2_edit', 'rootpw2'),
                          ('label_edit', 'label')):
            edit = getattr(self, attr, None)
            if edit is not None:
                st[key] = edit.text()
        return st

    def _restore_state(self, st, index, was_lang):
        """Push a captured state back into the freshly built widgets."""
        self.disk_mode = st['disk_mode']
        self.desktop_variant = st['desktop_variant']
        self.manual_assignments = st['manual_assignments']
        self.created_partitions = st['created_partitions']
        self.install_mode = st['install_mode']
        self.timezone = st['timezone']
        self.clock_24h = st['clock_24h']
        self.keyboard = st['keyboard']
        self.encrypt = st['encrypt']
        self.encrypt_password = st['encrypt_password']
        self.swap_mode = st['swap_mode']
        self.swap_size_mib = st['swap_size_mib']
        self.autologin = st['autologin']
        self.full_name = st['full_name']
        self.root_password = st['root_password']
        self.install_ok = st['install_ok']

        if st.get('selected_device') and self.device_combo.count():
            idx = self.device_combo.findData(st['selected_device'])
            self.device_combo.setCurrentIndex(max(0, idx))

        self.rb_mode_online.setChecked(st['install_mode'] == 'online')
        self.rb_mode_offline.setChecked(st['install_mode'] == 'offline')

        if self.tz_combo.findText(self.timezone) >= 0:
            self.tz_combo.setCurrentIndex(self.tz_combo.findText(self.timezone))
        self.rb_clock_24.setChecked(self.clock_24h)
        self.rb_clock_12.setChecked(not self.clock_24h)

        if self.kb_combo.findData(self.keyboard) >= 0:
            self.kb_combo.setCurrentIndex(self.kb_combo.findData(self.keyboard))

        self.rb_auto.setChecked(self.disk_mode == 'auto')
        self.rb_manual.setChecked(self.disk_mode == 'manual')
        self.rb_enc_none.setChecked(not self.encrypt)
        self.rb_enc_luks.setChecked(self.encrypt)
        if self.encrypt:
            self.enc_pass.setText(self.encrypt_password)
            self.enc_pass2.setText(self.encrypt_password)
        self.rb_swap_none.setChecked(self.swap_mode == 'none')
        self.rb_swap_part.setChecked(self.swap_mode == 'partition')
        self.rb_swap_file.setChecked(self.swap_mode == 'swapfile')
        self.swap_spin.setValue(self.swap_size_mib or 8192)

        self.rb_desktop_full.setChecked(self.desktop_variant == 'full')
        self.rb_desktop_minimal.setChecked(self.desktop_variant == 'minimal')
        self.autologin_check.setChecked(self.autologin)

        for attr, key in (('username_edit', 'user'), ('password_edit', 'pw'),
                          ('password2_edit', 'pw2'),
                          ('fullname_edit', 'fullname'),
                          ('hostname_edit', 'hostname'),
                          ('rootpass_edit', 'rootpw'),
                          ('rootpass2_edit', 'rootpw2'),
                          ('label_edit', 'label')):
            if key in st and getattr(self, attr, None) is not None:
                getattr(self, attr).setText(st[key])

        self.refresh_disk_page()
        self._probe_network()
        self._sync_assignment_column()
        self.stack.setCurrentIndex(0 if was_lang else max(1, index))

    def _page(self, key, title, subtitle='', scroll=False):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(34, 26, 34, 26)
        heading = QLabel(title)
        heading.setObjectName('pageTitle')
        outer.addWidget(heading)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName('pageSubtitle')
            sub.setWordWrap(True)
            outer.addWidget(sub)
        outer.addSpacing(14)
        body = QVBoxLayout()
        if scroll:
            # Pages with many controls (disk, user) must stay usable on
            # small screens — put the body inside a scroll area.
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QScrollArea.NoFrame)
            holder = QWidget()
            holder.setLayout(body)
            area.setWidget(holder)
            outer.addWidget(area, stretch=1)
        else:
            outer.addLayout(body, stretch=1)
        self.pages[key] = page
        self.page_titles[key] = heading
        self.stack.addWidget(page)
        return body

    def _retranslate(self):
        """Re-apply titles/text after the language changed.

        Widget text is set once at construction, so this covers only what
        exists before the first _rebuild(); after that the pages are rebuilt
        from scratch and already carry the right language.
        """
        self.setWindowTitle(self.t['app_title'])
        for key, heading in self.page_titles.items():
            mapping = {
                'lang': self.t['choose_lang'],
                'welcome': self.t['welcome_title'],
                'location': self.t['location_title'],
                'keyboard': self.t['keyboard_title'],
                'disk': self.t['disk_title'],
                'user': self.t['user_title'],
                'summary': self.t['summary_title'],
                'progress': self.t['progress_title'],
                'done': self.t['done_title'],
            }
            if key in mapping:
                heading.setText(mapping[key])

    def _nav_row(self, page_key, on_next, next_text=None):
        layout = self.pages[page_key].layout()
        layout.addStretch()
        row = QHBoxLayout()
        back = QPushButton(self.t['back'])
        back.clicked.connect(self.go_back)
        self._remember_back(page_key, back)
        nxt = QPushButton(next_text or self.t['next'])
        nxt.setObjectName('primary')
        nxt.setMinimumWidth(120)
        nxt.setDefault(True)
        nxt.clicked.connect(on_next)
        row.addWidget(back)
        row.addStretch()
        row.addWidget(nxt)
        self.pages[page_key].findChildren(QPushButton)
        layout.addLayout(row)
        setattr(self, f'_next_{page_key}', nxt)
        setattr(self, f'_back_{page_key}', back)

    def go_back(self):
        # Page 0 (language) is the floor: going further back would leave the
        # wizard with no way forward. Going back to it is allowed so the user
        # can change their mind about the language.
        self.stack.setCurrentIndex(max(0, self.stack.currentIndex() - 1))
        self._sync_back_buttons()

    def _sync_back_buttons(self):
        """Only the page on screen shows a Back button, and never on page 1.

        On the welcome page "Back" would land on the language chooser, which
        is the one step where changing your mind costs nothing; keeping the
        button there only invites the user into a dead end.
        """
        current = self.stack.currentWidget()
        for key, btn in self._back_buttons.items():
            btn.setVisible(current is self.pages.get(key)
                           and key != 'welcome')

    def _remember_back(self, key, btn):
        """Track a Back button so _sync_back_buttons can find it again."""
        self._back_buttons[key] = btn
        return btn

    # ---------- page 0: language ----------
    def _build(self):
        layout = self._page('lang', self.t['choose_lang'])
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(spacer)
        if BRANDING_LOGO and os.path.isfile(BRANDING_LOGO):
            logo = QLabel()
            logo.setPixmap(QPixmap(BRANDING_LOGO).scaledToHeight(150))
            logo.setAlignment(Qt.AlignCenter)
            layout.addWidget(logo)
        mark = QLabel('OrinOs')
        mark.setObjectName('brandMark')
        mark.setAlignment(Qt.AlignCenter)
        layout.addWidget(mark)
        row = QHBoxLayout()
        row.addStretch()
        for code in ('fa', 'en'):
            btn = QPushButton(LANGUAGES[code][code])
            btn.setObjectName('langButton')
            btn.clicked.connect(lambda _, c=code: self.pick_language(c))
            row.addWidget(btn)
        row.addStretch()
        layout.addSpacing(10)
        layout.addLayout(row)
        layout.addStretch()

        self._build_welcome()
        self._build_location()
        self._build_keyboard()
        self._build_disk()
        self._build_user()
        self._build_summary()
        self._build_progress()
        self._build_done()
        # Defaults so a lazy user can reach "Install" by clicking Next only.
        self._apply_recommended_defaults()
        self._mark_recommended_options()
        self.stack.setCurrentIndex(0)

    def _mark_recommended_options(self):
        """Tag the option the documentation recommends on every choice.

        Skips labels that already carry a tag: several option strings are
        written with '(recommended)' baked in, which would otherwise end up
        tagged twice.
        """
        tag = self.t['recommended'].lower()
        for btn in (self.rb_auto, self.rb_desktop_full, self.rb_swap_file,
                    self.rb_enc_none):
            if tag not in btn.text().lower():
                self._tag_recommended(btn, on=btn is not self.rb_enc_none)
        # ext4 and GRUB are the recommended choices inside their combos.
        for combo, data in ((self.fs_combo, 'ext4'),
                            (self.bootloader_combo, 'grub')):
            idx = combo.findData(data)
            if idx >= 0:
                combo.setItemText(
                    idx, f"{combo.itemText(idx)} ({self.t['recommended']})")

    def _apply_recommended_defaults(self):
        """Preset every choice the way the docs recommend."""
        self.rb_mode_online.setChecked(True)
        self.tz_combo.setCurrentIndex(
            max(0, self.tz_combo.findText(self.timezone)))
        self.kb_combo.setCurrentIndex(
            max(0, self.kb_combo.findData(self.keyboard)))
        self.device_combo.setCurrentIndex(0)
        self.fs_combo.setCurrentIndex(0)          # ext4
        self.label_edit.setText('orinos')
        self.bootloader_combo.setCurrentIndex(0)  # GRUB
        self.swap_spin.setValue(8192)
        self.hostname_edit.setText('orinos')
        self.rb_desktop_full.setChecked(True)
        self.rb_auto.setChecked(True)
        self.rb_enc_none.setChecked(True)
        self.rb_swap_file.setChecked(True)
        if self.device_combo.count():
            self.refresh_disk_page()

    def pick_language(self, code):
        # Rebuilding the pages is the only way Qt re-reads the strings: the
        # language is picked before any answer exists, so nothing is lost.
        self.lang = code
        self.t = LANGUAGES[code]
        QApplication.setLayoutDirection(
            Qt.RightToLeft if code == 'fa' else Qt.LeftToRight
        )
        self._rebuild()
        self.stack.setCurrentIndex(1)

    def _tag_recommended(self, button, on=True):
        """Append the localized 'recommended' tag to an option's label."""
        base = button.property('baseText') or button.text()
        button.setProperty('baseText', base)
        suffix = f"  ({self.t['recommended']})" if on else ''
        button.setText(f'{base}{suffix}')

    # ---------- page 1: welcome ----------
    def _build_welcome(self):
        layout = self._page('welcome', self.t['welcome_title'],
                            subtitle=self.t['welcome_hint'])
        text = QLabel(self.t['welcome_text'])
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addSpacing(10)

        # Installation mode (EndeavourOS-style online/offline choice).
        self.mode_group = QButtonGroup(self)
        self.rb_mode_online = QRadioButton(self.t['mode_online'])
        self.rb_mode_online.setToolTip(self.t['mode_online_hint'])
        self.rb_mode_online.setChecked(True)
        self.rb_mode_offline = QRadioButton(self.t['mode_offline'])
        self.rb_mode_offline.setToolTip(self.t['mode_offline_hint'])
        self.mode_group.addButton(self.rb_mode_online)
        self.mode_group.addButton(self.rb_mode_offline)
        layout.addWidget(QLabel(self.t['install_mode'] + ':'))
        layout.addWidget(self.rb_mode_online)
        layout.addWidget(self.rb_mode_offline)

        layout.addSpacing(10)
        # Requirements checklist.
        self.req_table = QTableWidget(4, 2)
        self.req_table.setHorizontalHeaderLabels(
            [self.t['requirements'], ''])
        self.req_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.req_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.req_table.setMaximumHeight(160)
        layout.addWidget(self.req_table)
        self.net_label = QLabel('')
        self.net_label.setWordWrap(True)
        layout.addWidget(self.net_label)

        self._nav_row('welcome', self.show_location)
        QTimer.singleShot(150, self._probe_network)

    def _req_row(self, index, name, ok):
        item = QTableWidgetItem(name)
        val = QTableWidgetItem(self.t['req_ok'] if ok else self.t['req_fail'])
        val.setForeground(Qt.GlobalColor.green if ok else Qt.GlobalColor.red)
        self.req_table.setItem(index, 0, item)
        self.req_table.setItem(index, 1, val)

    def _probe_network(self):
        ok = network_online()
        self.net_online = ok
        self.net_label.setText(self.t['net_ok'] if ok else self.t['net_missing'])
        self.net_label.setStyleSheet(
            f'color: {BRAND_TEAL};' if ok else 'color: #e0a33e;')
        # Offline mode needs no internet; online mode warns but allows.
        self.rb_mode_online.setEnabled(True)
        if not ok:
            # Preselect offline: online would fail on the first download, so
            # leaving it selected would send the user into a failure they have
            # to diagnose rather than one they can simply avoid.
            self.rb_mode_offline.setChecked(True)
            self.rb_mode_online.setChecked(False)
            self.net_label.setText(self.t['net_missing_offline_hint'])

        mem_mib = 0
        try:
            with open('/proc/meminfo') as fh:
                for line in fh:
                    if line.startswith('MemTotal:'):
                        mem_mib = int(line.split()[1]) // 1024
                        break
        except OSError:
            pass
        disks = read_disks()
        self._req_row(0, self.t['req_root'], os.geteuid() == 0)
        self._req_row(1, self.t['req_internet'], ok)
        self._req_row(2, self.t['req_disk'], bool(disks))
        self._req_row(3, f"{self.t['req_memory']} ({mem_mib} MiB)",
                      mem_mib >= 1024)

    def show_location(self):
        self.install_mode = 'online' if self.rb_mode_online.isChecked() \
            else 'offline'
        self.stack.setCurrentIndex(2)

    # ---------- page 2: location ----------
    def _build_location(self):
        layout = self._page('location', self.t['location_title'])
        form = QFormLayout()
        self.tz_combo = QComboBox()
        self.tz_combo.addItems(TIMEZONES)
        form.addRow(self.t['timezone'], self.tz_combo)
        self.clock_group = QButtonGroup(self)
        clock_row = QHBoxLayout()
        self.rb_clock_24 = QRadioButton(self.t['clock_24'])
        self.rb_clock_12 = QRadioButton(self.t['clock_12'])
        self.rb_clock_24.setChecked(True)
        self.clock_group.addButton(self.rb_clock_24)
        self.clock_group.addButton(self.rb_clock_12)
        clock_row.addWidget(self.rb_clock_24)
        clock_row.addWidget(self.rb_clock_12)
        clock_row.addStretch()
        holder = QWidget()
        holder.setLayout(clock_row)
        form.addRow(self.t['clock_format'], holder)
        layout.addLayout(form)
        self._nav_row('location', self.show_keyboard)

    def show_keyboard(self):
        self.timezone = self.tz_combo.currentText()
        self.clock_24h = self.rb_clock_24.isChecked()
        self.stack.setCurrentIndex(3)

    # ---------- page 3: keyboard ----------
    def _build_keyboard(self):
        layout = self._page('keyboard', self.t['keyboard_title'])
        form = QFormLayout()
        self.kb_combo = QComboBox()
        for code, label in KEYBOARD_LAYOUTS:
            self.kb_combo.addItem(label, code)
        form.addRow(self.t['keyboard_layout'], self.kb_combo)
        layout.addLayout(form)
        self._nav_row('keyboard', self.show_disk)

    def show_disk(self):
        self.keyboard = self.kb_combo.currentData()
        self.show_disk_page()

    # ---------- page 4: disk ----------
    def _build_disk(self):
        layout = self._page('disk', self.t['disk_title'], scroll=True)
        help_text = QLabel(self.t['disk_help'])
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        layout.addSpacing(6)

        self.disk_mode_group = QButtonGroup(self)
        self.rb_auto = QRadioButton(self.t['auto_erase'])
        self.rb_manual = QRadioButton(self.t['manual'])
        self.disk_mode_group.addButton(self.rb_auto)
        self.disk_mode_group.addButton(self.rb_manual)
        self.rb_auto.setChecked(True)
        layout.addWidget(self.rb_auto)
        layout.addWidget(self.rb_manual)
        layout.addSpacing(6)

        device_row = QHBoxLayout()
        device_row.addWidget(QLabel(self.t['device'] + ':'))
        self.device_combo = QComboBox()
        for path, model, mib in read_disks():
            self.device_combo.addItem(f'{path} — {model} ({size_str(mib)})')
        device_row.addWidget(self.device_combo, stretch=1)
        layout.addLayout(device_row)

        # Visual map of the disk: one coloured block per partition/gap.
        self.disk_map = DiskMap(self)
        self.disk_map.setFixedHeight(46)
        self.disk_map.setVisible(False)
        layout.addWidget(self.disk_map)

        # manual partition table
        self.partition_table = QTableWidget(0, 5)
        self.partition_table.setHorizontalHeaderLabels(
            [self.t['device'], self.t['size'], self.t['fstype'],
             self.t['mountpoint'], self.t['label']])
        self.partition_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.partition_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.partition_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.partition_table.setMinimumHeight(180)
        layout.addWidget(self.partition_table, stretch=1)

        manual_row = QHBoxLayout()
        for label, slot in (
            ('/boot', lambda: self.assign_mountpoint('/boot')),
            ('/', lambda: self.assign_mountpoint('/')),
            (None, self.clear_assignment),
            (None, self.create_partition),
        ):
            if label:
                b = QPushButton(label)
            elif slot == self.clear_assignment:
                b = QPushButton(self.t['remove_assignment'])
            else:
                b = QPushButton(self.t['create_partition'])
            b.clicked.connect(slot)
            manual_row.addWidget(b)
        manual_row.addStretch()
        self.verify_btn = QPushButton(self.t['verify'])
        self.verify_btn.setObjectName('primary')
        self.verify_btn.clicked.connect(self.verify_layout)
        manual_row.addWidget(self.verify_btn)
        layout.addLayout(manual_row)

        self.disk_status = QLabel('')
        self.disk_status.setWordWrap(True)
        layout.addWidget(self.disk_status)

        # encryption
        self.encrypt_group = QButtonGroup(self)
        self.rb_enc_none = QRadioButton(self.t['encrypt_none'])
        self.rb_enc_luks = QRadioButton(self.t['encrypt_luks'])
        self.rb_enc_none.setChecked(True)
        self.encrypt_group.addButton(self.rb_enc_none)
        self.encrypt_group.addButton(self.rb_enc_luks)
        enc_box = QWidget()
        enc_lay = QVBoxLayout(enc_box)
        enc_lay.setContentsMargins(0, 0, 0, 0)
        enc_lay.addWidget(self.rb_enc_none)
        enc_lay.addWidget(self.rb_enc_luks)
        self.enc_fields = QWidget()
        encf = QFormLayout(self.enc_fields)
        encf.setContentsMargins(28, 0, 0, 0)
        self.enc_pass = QLineEdit()
        self.enc_pass.setEchoMode(QLineEdit.Password)
        self.enc_pass2 = QLineEdit()
        self.enc_pass2.setEchoMode(QLineEdit.Password)
        encf.addRow(self.t['encryption_password'], self.enc_pass)
        encf.addRow(self.t['encryption_confirm'], self.enc_pass2)
        hint = QLabel(self.t['encryption_hint'])
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#9fb0c0;')
        encf.addRow(hint)
        self.enc_fields.setVisible(False)
        self.rb_enc_luks.toggled.connect(self.enc_fields.setVisible)
        enc_lay.addWidget(self.enc_fields)
        layout.addWidget(enc_box)

        # swap
        swap_row = QHBoxLayout()
        self.swap_group = QButtonGroup(self)
        self.rb_swap_none = QRadioButton(self.t['swap_none'])
        self.rb_swap_file = QRadioButton(self.t['swap_file'])
        self.rb_swap_part = QRadioButton(self.t['swap_partition'])
        self.rb_swap_file.setChecked(True)
        for b in (self.rb_swap_none, self.rb_swap_file, self.rb_swap_part):
            self.swap_group.addButton(b)
            swap_row.addWidget(b)
        self.swap_spin = QSpinBox()
        self.swap_spin.setRange(0, 65536)
        self.swap_spin.setSingleStep(512)
        self.swap_spin.setValue(8192)
        self.swap_spin.setSuffix(' MiB')
        swap_row.addSpacing(10)
        swap_row.addWidget(QLabel(self.t['swap_size']))
        swap_row.addWidget(self.swap_spin)
        swap_row.addStretch()
        layout.addLayout(swap_row)

        # Root filesystem type and volume label (erase mode).
        opts_row = QHBoxLayout()
        opts_row.addWidget(QLabel(self.t['root_fs'] + ':'))
        self.fs_combo = QComboBox()
        for fs in ('ext4', 'btrfs', 'xfs'):
            self.fs_combo.addItem(fs, fs)
        self.fs_combo.setToolTip(self.t['fstype_hint'])
        opts_row.addWidget(self.fs_combo)
        opts_row.addSpacing(16)
        opts_row.addWidget(QLabel(self.t['disk_label'] + ':'))
        self.label_edit = QLineEdit('orinos')
        self.label_edit.setMaximumWidth(190)
        opts_row.addWidget(self.label_edit)
        opts_row.addStretch()
        layout.addLayout(opts_row)

        boot_row = QHBoxLayout()
        boot_row.addWidget(QLabel(self.t['bootloader']))
        self.bootloader_combo = QComboBox()
        self.bootloader_combo.addItem('GRUB', 'grub')
        self.bootloader_combo.addItem('systemd-boot', 'systemd-boot')
        self.bootloader_combo.addItem('rEFInd', 'refind')
        self.bootloader_combo.addItem(self.t['bootloader_none'], 'none')
        boot_row.addWidget(self.bootloader_combo, stretch=1)
        layout.addLayout(boot_row)

        self.rb_auto.toggled.connect(self.refresh_disk_page)
        self.rb_manual.toggled.connect(self.refresh_disk_page)
        self.device_combo.currentIndexChanged.connect(self.refresh_disk_page)
        self._nav_row('disk', self.validate_disk)

    def show_disk_page(self):
        self.refresh_disk_page()
        self.stack.setCurrentIndex(4)

    def show_user_page(self):
        self.stack.setCurrentIndex(5)

    def refresh_disk_page(self):
        self.disk_mode = 'auto' if self.rb_auto.isChecked() else 'manual'
        cur = self.device_combo.currentText().split(' ')[0]
        self.selected_device = cur or None
        is_manual = self.disk_mode == 'manual'
        self.partition_table.setVisible(is_manual)
        self.disk_map.setVisible(is_manual)
        for b in (self.rb_enc_none, self.rb_enc_luks, self.enc_fields,
                  self.rb_swap_none, self.rb_swap_file, self.rb_swap_part,
                  self.swap_spin, self.verify_btn):
            b.setVisible(True)
        if is_manual:
            rows = read_partitions(self.selected_device)
            self.partition_table.setRowCount(len(rows))
            for i, row in enumerate(rows):
                values = (
                    row.name, size_str(row.size_mib), row.fstype,
                    row.mountpoint or '', row.label or '',
                )
                for j, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if row.is_free:
                        item.setForeground(Qt.GlobalColor.gray)
                    item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                    self.partition_table.setItem(i, j, item)
            self.disk_map.set_rows(rows)
        else:
            self.partition_table.setRowCount(0)
            self.disk_map.set_rows([])

    def _selected_row(self):
        idx = self.partition_table.currentRow()
        if idx < 0:
            return None
        return self.partition_table.item(idx, 0).text()

    def assign_mountpoint(self, mountpoint):
        name = self._selected_row()
        if not name or name.endswith(')'):
            return
        for other, mp in self.manual_assignments.items():
            if other != name and mp == mountpoint:
                self.disk_status.setText(self.t['verify_unique'])
                return
        self.manual_assignments[name] = mountpoint
        self._sync_assignment_column()

    def clear_assignment(self):
        name = self._selected_row()
        if name in self.manual_assignments:
            del self.manual_assignments[name]
        self._sync_assignment_column(clear=True)

    def _sync_assignment_column(self, clear=False):
        for name, mountpoint in self.manual_assignments.items():
            for i in range(self.partition_table.rowCount()):
                if self.partition_table.item(i, 0).text() == name:
                    self.partition_table.item(i, 3).setText(mountpoint)
        if clear:
            for i in range(self.partition_table.rowCount()):
                if self.partition_table.item(i, 0).text() == name:
                    self.partition_table.item(i, 3).setText('')

    def create_partition(self):
        name = self._selected_row()
        if not name or not name.endswith(')'):
            return
        row = next(
            (r for r in read_partitions(self.selected_device)
             if r.name == name), None)
        if row is None:
            return
        dlg = NewPartitionDialog(self, row, self.t)
        if dlg.exec() == QDialog.Accepted:
            size, fstype, mountpoint = dlg.result
            self.created_partitions.append({
                'free_slot': name,
                'size_mib': size,
                'fstype': fstype,
                'mountpoint': mountpoint,
            })
            self.refresh_disk_page()

    def verify_layout(self):
        boot = [n for n, m in self.manual_assignments.items() if m == '/boot']
        root = [n for n, m in self.manual_assignments.items() if m == '/']
        if len(set(self.manual_assignments)) != len(self.manual_assignments):
            self.disk_status.setText(self.t['verify_unique'])
            return False
        rows = read_partitions(self.selected_device)
        fstype_of = {r.name: r.fstype for r in rows}
        if len(boot) != 1 or fstype_of.get(boot[0], '') not in ('vfat', 'fat32'):
            self.disk_status.setText(self.t['verify_esp'])
            return False
        if len(root) != 1 or fstype_of.get(root[0], '') not in (
                'ext4', 'btrfs', 'xfs', 'f2fs'):
            self.disk_status.setText(self.t['verify_root'])
            return False
        if self.created_partitions:
            used = sum(p['size_mib'] for p in self.created_partitions)
            free = sum(r.size_mib for r in rows if r.is_free)
            if used > free:
                self.disk_status.setText(self.t['verify_overlap'])
                return False
        self.disk_status.setText(self.t['verify_ok'])
        self.disk_status.setStyleSheet(f'color: {BRAND_TEAL};')
        return True

    def validate_disk(self):
        if not self.selected_device:
            return
        if self.disk_mode == 'auto':
            if not self._confirm(
                self.t['confirm_wipe'].format(self.selected_device)
            ):
                return
        else:
            if not self.verify_layout():
                self.disk_status.setStyleSheet('color: #e0a33e;')
                return
        # encryption password sanity
        if self.rb_enc_luks.isChecked():
            if self.enc_pass.text() != self.enc_pass2.text() or not self.enc_pass.text():
                self.disk_status.setText(self.t['verify_encrypt_missing'])
                self.disk_status.setStyleSheet('color: #e0a33e;')
                return
            if not self._confirm(self.t['confirm_encrypt']):
                return
        self.encrypt = self.rb_enc_luks.isChecked()
        self.encrypt_password = self.enc_pass.text() if self.encrypt else ''
        if self.rb_swap_none.isChecked():
            self.swap_mode = 'none'
            self.swap_size_mib = 0
        elif self.rb_swap_part.isChecked():
            self.swap_mode = 'partition'
        else:
            self.swap_mode = 'swapfile'
            self.swap_size_mib = self.swap_spin.value()
        self.bootloader_target = self.bootloader_combo.currentText()
        self.stack.setCurrentIndex(5)

    def _confirm(self, message):
        box = QMessageBox(self)
        box.setWindowTitle(self.t['warning'] if hasattr(self, 't') else '')
        box.setTextFormat(Qt.RichText)
        box.setText(message)
        yes = box.addButton(self.t['install'], QMessageBox.AcceptRole)
        box.addButton(self.t['cancel'], QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    # ---------- page 5: user ----------
    def _build_user(self):
        layout = self._page('user', self.t['user_title'], scroll=True)
        form = QFormLayout()
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText('yourname')
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password2_edit = QLineEdit()
        self.password2_edit.setEchoMode(QLineEdit.Password)
        self.hostname_edit = QLineEdit('orinos')
        self.fullname_edit = QLineEdit()
        self.rootpass_edit = QLineEdit()
        self.rootpass_edit.setEchoMode(QLineEdit.Password)
        self.rootpass2_edit = QLineEdit()
        self.rootpass2_edit.setEchoMode(QLineEdit.Password)
        form.addRow(self.t['full_name'], self.fullname_edit)
        form.addRow(self.t['username'], self.username_edit)
        form.addRow(self.t['password'], self.password_edit)
        form.addRow(self.t['password_again'], self.password2_edit)
        form.addRow(self.t['hostname'], self.hostname_edit)
        form.addRow(self.t['root_password'], self.rootpass_edit)
        form.addRow(self.t['root_password_again'], self.rootpass2_edit)
        layout.addLayout(form)

        # live password strength meter
        self.strength_label = QLabel(self.t['password_strength'] + ': —')
        self.strength_bar = QProgressBar()
        self.strength_bar.setRange(0, 4)
        self.strength_bar.setValue(0)
        self.strength_bar.setTextVisible(False)
        self.strength_bar.setFixedHeight(10)
        self.password_edit.textChanged.connect(self._update_strength)
        self.strength_row = QVBoxLayout()
        self.strength_row.addWidget(self.strength_label)
        self.strength_row.addWidget(self.strength_bar)
        strength_holder = QWidget()
        strength_holder.setLayout(self.strength_row)
        layout.addWidget(strength_holder)

        # desktop variant
        self.desktop_group = QButtonGroup(self)
        self.rb_desktop_full = QRadioButton(self.t['desktop_full'])
        self.rb_desktop_full.setToolTip(self.t['desktop_full_hint'])
        self.rb_desktop_full.setChecked(True)
        self.rb_desktop_minimal = QRadioButton(self.t['desktop_minimal'])
        self.rb_desktop_minimal.setToolTip(self.t['desktop_minimal_hint'])
        self.desktop_group.addButton(self.rb_desktop_full)
        self.desktop_group.addButton(self.rb_desktop_minimal)
        layout.addSpacing(6)
        layout.addWidget(QLabel(self.t['desktop_variant'] + ':'))
        layout.addWidget(self.rb_desktop_full)
        layout.addWidget(self.rb_desktop_minimal)
        layout.addSpacing(6)

        self.autologin_check = QCheckBox(self.t['autologin'])
        layout.addWidget(self.autologin_check)

        self.user_status = QLabel('')
        self.user_status.setWordWrap(True)
        layout.addWidget(self.user_status)
        self._nav_row('user', self.validate_user)

    def _update_strength(self, text):
        score = password_score(text)
        self.strength_bar.setValue(score)
        labels = ['—', self.t['strength_weak'], self.t['strength_fair'],
                  self.t['strength_good'], self.t['strength_strong']]
        colors = ['#5a6b7a', '#e05f5f', '#e0a33e', '#8fd14f', BRAND_TEAL]
        self.strength_label.setText(f"{self.t['password_strength']}: "
                                    f"{labels[score]}")
        self.strength_bar.setStyleSheet(
            f'QProgressBar::chunk {{ background: {colors[score]}; }}')

    def validate_user(self):
        user = self.username_edit.text().strip()
        pw = self.password_edit.text()
        if not (user and pw and self.hostname_edit.text().strip()):
            self.user_status.setText(self.t['user_warn'])
            return
        if not re.match(r'^[a-z][a-z0-9_-]*$', user):
            self.user_status.setText(self.t['username_invalid'])
            return
        if user in existing_usernames():
            self.user_status.setText(self.t['user_exists'])
            return
        if pw != self.password2_edit.text():
            self.user_status.setText(self.t['password_mismatch'])
            return
        if len(pw) < 6:
            self.user_status.setText(self.t['password_weak'])
            return
        rootpw = self.rootpass_edit.text()
        if rootpw and rootpw != self.rootpass2_edit.text():
            self.user_status.setText(self.t['password_mismatch'])
            return
        if rootpw and len(rootpw) < 6:
            self.user_status.setText(self.t['password_weak'])
            return
        self.desktop_variant = ('full' if self.rb_desktop_full.isChecked()
                                else 'minimal')
        self.autologin = self.autologin_check.isChecked()
        self.full_name = self.fullname_edit.text().strip()
        self.root_password = rootpw
        self.build_summary()
        self.stack.setCurrentIndex(6)

    # ---------- page 6: summary ----------
    def _build_summary(self):
        layout = self._page('summary', self.t['summary_title'])
        self.summary_label = QLabel('')
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextFormat(Qt.RichText)
        layout.addWidget(self.summary_label)
        row = QHBoxLayout()
        back = QPushButton(self.t['back'])
        back.clicked.connect(self.go_back)
        self._remember_back('summary', back)
        install_btn = QPushButton(self.t['install'])
        install_btn.setObjectName('primary')
        install_btn.setMinimumWidth(160)
        install_btn.clicked.connect(self.start_install)
        row.addWidget(back)
        row.addStretch()
        row.addWidget(install_btn)
        layout.addLayout(row)

    def build_summary(self):
        def line(label, value):
            return (f'<p style="margin:4px 0"><b style="color:{BRAND_TEAL}">'
                    f'{label}:</b> {value}</p>')
        parts = [
            line(self.t['summary_lang'],
                 'English' if self.lang == 'en' else 'فارسی'),
            line(self.t['install_mode'],
                 self.t['mode_online'] if self.install_mode == 'online'
                 else self.t['mode_offline']),
            line(self.t['summary_location'], f'{self.timezone} · '
                 + (self.t['clock_24'] if self.clock_24h else self.t['clock_12'])),
            line(self.t['summary_keyboard'], self.keyboard),
            line(self.t['bootloader'],
                 self.bootloader_combo.currentText()
                 or self.t['bootloader_none']),
            line(f"{self.t['root_fs']} / {self.t['disk_label']}",
                 f"{self.fs_combo.currentData()} · "
                 f"{self.label_edit.text().strip() or 'orinos'}"),
        ]
        if self.disk_mode == 'auto':
            parts.append(line(
                self.t['summary_disk'],
                self.t['summary_erase'].format(self.selected_device)))
        else:
            detail = ', '.join(
                f'{mp} → {name}'
                for name, mp in self.manual_assignments.items())
            if self.created_partitions:
                detail += ' + ' + ', '.join(
                    f"{p['mountpoint']} ({p['fstype']}, "
                    f"{size_str(p['size_mib'])})"
                    for p in self.created_partitions)
            parts.append(line(self.t['summary_disk'],
                              self.t['summary_manual'].format(detail)))
        parts.append(line(
            self.t['summary_encryption'],
            self.t['encrypt_luks'] if self.encrypt else self.t['encrypt_none']))
        if self.swap_mode == 'none':
            parts.append(line(self.t['summary_swap'], self.t['swap_none']))
        elif self.swap_mode == 'partition':
            parts.append(line(self.t['summary_swap'], self.t['swap_partition']))
        else:
            parts.append(line(self.t['summary_swap'],
                              f"{self.t['swap_file']} — "
                              f"{size_str(self.swap_size_mib)}"))
        parts.append(line(
            self.t['summary_desktop'],
            self.t['desktop_full'] if self.rb_desktop_full.isChecked()
            else self.t['desktop_minimal']))
        parts.append(line(
            self.t['summary_user'],
            f"{self.username_edit.text()} @ "
            f"{self.hostname_edit.text().strip()}"
            + (f" · {self.fullname_edit.text().strip()}"
               if self.fullname_edit.text().strip() else '')))
        self.summary_label.setText(''.join(parts))

    # ---------- page 7: progress ----------
    def _build_progress(self):
        layout = self._page('progress', self.t['progress_title'])
        text = QLabel(self.t['progress_text'])
        text.setWordWrap(True)
        layout.addWidget(text)

        # Current stage + real percentage driven by backend stage markers.
        self.stage_label = QLabel('')
        self.stage_label.setStyleSheet(
            f'color: {BRAND_TEAL}; font-size: 16px; font-weight: 600;')
        layout.addWidget(self.stage_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat('%p%')
        layout.addWidget(self.progress_bar)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        layout.addWidget(self.log_view, stretch=1)

        row = QHBoxLayout()
        row.addStretch()
        self.cancel_btn = QPushButton(self.t['cancel'])
        self.cancel_btn.clicked.connect(self.cancel_install)
        row.addWidget(self.cancel_btn)
        layout.addLayout(row)

    def build_plan(self):
        """Serialize the wizard state into the backend's plan-JSON."""
        partitions = []
        if self.disk_mode == 'auto':
            partitions = [
                {'kind': 'create', 'start_mib': 1, 'size_mib': 512,
                 'fs': 'fat32', 'mountpoint': '/boot'},
                {'kind': 'create', 'start_mib': 513, 'size_mib': 0,
                 'fs': self.fs_combo.currentData(), 'mountpoint': '/'},
            ]
            if self.swap_mode == 'partition':
                partitions.append(
                    {'kind': 'create', 'start_mib': 0, 'size_mib': 0,
                     'fs': 'linuxswap', 'mountpoint': None})
        else:
            starts = {p['free_slot']: free_starts.get(p['free_slot'], 1)
                      for p in self.created_partitions}
            read_partitions(self.selected_device)  # refresh free_starts
            for part in self.created_partitions:
                start = free_starts.get(part['free_slot'], 1)
                partitions.append({
                    'kind': 'create',
                    'start_mib': start,
                    'size_mib': (0 if part['size_mib'] is None
                                 else part['size_mib']),
                    'fs': part['fstype'],
                    'mountpoint': part['mountpoint'],
                })
            for name, mountpoint in self.manual_assignments.items():
                partitions.append({
                    'kind': 'existing',
                    'dev': name,
                    'mountpoint': mountpoint,
                })
        plan = {
            'disk': self.selected_device,
            'wipe': self.disk_mode == 'auto',
            'partitions': partitions,
            'desktop': ('full' if self.rb_desktop_full.isChecked()
                        else 'minimal'),
            'user': self.username_edit.text().strip(),
            'password': self.password_edit.text(),
            'hostname': self.hostname_edit.text().strip(),
            'timezone': self.timezone,
            'keyboard': self.keyboard,
            'locale': ('fa_IR.UTF-8' if self.lang == 'fa' else 'en_US.UTF-8'),
            'autologin': self.autologin,
            'swap': self.swap_mode,
            'swap_size_mib': self.swap_size_mib,
            'install_mode': self.install_mode,
            'root_fs': self.fs_combo.currentData(),
            'disk_label': self.label_edit.text().strip() or 'orinos',
            'bootloader': self.bootloader_combo.currentData(),
        }
        if self.full_name:
            plan['full_name'] = self.full_name
        if self.root_password:
            plan['root_password'] = self.root_password
        if self.encrypt:
            plan['encryption'] = {'password': self.encrypt_password}
        repo_url = os.environ.get('ORINOS_REPO_URL') \
            or ('file:///orinos-repo/x86_64'
                if os.path.isdir('/orinos-repo/x86_64')
                else 'http://192.168.122.1:8000/os/x86_64')
        plan['repo_url'] = repo_url
        return plan

    def start_install(self):
        self.stack.setCurrentIndex(7)
        self.progress_bar.setValue(0)
        self.stage_label.setText('')
        self.cancel_btn.setEnabled(True)
        plan = self.build_plan()
        plan_file = f'{os.environ.get("TMPDIR", "/tmp")}/orinos-plan.json'
        with open(plan_file, 'w') as fh:
            json.dump(plan, fh)
        os.chmod(plan_file, 0o600)
        self._plan_file = plan_file
        cmd = [sys.executable, BACKEND, plan_file]
        if os.geteuid() != 0:
            cmd = ['sudo', '--'] + cmd
        self.log_view.appendPlainText('$ ' + ' '.join(cmd[:-1]) + ' <plan>')
        self.log_view.appendPlainText(
            f"Layout: {'erase ' if plan['wipe'] else 'dual-boot on '}"
            f"{plan['disk']}, desktop={plan['desktop']}")

        self.worker = InstallWorker(cmd, self)
        self.worker.log.connect(self.log_view.appendPlainText)
        self.worker.stage.connect(self._on_stage)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_stage(self, name):
        # Advance the bar by the cumulative weight of finished stages so the
        # percentage tracks real work instead of animating arbitrarily.
        done = 0
        for stage_name, weight in STAGES:
            if stage_name == name:
                break
            done += weight
        pct = min(100, int(done * 100 / STAGE_TOTAL))
        self.progress_bar.setValue(max(self.progress_bar.value(), pct))
        self.stage_label.setText(
            f"{self.t.get('stage_' + name.replace('-', '_'), name)}"
            if name != 'done' else self.t['done_title'])

    def cancel_install(self):
        if not self._confirm(self.t['cancel'] + '?'):
            return
        if getattr(self, 'worker', None):
            self.worker.cancel()
            self.log_view.appendPlainText('cancelled by user')

    def _on_finished(self, code):
        self.install_ok = code == 0
        self.cancel_btn.setEnabled(False)
        if self.install_ok:
            self.progress_bar.setValue(100)
            self.stage_label.setText(self.t['done_title'])
        try:
            os.unlink(self._plan_file)
        except (OSError, AttributeError):
            pass
        if code == 2:
            # Backend refused before writing anything (exit code 2 = a
            # pre-flight safety check). Nothing was changed, so going back to
            # the disk page is safe and is what the user has to do.
            self.stage_label.setText(self.t['preflight_failed'])
            self.log_view.appendPlainText(self.t['preflight_failed_hint'])
            self.stack.setCurrentIndex(4)
            self.refresh_disk_page()
            return
        if code < 0:
            self.stage_label.setText(self.t['stage_cancelled'])
            self.log_view.appendPlainText(self.t['cancelled'])
            self.stack.setCurrentIndex(8)
            return
        if not self.install_ok:
            self.log_view.appendPlainText(self.t['install_failed'])
        self.stack.setCurrentIndex(8)

    # ---------- page 8: done ----------
    def _build_done(self):
        layout = self._page('done', self.t['done_title'])
        text = QLabel(self.t['done_text'])
        text.setWordWrap(True)
        layout.addWidget(text)
        hint = QLabel(self.t['done_next'])
        hint.setWordWrap(True)
        hint.setStyleSheet(f'color: {BRAND_TEAL};')
        layout.addWidget(hint)
        self.release_check = QCheckBox(self.t['release_notes'])
        self.release_check.setChecked(True)
        layout.addWidget(self.release_check)
        self.reboot_check = QCheckBox(self.t['reboot_now'])
        self.reboot_check.setChecked(False)
        layout.addWidget(self.reboot_check)
        row = QHBoxLayout()
        quit_btn = QPushButton(self.t['quit'])
        quit_btn.clicked.connect(QApplication.quit)
        reboot = QPushButton(self.t['reboot'])
        reboot.setObjectName('primary')
        reboot.setMinimumWidth(160)
        reboot.clicked.connect(self.reboot_now)
        row.addWidget(quit_btn)
        row.addStretch()
        row.addWidget(reboot)
        layout.addLayout(row)

    def reboot_now(self):
        # Finished page offers an explicit confirm (the checkbox is the
        # opt-in signal; the dialog guards against accidental clicks).
        if self._confirm(self.t['reboot'] + '?'):
            subprocess.Popen(['reboot'], start_new_session=True)


class NewPartitionDialog(QDialog):
    """Ask size/filesystem/mountpoint for a partition inside free space."""

    def __init__(self, parent, free_row, t):
        super().__init__(parent)
        self.t = t
        self.result = None
        self.setWindowTitle(t['create_partition'])
        form = QFormLayout(self)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(1, max(1, free_row.size_mib))
        self.size_spin.setValue(free_row.size_mib)
        self.size_spin.setSuffix(' MiB')
        form.addRow(t['free_space'] + f' ({size_str(free_row.size_mib)})',
                    self.size_spin)
        self.fs_combo = QComboBox()
        for fs in ('ext4', 'btrfs', 'xfs', 'f2fs', 'fat32'):
            self.fs_combo.addItem(fs, fs)
        form.addRow(t['fstype'], self.fs_combo)
        self.mp_combo = QComboBox()
        self.mp_combo.addItems(['/', '/boot', '/home', ''])
        form.addRow(t['mountpoint'], self.mp_combo)
        row = QHBoxLayout()
        ok = QPushButton(self.t['next'])
        ok.setObjectName('primary')
        ok.clicked.connect(self.accept_dialog)
        cancel = QPushButton(self.t['cancel'])
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        form.addRow(row)

    def accept_dialog(self):
        mountpoint = self.mp_combo.currentText()
        self.result = (
            self.size_spin.value(),
            self.fs_combo.currentData(),
            mountpoint or None,
        )
        self.accept()


def main():
    app = QApplication(sys.argv)
    wizard = Wizard()
    wizard.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
