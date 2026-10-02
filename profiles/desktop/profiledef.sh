#!/usr/bin/env bash
# shellcheck disable=SC2034

iso_name="orinos-desktop"
iso_label="ORINOS_D_$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m)"
iso_publisher="OrinOs <https://github.com/The-Madani/OrinOs>"
iso_application="OrinOs desktop live/ installation medium"
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
  ["/etc/sudoers.d/orinos-live"]="0:0:440"
  # mkarchiso does not preserve exec bits when copying airootfs; scripts
  # must be listed here or systemd can't spawn them (status=203/EXEC).
  ["/usr/local/bin/refresh-orinos-repo"]="0:0:755"
  ["/usr/local/bin/refresh-orinos-cache"]="0:0:755"
  ["/usr/local/bin/orinos-trust-desktop"]="0:0:755"
)
