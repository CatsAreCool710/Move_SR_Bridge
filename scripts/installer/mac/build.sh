#!/bin/bash
# build.sh - Build the Move-SR-Bridge macOS installer
# Copyright (C) 2026 Jeremiah Ticket
# Licensed under GPLv3 -- see LICENSE for details.
#
# Requires macOS with osacompile (ships with macOS).
# Produces "Install Move-SR-Bridge.app" in the project root.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "Building Move-SR-Bridge installer..."
cd "$PROJECT_DIR"

osacompile -l JavaScript -o "Install Move-SR-Bridge.app" \
    "scripts/installer/mac/Install Move-SR-Bridge.js"

echo "Built: ${PROJECT_DIR}/Install Move-SR-Bridge.app"
echo ""
echo "Double-click the .app to run the installer."
