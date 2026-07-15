#!/bin/bash
# start_helper_mac.sh - Manually launch sr_helper_mac for debugging
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
# Searches for sr_helper_mac.py (source) or sr_helper_mac (compiled) and
# runs it with visible terminal output for debugging.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PACKAGE_NAME="Move_SR_Bridge"

echo "Move-SR-Bridge Helper Launcher (macOS)"
echo "======================================="
echo ""

# ---------------------------------------------------------------------------
# Search locations for the helper
# ---------------------------------------------------------------------------
CANDIDATES=()

# 1. Source directory (project development)
if [ -f "${PROJECT_DIR}/${PACKAGE_NAME}/sr_helper.py" ]; then
    CANDIDATES+=("${PROJECT_DIR}/${PACKAGE_NAME}/sr_helper.py")
fi

# 2. Deployed copies in Live installations
for app in /Applications/Ableton\ Live*.app; do
    [ -d "$app" ] || continue
    scripts_dir="${app}/Contents/App-Resources/MIDI Remote Scripts"
    helper="${scripts_dir}/${PACKAGE_NAME}/sr_helper_mac"
    if [ -f "$helper" ]; then
        CANDIDATES+=("$helper")
    fi
    # Also check for source copy
    src_helper="${scripts_dir}/${PACKAGE_NAME}/sr_helper.py"
    if [ -f "$src_helper" ]; then
        CANDIDATES+=("$src_helper")
    fi
done

# De-duplicate
UNIQUE=()
for c in "${CANDIDATES[@]}"; do
    dup=0
    for u in "${UNIQUE[@]+"${UNIQUE[@]}"}"; do
        if [ "$c" = "$u" ]; then dup=1; break; fi
    done
    [ "$dup" -eq 0 ] && UNIQUE+=("$c")
done

if [ ${#UNIQUE[@]} -eq 0 ]; then
    echo "ERROR: No sr_helper_mac.py or sr_helper_mac found."
    echo ""
    echo "Build it first with: python scripts/build_mac.py"
    exit 1
fi

if [ ${#UNIQUE[@]} -eq 1 ]; then
    CHOSEN="${UNIQUE[0]}"
else
    echo "Found multiple helpers:"
    for i in "${!UNIQUE[@]}"; do
        echo "  $((i+1)). ${UNIQUE[$i]}"
    done
    echo ""
    read -rp "Select number: " sel
    idx=$((sel - 1))
    if [ "$idx" -lt 0 ] || [ "$idx" -ge "${#UNIQUE[@]}" ]; then
        echo "Invalid selection."
        exit 1
    fi
    CHOSEN="${UNIQUE[$idx]}"
fi

echo "Running: ${CHOSEN}"
echo "Log file will be written next to the helper."
echo "Press Ctrl+C to stop."
echo ""

if [ "${CHOSEN##*.}" = "py" ]; then
    python3 "$CHOSEN"
else
    exec "$CHOSEN"
fi
