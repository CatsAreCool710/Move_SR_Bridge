#!/bin/bash
# uninstall_mac.sh - Remove Move_SR_Bridge from Ableton Live on macOS
# Copyright (C) 2026 Jeremiah Ticket
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# Removes Move_SR_Bridge from every location an installer could have put
# it: the User Library recorded in Live's Library.cfg, the default User
# Library, and inside any Live app bundle (where pre-User-Library versions
# went, and where the installer's last-resort path lands).
#
# If your User Library is somewhere unusual, set:
#   MOVE_SR_USER_LIBRARY="/path/to/User Library" scripts/uninstall_mac.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PACKAGE_NAME="Move_SR_Bridge"
CONFIG_DIR="${HOME}/.move_sr_bridge"

# shellcheck source=lib/resolve_install_dir.sh
. "${SCRIPT_DIR}/lib/resolve_install_dir.sh"

echo "Move-SR-Bridge macOS Uninstaller"
echo "================================"
echo ""

# ---------------------------------------------------------------------------
# Live must not be running
# ---------------------------------------------------------------------------
if pgrep -x Live >/dev/null 2>&1; then
    echo "ERROR: Ableton Live is currently running."
    echo "Quit Live and run this again."
    exit 1
fi

# ---------------------------------------------------------------------------
# Collect every location a copy could live in
# ---------------------------------------------------------------------------
TARGETS=()
while IFS= read -r t; do
    TARGETS+=("$t")
done < <(msb_installed_dirs)

if [ ${#TARGETS[@]} -eq 0 ]; then
    echo "${PACKAGE_NAME} does not appear to be installed."
    echo ""
    echo "Checked:"
    msb_all_candidate_dirs | sed 's/^/  /'
    exit 0
fi

echo "Found ${#TARGETS[@]} installation(s):"
echo ""
for t in "${TARGETS[@]}"; do
    echo "  ${t}"
done
echo ""

# Under `set -e` a bare `read` that hits EOF would abort with no output.
confirm=""
read -rp "Remove all of the above? [y/N] " confirm || true
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Cancelled."
    exit 0
fi
echo ""

# ---------------------------------------------------------------------------
# Kill any running helper
# ---------------------------------------------------------------------------
if pgrep -x sr_helper_mac >/dev/null 2>&1; then
    echo "Stopping running sr_helper_mac..."
    pkill -x sr_helper_mac 2>/dev/null || true
    sleep 1
fi

# ---------------------------------------------------------------------------
# Remove.  Copies inside a Live app bundle may be root-owned, so fall back
# to sudo rather than failing outright.
# ---------------------------------------------------------------------------
FAILED=()
for t in "${TARGETS[@]}"; do
    echo "Removing: ${t}"
    if rm -rf "$t" 2>/dev/null; then
        echo "  Done."
    else
        echo "  Permission denied -- retrying with sudo..."
        if sudo rm -rf "$t"; then
            echo "  Done."
        else
            echo "  FAILED."
            FAILED+=("$t")
        fi
    fi
done
echo ""

# ---------------------------------------------------------------------------
# Offer to remove settings + log
# ---------------------------------------------------------------------------
if [ -d "$CONFIG_DIR" ]; then
    rmcfg=""
    read -rp "Also remove settings and log folder (${CONFIG_DIR})? [y/N] " rmcfg || true
    if [ "$rmcfg" = "y" ] || [ "$rmcfg" = "Y" ]; then
        rm -rf "$CONFIG_DIR"
        echo "Removed ${CONFIG_DIR}"
    else
        echo "Kept ${CONFIG_DIR}"
    fi
    echo ""
fi

if [ ${#FAILED[@]} -gt 0 ]; then
    echo "Uninstall completed with errors. Remove these manually:"
    for p in "${FAILED[@]}"; do
        echo "  ${p}"
    done
    exit 1
fi

echo "Uninstall complete."
echo ""
