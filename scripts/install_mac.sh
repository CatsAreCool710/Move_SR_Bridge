#!/bin/bash
# install_mac.sh - Deploy Move_SR_Bridge to Ableton Live on macOS
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
# Installs Move_SR_Bridge to all detected Ableton Live installations
# on macOS.  Requires the Move_SR_Bridge/ package to be present in the
# same directory as this script (or run from the project root).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PACKAGE_NAME="Move_SR_Bridge"
PACKAGE_SRC="${PROJECT_DIR}/${PACKAGE_NAME}"

# ---------------------------------------------------------------------------
# Locate Ableton Live installations in /Applications
# ---------------------------------------------------------------------------
LIVE_APPS=()
for app in /Applications/Ableton\ Live*.app; do
    [ -d "$app" ] && LIVE_APPS+=("$app")
done

if [ ${#LIVE_APPS[@]} -eq 0 ]; then
    echo "ERROR: No Ableton Live installations found in /Applications."
    echo ""
    echo "If Live is installed elsewhere, copy the ${PACKAGE_NAME}/ folder"
    "to your Live MIDI Remote Scripts directory manually."
    exit 1
fi

echo "Move-SR-Bridge macOS Installer"
echo "=============================="
echo ""
echo "Found ${#LIVE_APPS[@]} Ableton Live installation(s):"
echo ""

for i in "${!LIVE_APPS[@]}"; do
    app="${LIVE_APPS[$i]}"
    name="$(basename "$app" .app)"
    # Derive the MIDI Remote Scripts path
    scripts_dir="${app}/Contents/App-Resources/MIDI Remote Scripts"
    if [ -d "$scripts_dir" ]; then
        status="MIDI Remote Scripts found"
    else
        status="WARNING: MIDI Remote Scripts directory not found"
    fi
    echo "  $((i+1)). ${name}"
    echo "     ${status}"
done

echo ""
echo "  A) Install to ALL detections"
echo "  Q) Quit"
echo ""

# ---------------------------------------------------------------------------
# Prompt for selection (or accept from command-line arg $1)
# ---------------------------------------------------------------------------
if [ -n "${1:-}" ]; then
    selection="$1"
    echo "Using command-line selection: $selection"
else
    read -rp "Select installation number (or A for all): " selection
fi

# Build list of selected indices
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

# ---------------------------------------------------------------------------
# Validate source package
# ---------------------------------------------------------------------------
if [ ! -f "${PACKAGE_SRC}/__init__.py" ]; then
    echo "ERROR: ${PACKAGE_SRC}/__init__.py not found."
    echo "Run this script from the project root or ensure the package"
    echo "folder is next to the scripts/ directory."
    exit 1
fi

echo ""
echo "This will install ${PACKAGE_NAME} to ${#SELECTED[@]} Live installation(s)."
read -rp "Press Enter to continue, or Ctrl+C to cancel: "
echo ""

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
for idx in "${SELECTED[@]}"; do
    app="${LIVE_APPS[$idx]}"
    name="$(basename "$app" .app)"
    scripts_dir="${app}/Contents/App-Resources/MIDI Remote Scripts"
    dest="${scripts_dir}/${PACKAGE_NAME}"

    echo "Installing to: ${name}"

    if [ ! -d "$scripts_dir" ]; then
        echo "  ERROR: MIDI Remote Scripts directory not found, skipping."
        echo ""
        continue
    fi

    # Remove old installation if present
    if [ -d "$dest" ]; then
        echo "  Removing old installation..."
        rm -rf "$dest"
    fi

    # Copy package
    echo "  Copying ${PACKAGE_NAME}/..."
    cp -R "$PACKAGE_SRC" "$dest"

    # Make helper binary executable
    if [ -f "${dest}/sr_helper_mac" ]; then
        chmod +x "${dest}/sr_helper_mac"
    fi

    echo "  Done."
    echo ""
done

echo "Installation complete!"
echo ""
echo "To use:"
echo "  1. Open Ableton Live"
echo "  2. Go to Settings > Link, Tempo & MIDI"
echo "  3. Select 'Move_SR_Bridge' as your Control Surface"
echo "  4. Connect your Move via USB"
echo ""
echo "VoiceOver setup (required):"
echo "  1. Enable VoiceOver (Cmd+F5)"
echo "  2. Open VoiceOver Utility (VO+F8)"
echo "  3. Go to General > check 'Allow VoiceOver to be controlled"
echo "     with AppleScript'"
echo ""
echo "Config file: ~/.move_sr_bridge/config.ini"
echo "  (created automatically on first launch, edit to customise debounce)"
echo ""
