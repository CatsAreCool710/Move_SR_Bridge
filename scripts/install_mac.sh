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
# Installs Move_SR_Bridge into the Ableton User Library's "Remote Scripts"
# folder.  The exact location is read from Live's own Library.cfg where
# possible -- see scripts/lib/resolve_install_dir.sh for the full chain.
#
# This deliberately avoids installing inside Live's application bundle:
# that bundle is code-signed with a hardened runtime, so writing into it
# breaks the signature seal, needs admin rights, and is wiped by every Live
# update.  The User Library is per-user, always writable, survives updates,
# and one install covers every Live installation on the machine.  The
# in-bundle path is only used if no User Library can be found or created,
# and the script warns loudly when that happens.
#
# To force a specific location:
#   MOVE_SR_USER_LIBRARY="/path/to/User Library" scripts/install_mac.sh
# Live shows the path under Settings > Library > Location of User Library.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PACKAGE_NAME="Move_SR_Bridge"
PACKAGE_SRC="${PROJECT_DIR}/${PACKAGE_NAME}"

# shellcheck source=lib/resolve_install_dir.sh
. "${SCRIPT_DIR}/lib/resolve_install_dir.sh"

echo "Move-SR-Bridge macOS Installer"
echo "=============================="
echo ""

# ---------------------------------------------------------------------------
# Validate source package
# ---------------------------------------------------------------------------
if [ ! -f "${PACKAGE_SRC}/__init__.py" ]; then
    echo "ERROR: ${PACKAGE_SRC}/__init__.py not found."
    echo "Run this script from the project root or ensure the package"
    echo "folder is next to the scripts/ directory."
    exit 1
fi

if [ ! -f "${PACKAGE_SRC}/sr_helper_mac" ]; then
    echo "WARNING: ${PACKAGE_SRC}/sr_helper_mac not found."
    echo "The remote script will install, but speech needs the helper."
    echo "Build it with: python scripts/build_mac.py"
    echo "Or start it from source: scripts/start_helper_mac.sh"
    echo ""
fi

# ---------------------------------------------------------------------------
# Live must not be running -- it only scans Remote Scripts at startup
# ---------------------------------------------------------------------------
if pgrep -x Live >/dev/null 2>&1; then
    echo "ERROR: Ableton Live is currently running."
    echo "Quit Live and run this again -- Live only scans Remote Scripts"
    echo "when it starts up."
    exit 1
fi

# ---------------------------------------------------------------------------
# Work out where to install
# ---------------------------------------------------------------------------
if ! msb_resolve_remote_scripts create; then
    echo "ERROR: Could not find or create an Ableton User Library."
    echo ""
    if [ -n "${MOVE_SR_USER_LIBRARY:-}" ]; then
        echo "MOVE_SR_USER_LIBRARY is set to:"
        echo "  ${MOVE_SR_USER_LIBRARY}"
        echo "but that folder does not exist and could not be created."
    else
        echo "Find the path in Live under"
        echo "Settings > Library > Location of User Library, then re-run:"
        echo "  MOVE_SR_USER_LIBRARY=\"/path/to/User Library\" $0"
    fi
    exit 1
fi

DEST="${MSB_REMOTE_SCRIPTS}/${PACKAGE_NAME}"

echo "Install to:  ${DEST}"
echo "Located by:  ${MSB_SOURCE}"
echo ""

if [ -n "${MSB_LAST_RESORT:-}" ]; then
    echo "WARNING: no Ableton User Library was found, so this will install"
    echo "inside Live's application bundle. That location needs admin"
    echo "rights, breaks Live's code signature, and is erased by every Live"
    echo "update -- you will have to reinstall after each one."
    echo ""
    echo "Better: open Live once so it creates your User Library, or set"
    echo "MOVE_SR_USER_LIBRARY to its path, then run this again."
    echo ""
fi

# Under `set -e` a bare `read` that hits EOF would abort the script with no
# output at all, so handle non-interactive input explicitly.
if ! read -rp "Press Enter to continue, or Ctrl+C to cancel: "; then
    echo ""
    echo "ERROR: no input available (not running interactively). Cancelled."
    exit 1
fi
echo ""

