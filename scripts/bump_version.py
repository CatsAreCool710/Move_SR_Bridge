#!/usr/bin/env python3
# bump_version.py - Read and bump Move_SR_Bridge/version.py
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
"""Read and bump the single source of the version string.

Move_SR_Bridge/version.py is the only place a version is written; both
processes log it at startup and the release workflow asserts it matches
the pushed tag.  This script rewrites *only* the `__version__` line, so
the GPL header and the module docstring survive untouched.

Version scheme -- PEP 440 dot form:

    MAJOR.MINOR.PATCH[.devN]        e.g. 1.7.0  or  1.7.0.dev1

`1.7.0.dev1` sorts *before* `1.7.0` under PEP 440, which is what it means:
a pre-release of 1.7.0, not something after it.  Chosen over `1.7.0-dev1`
because version.py is Python and should follow Python's convention; git
tags take dots without complaint.

Usage:
    python scripts/bump_version.py --show
    python scripts/bump_version.py --set 1.7.0.dev1
    python scripts/bump_version.py --dev        # 1.7.0.dev1 -> 1.7.0.dev2
    python scripts/bump_version.py --release    # 1.7.0.dev3 -> 1.7.0
"""

import argparse
import os
import re
import sys

# The canonical pattern, shared by this script, tests/test_version.py and
# .github/workflows/build.yml.  Leading zeros in devN are rejected so
# `dev1` and `dev01` can never both exist and disagree about ordering.
#
# The workflow keeps a copy of this string; tests/test_version.py asserts
# the two are character-for-character identical, because a drift there
# means CI accepts a version this tooling rejects or vice versa.
VERSION_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+(\.dev[1-9][0-9]*)?$"

_VERSION_RE = re.compile(VERSION_PATTERN)
_DEV_RE = re.compile(r"^([0-9]+\.[0-9]+\.[0-9]+)\.dev([1-9][0-9]*)$")
# Matches the assignment line without caring about quote style.
_ASSIGN_RE = re.compile(r'^__version__\s*=\s*["\'][^"\']*["\']\s*$')

VERSION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Move_SR_Bridge",
    "version.py",
)


class VersionError(ValueError):
    """Raised for anything that would put a bad version on disk."""


def is_valid(version):
    """True when `version` matches the canonical pattern."""
    return bool(_VERSION_RE.match(version or ""))


def validate(version):
    """Return `version` unchanged, or raise VersionError."""
    if not is_valid(version):
        raise VersionError(
            "%r is not a valid version -- expected MAJOR.MINOR.PATCH "
            "optionally followed by .devN (N >= 1, no leading zero), "
            "e.g. 1.7.0 or 1.7.0.dev1" % (version,)
        )
    return version


def is_dev(version):
    """True for a .devN pre-release version."""
    return bool(_DEV_RE.match(version or ""))


def next_dev(version):
    """1.7.0.dev1 -> 1.7.0.dev2.  Raises on a plain release version.

    Deliberately refuses to invent a dev version from a release one:
    turning 1.6.0 into "1.7.0.dev1" means deciding whether the next
    release is a patch, minor or major, and a tool that guesses that will
    eventually guess wrong without anyone noticing.  Use --set.
    """
    validate(version)
    match = _DEV_RE.match(version)
    if match is None:
        raise VersionError(
            "%s is a release version, so there is no 'next dev' to derive "
            "-- the next base version is a decision, not a calculation. "
            "Use --set X.Y.Z.dev1 to start a new dev series." % (version,)
        )
    return "%s.dev%d" % (match.group(1), int(match.group(2)) + 1)


def to_release(version):
    """1.7.0.dev3 -> 1.7.0.  Raises when already a release version."""
    validate(version)
    match = _DEV_RE.match(version)
    if match is None:
        raise VersionError(
            "%s is already a release version; nothing to drop." % (version,)
        )
    return match.group(1)


def tag_for(version):
    """The git tag that must accompany `version`."""
    return "v" + version


def read_version(path=VERSION_FILE):
    """The current __version__, read without importing the module."""
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if _ASSIGN_RE.match(line.strip()):
                return line.split("=", 1)[1].strip().strip("\"'")
    raise VersionError("no __version__ assignment found in %s" % (path,))


def write_version(version, path=VERSION_FILE):
    """Rewrite only the __version__ line, leaving every other byte alone.

    The GPL header and the docstring must survive: a rewrite that
    regenerated the file would be a licensing defect, not a cosmetic one.
    """
    validate(version)
    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.readlines()

    replaced = False
    for index, line in enumerate(lines):
        if _ASSIGN_RE.match(line.strip()):
            lines[index] = '__version__ = "%s"\n' % (version,)
            replaced = True
            break
    if not replaced:
        raise VersionError("no __version__ assignment found in %s" % (path,))

    with open(path, "w", encoding="utf-8") as handle:
        handle.writelines(lines)
    return version


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read and bump Move_SR_Bridge/version.py",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--show", action="store_true", help="print the current version and tag"
    )
    group.add_argument("--set", metavar="VERSION", help="set an exact version")
    group.add_argument(
        "--dev",
        action="store_true",
        help="bump the .devN suffix (1.7.0.dev1 -> 1.7.0.dev2)",
    )
    group.add_argument(
        "--release",
        action="store_true",
        help="drop the .devN suffix (1.7.0.dev3 -> 1.7.0)",
    )
    args = parser.parse_args(argv)

    try:
        current = read_version()
        if args.show:
            new = current
            validate(current)
        elif args.set:
            new = write_version(validate(args.set))
        elif args.dev:
            new = write_version(next_dev(current))
        else:
            new = write_version(to_release(current))
    except VersionError as error:
        print("error: %s" % (error,), file=sys.stderr)
        return 1
    except OSError as error:
        print("error: %s" % (error,), file=sys.stderr)
        return 1

    if args.show:
        print("%s (tag %s)" % (new, tag_for(new)))
    else:
        print("%s -> %s (tag %s)" % (current, new, tag_for(new)))
    if is_dev(new):
        print("dev version: CI will build it but publish no release.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
