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
# Step 2: Build installer .app (embeds the package + LICENSE inside it)
# ---------------------------------------------------------------------------
echo "Step 2: Building Install Move-SR-Bridge.app..."
echo ""

scripts/installer/mac/build.sh

echo ""

# ---------------------------------------------------------------------------
# Step 3: Create distribution zip -- contains only the self-contained .app
# ---------------------------------------------------------------------------
echo "Step 3: Creating distribution zip..."
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
