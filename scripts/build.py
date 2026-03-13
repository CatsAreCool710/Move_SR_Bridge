# build.py - PyInstaller build script for sr_helper.exe
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
"""
Build sr_helper.exe using PyInstaller.

Part of the Move-SR-Bridge project.

Usage:
    python scripts/build.py

Run from the project root directory (Move-SR-Bridge/).
Requires PyInstaller:  pip install pyinstaller
"""

import os
import shutil
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_DIR = os.path.join(PROJECT_ROOT, "Move_SR_Bridge")
HELPER_SRC = os.path.join(PACKAGE_DIR, "sr_helper.py")
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")


def main():
    print("Move-SR-Bridge Builder")
    print("=" * 40)
    print()

    if not os.path.exists(HELPER_SRC):
        print(f"ERROR: {HELPER_SRC} not found.")
        sys.exit(1)

    # Check PyInstaller is available
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("ERROR: PyInstaller is not installed.")
        print("  Install it with:  pip install pyinstaller")
        input("\nPress Enter to exit...")
        sys.exit(1)

    # Estimate output size (will be ~8-10 MB)
    print("This will build sr_helper.exe (PyInstaller --onefile --noconsole)")
    print(f"  Source: {HELPER_SRC}")
    print(f"  Output: {PACKAGE_DIR}/sr_helper.exe")
    print(f"  Estimated size: ~9 MB")
    print()

    # Prompt for confirmation
    confirm = input("Press Enter to build, or any other key to cancel: ")
    if confirm != "":
        print("\nBuild cancelled.")
        input("\nPress Enter to exit...")
        sys.exit(0)

    print("\nBuilding sr_helper.exe ...")
    print("-" * 40)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--noconsole",
        "--name",
        "sr_helper",
        "--distpath",
        DIST_DIR,
        "--workpath",
        BUILD_DIR,
        "--specpath",
        BUILD_DIR,
        HELPER_SRC,
    ]
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)

    if result.returncode != 0:
        print("\nERROR: PyInstaller build failed.")
        input("\nPress Enter to exit...")
        sys.exit(1)

    # Copy the built exe into the package directory
    built_exe = os.path.join(DIST_DIR, "sr_helper.exe")
    dest_exe = os.path.join(PACKAGE_DIR, "sr_helper.exe")
    if os.path.exists(built_exe):
        shutil.copy2(built_exe, dest_exe)
    else:
        print(f"\nWARNING: Expected {built_exe} but it was not found.")
        input("\nPress Enter to exit...")
        sys.exit(1)

    size_mb = os.path.getsize(dest_exe) / 1024 / 1024

    print()
    print("=" * 40)
    print("  Build complete!")
    print("=" * 40)
    print()
    print(f"  Executable: {dest_exe}")
    print(f"  Size:       {size_mb:.1f} MB")
    print()
    print("Next steps:")
    print("  1. Run scripts\\install.bat to deploy to Live")
    print("  2. Or use scripts\\install_from_source.bat for source-only")
    print()

    input("Press Enter to exit...")


if __name__ == "__main__":
    main()
