#!/bin/bash
# build.sh - Build the Move-SR-Bridge macOS installer
# Copyright (C) 2026 Jeremiah Ticket
# Licensed under GPLv3 -- see LICENSE for details.
#
# Requires macOS with osacompile (ships with macOS).
# Produces a self-contained "Install Move-SR-Bridge.app" in the project
# root, with the Move_SR_Bridge package and LICENSE embedded inside
# Contents/Resources/ so the .app is the only file that needs to be
# distributed -- no sibling folder required.
#
# Requires Move_SR_Bridge/sr_helper_mac to already be built.
# Build it first with: python scripts/build_mac.py

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$(dirname "$(dirname "$SCRIPT_DIR")")")"
APP_NAME="Install Move-SR-Bridge.app"

echo "Building Move-SR-Bridge installer..."
cd "$PROJECT_DIR"

PACKAGE_SRC="${PROJECT_DIR}/Move_SR_Bridge"

if [ ! -f "${PACKAGE_SRC}/sr_helper_mac" ]; then
    echo "ERROR: ${PACKAGE_SRC}/sr_helper_mac not found."
    echo "Build it first with: python scripts/build_mac.py"
    exit 1
fi

# The frozen helper bakes in its own copy of version.py (sr_helper.py does
# `from version import __version__` at runtime, and PyInstaller collects it).
# So a binary older than version.py reports the previous version while the
# package beside it reports the new one -- two different versions in the log
# file that is this project's primary support artefact, from one install.
if [ "${PACKAGE_SRC}/version.py" -nt "${PACKAGE_SRC}/sr_helper_mac" ]; then
    echo "ERROR: ${PACKAGE_SRC}/sr_helper_mac is older than version.py."
    echo "The bundled binary would report a stale version. Rebuild it:"
    echo "  python scripts/build_mac.py"
    exit 1
fi

rm -rf "$APP_NAME"
osacompile -l JavaScript -o "$APP_NAME" \
    "scripts/installer/mac/Install Move-SR-Bridge.js"

# Embed the package and license inside the app bundle so the .app is
# fully self-contained -- the distributed zip contains nothing else.
#
# Copied as a directory with an exclude list, not as a hand-written list of
# members.  This was the only packaging step in the repo that enumerated
# the package file by file, which makes it the only one that can silently
# ship an incomplete package when a module is added -- and the failure mode
# is an ImportError inside Live with nothing wrong on the installer side.
RESOURCES="${APP_NAME}/Contents/Resources"
mkdir -p "${RESOURCES}"
rsync -a \
    --exclude '__pycache__/' \
    --exclude '.DS_Store' \
    --exclude '*.exe' \
    --exclude '*.dll' \
    "${PACKAGE_SRC}/" "${RESOURCES}/Move_SR_Bridge/"
chmod +x "${RESOURCES}/Move_SR_Bridge/sr_helper_mac"
cp LICENSE "${RESOURCES}/"

# Fail loudly rather than shipping a package Live cannot import.
for required in __init__.py config.py version.py sr_bridge.py sr_helper.py sr_helper_mac; do
    if [ ! -f "${RESOURCES}/Move_SR_Bridge/${required}" ]; then
        echo "ERROR: ${required} is missing from the built app bundle."
        exit 1
    fi
done

echo "Built: ${PROJECT_DIR}/${APP_NAME}"
echo ""
echo "Double-click the .app to run the installer."
