#!/usr/bin/env bash
# shellcheck disable=SC2034

iso_name="orinos"
iso_label="ORINOS_$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m)"
iso_publisher="OrinOs <https://github.com/The-Madani/OrinOs>"
iso_application="OrinOs live/ installation medium"
iso_version="$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y.%m.%d)"
install_dir="orinos"
buildmodes=('iso')
bootmodes=('bios.syslinux'
           'uefi.grub')
pacman_conf="pacman.conf"
airootfs_image_type="erofs"
airootfs_image_tool_options=('-zlzma,109' -E 'ztailpacking')
file_permissions=(
  ["/etc/shadow"]="0:0:400"
)
