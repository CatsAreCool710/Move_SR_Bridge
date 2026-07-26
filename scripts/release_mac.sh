#!/bin/bash
# release_mac.sh - Build macOS release assets for GitHub
# Copyright (C) 2026 Jeremiah Ticket
# Licensed under GPLv3 -- see LICENSE for details.
#
# Builds:
#   1. sr_helper_mac binary (PyInstaller)
#   2. Install Move-SR-Bridge.app (JXA installer, package + LICENSE embedded)
#   3. Move-SR-Bridge-macOS.zip (distribution archive -- contains only the .app)
#
# Note: this produces a single-arch binary matching the machine it runs on.
# Official releases are built by CI (.github/workflows/build.yml), which
# builds a universal2 (arm64 + x86_64) binary via a dual-arch build + lipo.
#
# Usage:
#   scripts/release_mac.sh
#   PYTHON=/path/to/python3 scripts/release_mac.sh
#
# The script is always non-interactive.
#
# After building, create a GitHub release:
#   gh release create "v$(python3 -c 'import sys; sys.path.insert(0, "Move_SR_Bridge"); import version; print(version.__version__)')" \
#       Move-SR-Bridge-macOS.zip --notes "Release notes here"
#
# The tag must match Move_SR_Bridge/version.py -- the release workflow
# refuses to publish otherwise.  This script prints the expected tag.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Interpreter used for the PyInstaller build.  Override with e.g.
#   PYTHON=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
#       scripts/release_mac.sh
# Official releases are built by CI on 3.13; if you build locally on a
# noticeably older interpreter the artefact will differ from the release.
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "ERROR: interpreter '${PYTHON}' not found."
    echo "Set PYTHON to the interpreter you want to build with."
    exit 1
fi

if ! "$PYTHON" -c "import PyInstaller" >/dev/null 2>&1; then
    echo "ERROR: PyInstaller is not available to ${PYTHON}."
    echo "Install it with:  ${PYTHON} -m pip install pyinstaller"
    echo "Or point PYTHON at an interpreter that already has it."
    exit 1
fi

echo "Interpreter: $("$PYTHON" -c 'import sys; print(sys.executable, sys.version.split()[0])')"

# Single source of truth for the version -- the release workflow refuses to
# publish unless the pushed tag matches this.
VERSION="$("$PYTHON" -c 'import sys; sys.path.insert(0, "Move_SR_Bridge"); import version; print(version.__version__)')"
TAG="v${VERSION}"
echo "Version:     ${VERSION} (tag ${TAG})"
echo ""

echo "Move-SR-Bridge macOS Release Builder"
echo "====================================="
echo ""

# ---------------------------------------------------------------------------
# Step 1: Run the unit suite
#
# The same gate CI applies before it will build anything.  This script used
# to go straight to PyInstaller, so the one release path a maintainer drives
# by hand was the one with no tests behind it.
# ---------------------------------------------------------------------------
echo "Step 1: Running unit tests..."
echo ""

"$PYTHON" -m unittest discover -s tests

echo ""

# ---------------------------------------------------------------------------
# Step 2: Build sr_helper_mac
# ---------------------------------------------------------------------------
echo "Step 2: Building sr_helper_mac (PyInstaller)..."
echo ""

rm -rf build dist
"$PYTHON" scripts/build_mac.py --yes

echo ""

# ---------------------------------------------------------------------------
# Step 3: Smoke-test the frozen binary
#
# Also a CI gate, and the one that matters most here: a frozen build can
# silently lose a runtime-only import (configparser did exactly that, and
# every release ignored config.ini until it was caught).  Nothing about
# that failure is visible from the build output -- speech keeps working
# and only the log level and DEBUG trace vanish.  Run before the .app is
# built, so a bad binary can never get embedded.
# ---------------------------------------------------------------------------
echo "Step 3: Smoke-testing the frozen helper against a real config.ini..."
echo ""

"$PYTHON" scripts/smoke_helper.py Move_SR_Bridge/sr_helper_mac

echo ""

# ---------------------------------------------------------------------------
# Step 4: Build installer .app (embeds the package + LICENSE inside it)
# ---------------------------------------------------------------------------
echo "Step 4: Building Install Move-SR-Bridge.app..."
echo ""

scripts/installer/mac/build.sh

echo ""

# ---------------------------------------------------------------------------
# Step 5: Create distribution zip -- contains only the self-contained .app
# ---------------------------------------------------------------------------
echo "Step 5: Creating distribution zip..."
echo ""

ZIP_NAME="Move-SR-Bridge-macOS.zip"
rm -f "$ZIP_NAME"
ditto -c -k --sequesterRsrc --keepParent "Install Move-SR-Bridge.app" "$ZIP_NAME"

ZIP_SIZE=$(ls -lh "$ZIP_NAME" | awk '{print $5}')

echo ""
echo "====================================="
echo "  Build complete!"
echo "====================================="
echo ""
echo "  Release asset: ${PROJECT_DIR}/${ZIP_NAME}"
echo "  Size:          ${ZIP_SIZE}"
echo ""
echo "Contents:"
echo "  - Install Move-SR-Bridge.app  (self-contained: package + LICENSE embedded)"
echo ""
echo "  Architecture:  $(lipo -archs "Install Move-SR-Bridge.app/Contents/Resources/Move_SR_Bridge/sr_helper_mac" 2>/dev/null || echo unknown)"
echo ""
echo "Next steps:"
echo "  1. Commit and push your changes"
echo "  2. Create a tag and push it -- this is the recommended route:"
echo "     git tag ${TAG}"
echo "     git push origin ${TAG}"
echo ""
echo "  CI builds a universal2 (arm64 + x86_64) helper and publishes it."
echo ""
echo "  Publishing THIS zip by hand ships a single-architecture helper that"
echo "  will not run on the other kind of Mac.  Only do that deliberately:"
echo "     gh release create ${TAG} ${ZIP_NAME} \\"
echo "         --title \"${TAG}\" --notes \"Release notes\""
echo ""
echo "  The release workflow refuses to publish unless the tag matches"
echo "  Move_SR_Bridge/version.py -- bump that file first if needed."
echo ""
