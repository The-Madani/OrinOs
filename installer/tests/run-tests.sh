#!/usr/bin/env bash
# Run the installer test suite. No disk, no network and no root required.
#
#   ./installer/tests/run-tests.sh
set -euo pipefail

TESTS_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "== backend safety =="
python3 "${TESTS_DIR}/test_backend_safety.py"

echo
echo "== arch_chroot shell usage =="
python3 "${TESTS_DIR}/test_chroot_calls.py"

echo
echo "== frontend =="
QT_QPA_PLATFORM=offscreen python3 "${TESTS_DIR}/test_installer_gui.py"

echo
echo "== ISO profile =="
python3 "${TESTS_DIR}/test_iso_profile.py"

echo
echo "== branding =="
python3 "${TESTS_DIR}/test_branding.py"

echo
echo "All installer tests passed."