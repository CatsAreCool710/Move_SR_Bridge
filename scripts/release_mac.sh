#!/bin/bash
# release_mac.sh - Build macOS release assets for GitHub
# Copyright (C) 2026 Jeremiah Ticket
# Licensed under GPLv3 -- see LICENSE for details.
#
# Builds:
#   1. sr_helper_mac binary (PyInstaller)
#   2. Install Move-SR-Bridge.app (JXA installer)
#   3. Move-SR-Bridge-macOS.zip (distribution archive)
#
# Usage:
#   scripts/release_mac.sh              # Interactive
#   scripts/release_mac.sh --yes        # Non-interactive
#
# After building, create a GitHub release:
#   gh release create v1.1.0 Move-SR-Bridge-macOS.zip \
#       --title "v1.1.0" --notes "Release notes here"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
YES_MODE=false

if [ "${1:-}" = "--yes" ] || [ "${1:-}" = "-y" ]; then
    YES_MODE=true
fi

cd "$PROJECT_DIR"

echo "Move-SR-Bridge macOS Release Builder"
echo "====================================="
echo ""

# ---------------------------------------------------------------------------
# Step 1: Build sr_helper_mac
# ---------------------------------------------------------------------------
echo "Step 1: Building sr_helper_mac (PyInstaller)..."
echo ""

source venv/bin/activate
python scripts/build_mac.py --yes
deactivate

echo ""

# ---------------------------------------------------------------------------
# Step 2: Build installer .app
# ---------------------------------------------------------------------------
echo "Step 2: Building Install Move-SR-Bridge.app (osacompile)..."
echo ""

osacompile -l JavaScript -o "Install Move-SR-Bridge.app" \
    "scripts/installer/mac/Install Move-SR-Bridge.js"

echo ""

# ---------------------------------------------------------------------------
# Step 3: Create distribution zip
# ---------------------------------------------------------------------------
echo "Step 3: Creating distribution zip..."
echo ""

STAGING="${PROJECT_DIR}/staging"
rm -rf "$STAGING"
mkdir -p "$STAGING"

# Copy package (includes built sr_helper_mac)
cp -R Move_SR_Bridge "$STAGING/"

# Copy scripts
cp -R scripts "$STAGING/"

# Copy installer .app
cp -R "Install Move-SR-Bridge.app" "$STAGING/"

# Copy docs
cp README.md LICENSE "$STAGING/"

# Create zip
ZIP_NAME="Move-SR-Bridge-macOS.zip"
rm -f "$ZIP_NAME"
ditto -c -k --sequesterRsrc --keepParent "$STAGING" "$ZIP_NAME"
rm -rf "$STAGING"

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
echo "  - Move_SR_Bridge/          (package with sr_helper_mac)"
echo "  - scripts/                 (install/build scripts)"
echo "  - Install Move-SR-Bridge.app  (graphical installer)"
echo "  - README.md"
echo "  - LICENSE"
echo ""
echo "Next steps:"
echo "  1. Commit and push your changes"
echo "  2. Create a release:"
echo "     gh release create v1.1.0 ${ZIP_NAME} \\"
echo "         --title \"v1.1.0\" --notes \"Release notes\""
echo ""
echo "  Or create a tag and push it to trigger the CI workflow:"
echo "     git tag v1.1.0"
echo "     git push origin v1.1.0"
echo ""
