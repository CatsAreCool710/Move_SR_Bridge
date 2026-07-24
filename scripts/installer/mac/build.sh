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

rm -rf "$APP_NAME"
osacompile -l JavaScript -o "$APP_NAME" \
    "scripts/installer/mac/Install Move-SR-Bridge.js"

# Embed the package and license inside the app bundle so the .app is
# fully self-contained -- the distributed zip contains nothing else.
RESOURCES="${APP_NAME}/Contents/Resources"
mkdir -p "${RESOURCES}/Move_SR_Bridge"
cp "${PACKAGE_SRC}/__init__.py" "${PACKAGE_SRC}/config.py" \
   "${PACKAGE_SRC}/sr_bridge.py" "${PACKAGE_SRC}/sr_helper.py" \
   "${PACKAGE_SRC}/sr_helper_mac" \
   "${RESOURCES}/Move_SR_Bridge/"
chmod +x "${RESOURCES}/Move_SR_Bridge/sr_helper_mac"
cp LICENSE "${RESOURCES}/"

echo "Built: ${PROJECT_DIR}/${APP_NAME}"
echo ""
echo "Double-click the .app to run the installer."