# ---------------------------------------------------------------------------
# Stop a helper left over from a previous session
# ---------------------------------------------------------------------------
if pgrep -x sr_helper_mac >/dev/null 2>&1; then
    echo "Stopping running sr_helper_mac..."
    pkill -x sr_helper_mac 2>/dev/null || true
    sleep 1
fi

# ---------------------------------------------------------------------------
# Install
#
# Staged, not in place.  The old copy is only removed once the new one is
# fully built and sitting next to it, so a failure part-way through leaves
# the working install untouched instead of deleting it and then failing to
# replace it.  That matters most on the last-resort path, where the target
# lives inside Live's root-owned app bundle: "rm succeeded, cp denied" was
# a real way to end up with no remote script at all.
#
# msb_run_privileged retries a command under sudo when the unprivileged
# attempt fails -- the same escalation the stale-copy sweep below has
# always used, which the install path itself was missing.
# ---------------------------------------------------------------------------
msb_run_privileged() {
    if "$@" 2>/dev/null; then
        return 0
    fi
    echo "  Permission denied -- retrying with sudo..."
    sudo "$@"
}

msb_run_privileged mkdir -p "$MSB_REMOTE_SCRIPTS"

# A sibling of $DEST, so the final move is a rename within one filesystem
# (atomic) rather than a second copy that could itself fail half-done.
STAGE="${DEST}.new.$$"
BACKUP="${DEST}.old.$$"

msb_cleanup_stage() {
    [ -e "$STAGE" ] && msb_run_privileged rm -rf "$STAGE" || true
}
trap msb_cleanup_stage EXIT

echo "Copying ${PACKAGE_NAME}/..."
msb_run_privileged rm -rf "$STAGE"
msb_run_privileged cp -R "$PACKAGE_SRC" "$STAGE"

# Drop the build machine's bytecode and Finder metadata. The .pyc files are
# compiled by whatever interpreter last imported the package here, which is
# not necessarily Live's 3.11; shipping them adds nothing and the community
# advice for remote scripts is explicitly to delete stale compiled files.
msb_run_privileged rm -rf "${STAGE}/__pycache__"
# Cosmetic, so no sudo escalation and no failure if it cannot be done.
find "$STAGE" -name '.DS_Store' -delete 2>/dev/null || true

if [ -f "${STAGE}/sr_helper_mac" ]; then
    msb_run_privileged chmod +x "${STAGE}/sr_helper_mac"
fi

# Swap. The old copy is moved aside rather than deleted, so if the rename
# of the new one somehow fails there is still something to put back.
if [ -d "$DEST" ]; then
    echo "Replacing old installation..."
    msb_run_privileged rm -rf "$BACKUP"
    msb_run_privileged mv "$DEST" "$BACKUP"
fi

if msb_run_privileged mv "$STAGE" "$DEST"; then
    msb_run_privileged rm -rf "$BACKUP"
else
    echo "ERROR: could not move the new install into place."
    if [ -d "$BACKUP" ]; then
        echo "Restoring the previous installation..."
        msb_run_privileged mv "$BACKUP" "$DEST" || true
    fi
    exit 1
fi

trap - EXIT

echo "Done."
echo ""

# ---------------------------------------------------------------------------
# Sweep every other location a copy could be sitting in.  Two packages with
# the same name on Live's script search path is ambiguous, and a stale one
# would keep shadowing this install.
# ---------------------------------------------------------------------------
STALE_FAILED=()
while IFS= read -r stale; do
    [ "$stale" = "$DEST" ] && continue
    echo "Removing stale copy at another location:"
    echo "  ${stale}"
    if rm -rf "$stale" 2>/dev/null; then
        echo "  Removed."
    else
        echo "  Permission denied -- retrying with sudo..."
        if sudo rm -rf "$stale"; then
            echo "  Removed."
        else
            echo "  FAILED."
            STALE_FAILED+=("$stale")
        fi
    fi
    echo ""
done < <(msb_installed_dirs)

if [ ${#STALE_FAILED[@]} -gt 0 ]; then
    echo "WARNING: an old copy is still on Live's search path and may"
    echo "override this install. Remove it manually:"
    for p in "${STALE_FAILED[@]}"; do
        echo "  ${p}"
    done
    echo ""
fi

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
echo "  (created automatically on first launch, edit to customise"
echo "   debounce and logging)"
echo "Log file:    ~/.move_sr_bridge/Move_SR_Bridge.log"
echo ""
