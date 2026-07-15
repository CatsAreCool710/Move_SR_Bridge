# build_mac.py - PyInstaller build script for sr_helper_mac (macOS)
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
Build sr_helper_mac using PyInstaller (macOS).

Part of the Move-SR-Bridge project.

Usage:
    python scripts/build_mac.py         # Interactive (prompts for confirmation)
    python scripts/build_mac.py --yes    # Non-interactive (skip prompts)

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
    yes_mode = "--yes" in sys.argv or "-y" in sys.argv

    print("Move-SR-Bridge macOS Builder")
    print("=" * 40)
    print()

    if not os.path.exists(HELPER_SRC):
        print("ERROR: {} not found.".format(HELPER_SRC))
        if not yes_mode:
            input("\nPress Enter to exit...")
        sys.exit(1)

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("ERROR: PyInstaller is not installed.")
        print("  Install it with:  pip install pyinstaller")
        if not yes_mode:
            input("\nPress Enter to exit...")
        sys.exit(1)

    print("This will build sr_helper_mac (PyInstaller --onefile)")
    print("  Source: {}".format(HELPER_SRC))
    print("  Output: {}/sr_helper_mac".format(PACKAGE_DIR))
    print()

    if not yes_mode:
        confirm = input("Press Enter to build, or any other key to cancel: ")
        if confirm != "":
            print("\nBuild cancelled.")
            input("\nPress Enter to exit...")
            sys.exit(0)
    else:
        print("Running in non-interactive mode (--yes flag detected)")
        print()

    print("\nBuilding sr_helper_mac ...")
    print("-" * 40)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        "sr_helper_mac",
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
        if not yes_mode:
            input("\nPress Enter to exit...")
        sys.exit(1)

    built = os.path.join(DIST_DIR, "sr_helper_mac")
    dest = os.path.join(PACKAGE_DIR, "sr_helper_mac")
    if os.path.exists(built):
        shutil.copy2(built, dest)
        os.chmod(dest, 0o755)
    else:
        print("\nWARNING: Expected {} but it was not found.".format(built))
        if not yes_mode:
            input("\nPress Enter to exit...")
        sys.exit(1)

    size_mb = os.path.getsize(dest) / 1024 / 1024

    print()
    print("=" * 40)
    print("  Build complete!")
    print("=" * 40)
    print()
    print("  Executable: {}".format(dest))
    print("  Size:       {:.1f} MB".format(size_mb))
    print()
    print("Next steps:")
    print("  1. Run scripts/install_mac.sh to deploy to Live")
    print("  2. Or use scripts/start_helper_mac.sh for debugging")
    print()

    if not yes_mode:
        input("Press Enter to exit...")


if __name__ == "__main__":
    main()
