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
set -euo pipefail

PACKAGE_NAME="Move_SR_Bridge"

# ---------------------------------------------------------------------------
# Kill any running sr_helper_mac processes
# ---------------------------------------------------------------------------
if pgrep -x sr_helper_mac >/dev/null 2>&1; then
    echo "Stopping running sr_helper_mac processes..."
    pkill -x sr_helper_mac 2>/dev/null || true
    sleep 1
fi

# ---------------------------------------------------------------------------
# Locate Ableton Live installations
# ---------------------------------------------------------------------------
LIVE_APPS=()
for app in /Applications/Ableton\ Live*.app; do
    [ -d "$app" ] && LIVE_APPS+=("$app")
done

if [ ${#LIVE_APPS[@]} -eq 0 ]; then
    echo "No Ableton Live installations found in /Applications."
    exit 0
fi

echo "Move-SR-Bridge macOS Uninstaller"
echo "================================"
echo ""
echo "Found ${#LIVE_APPS[@]} Ableton Live installation(s):"
echo ""

FOUND=0
for i in "${!LIVE_APPS[@]}"; do
    app="${LIVE_APPS[$i]}"
    name="$(basename "$app" .app)"
    scripts_dir="${app}/Contents/App-Resources/MIDI Remote Scripts"
    dest="${scripts_dir}/${PACKAGE_NAME}"
    if [ -d "$dest" ]; then
        echo "  $((i+1)). ${name} -- INSTALLED"
        FOUND=$((FOUND+1))
    else
        echo "  $((i+1)). ${name} -- not installed"
    fi
done

if [ "$FOUND" -eq 0 ]; then
    echo ""
    echo "${PACKAGE_NAME} is not installed in any Live installation."
    exit 0
fi

echo ""
echo "  A) Remove from ALL installations"
echo "  Q) Quit"
echo ""

read -rp "Select installation number (or A for all): " selection

SELECTED=()
if [ "$selection" = "A" ] || [ "$selection" = "a" ]; then
    SELECTED=("${!LIVE_APPS[@]}")
elif [[ "$selection" =~ ^[0-9]+$ ]]; then
    idx=$((selection - 1))
    if [ "$idx" -ge 0 ] && [ "$idx" -lt "${#LIVE_APPS[@]}" ]; then
        SELECTED=("$idx")
    else
        echo "ERROR: Invalid selection: $selection"
        exit 1
    fi
else
    echo "ERROR: Invalid selection: $selection"
    exit 1
fi

echo ""
read -rp "Remove ${PACKAGE_NAME} from ${#SELECTED[@]} installation(s)? [y/N] " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Cancelled."
    exit 0
fi

echo ""
for idx in "${SELECTED[@]}"; do
    app="${LIVE_APPS[$idx]}"
    name="$(basename "$app" .app)"
    scripts_dir="${app}/Contents/App-Resources/MIDI Remote Scripts"
    dest="${scripts_dir}/${PACKAGE_NAME}"

    if [ -d "$dest" ]; then
        echo "Removing from: ${name}"
        rm -rf "$dest"
        echo "  Done."
    fi
done

echo ""
echo "Uninstall complete."
echo ""
