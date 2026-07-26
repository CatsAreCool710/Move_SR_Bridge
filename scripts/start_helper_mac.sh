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
# Searches for sr_helper.py (source) or sr_helper_mac (compiled) and runs
# it with visible terminal output for debugging.
#
# Installed copies are found through the same resolver the installer uses
# (scripts/lib/resolve_install_dir.sh), so this follows Live's Library.cfg
# and finds the helper wherever the install actually landed.
#
# To force a specific location:
#   MOVE_SR_USER_LIBRARY="/path/to/User Library" scripts/start_helper_mac.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PACKAGE_NAME="Move_SR_Bridge"

# shellcheck source=lib/resolve_install_dir.sh
. "${SCRIPT_DIR}/lib/resolve_install_dir.sh"

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

# 2. Every installed copy the resolver knows about -- User Library first,
#    Live app bundles last, matching the installer's own preference order.
while IFS= read -r pkg; do
    if [ -f "${pkg}/sr_helper_mac" ]; then
        CANDIDATES+=("${pkg}/sr_helper_mac")
    fi
    if [ -f "${pkg}/sr_helper.py" ]; then
        CANDIDATES+=("${pkg}/sr_helper.py")
    fi
done < <(msb_installed_dirs)

# De-duplicate
UNIQUE=()
for c in "${CANDIDATES[@]+"${CANDIDATES[@]}"}"; do
    dup=0
    for u in "${UNIQUE[@]+"${UNIQUE[@]}"}"; do
        if [ "$c" = "$u" ]; then dup=1; break; fi
    done
    [ "$dup" -eq 0 ] && UNIQUE+=("$c")
done

if [ ${#UNIQUE[@]} -eq 0 ]; then
    echo "ERROR: No sr_helper.py or sr_helper_mac found."
    echo ""
    echo "Searched:"
    echo "  ${PROJECT_DIR}/${PACKAGE_NAME}/"
    msb_all_candidate_dirs | sed 's/^/  /'
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
    # Guarded like install_mac.sh / uninstall_mac.sh: under `set -e` a bare
    # read that hits EOF aborts the script with no output at all.
    sel=""
    if ! read -rp "Select number: " sel; then
        echo ""
        echo "ERROR: no input available (not running interactively)."
        exit 1
    fi
    # Validate as a plain number BEFORE any arithmetic. bash's $((...))
    # evaluates its argument as an expression, and an array subscript
    # inside one is expanded -- so "$((sel - 1))" on unvalidated input is
    # not merely a wrong answer, it can run a command substitution.
    # start_helper.bat guards the same prompt with findstr; match it.
    case "$sel" in
        ''|*[!0-9]*)
            echo "Invalid selection: '${sel}'. Enter a number 1-${#UNIQUE[@]}."
            exit 1
            ;;
    esac
    idx=$((10#$sel - 1))
    if [ "$idx" -lt 0 ] || [ "$idx" -ge "${#UNIQUE[@]}" ]; then
        echo "Invalid selection: '${sel}'. Enter a number 1-${#UNIQUE[@]}."
        exit 1
    fi
    CHOSEN="${UNIQUE[$idx]}"
fi

echo "Running: ${CHOSEN}"
echo "Log file: ${HOME}/.move_sr_bridge/Move_SR_Bridge.log"
echo "Press Ctrl+C to stop."
echo ""

if [ "${CHOSEN##*.}" = "py" ]; then
    python3 "$CHOSEN"
else
    exec "$CHOSEN"
fi
