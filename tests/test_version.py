# test_version.py - Tests for the version string and its tooling
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
"""Tests for Move_SR_Bridge/version.py and scripts/bump_version.py."""

import importlib.util
import os
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_SCRIPT = os.path.join(_ROOT, "scripts", "bump_version.py")
_VERSION_FILE = os.path.join(_ROOT, "Move_SR_Bridge", "version.py")
_WORKFLOW = os.path.join(_ROOT, ".github", "workflows", "build.yml")


def _load_bump_version():
    """Import scripts/bump_version.py by path -- scripts/ is not a package."""
    spec = importlib.util.spec_from_file_location("bump_version", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VersionStringTest(unittest.TestCase):
    """The shipped version string itself."""

    def setUp(self):
        self.m = _load_bump_version()

    def test_shipped_version_is_valid(self):
        # Catches a hand-edited typo (1.7.O, v1.7.0, 1.7) reaching a tag.
        # Worth the file on its own.
        version = self.m.read_version(_VERSION_FILE)
        self.assertTrue(
            self.m.is_valid(version),
            "Move_SR_Bridge/version.py says %r, which is not a valid "
            "version" % (version,),
        )

    def test_read_version_matches_the_module(self):
        import sys

        sys.path.insert(0, os.path.join(_ROOT, "Move_SR_Bridge"))
        try:
            import version as version_module

            self.assertEqual(
                self.m.read_version(_VERSION_FILE), version_module.__version__
            )
        finally:
            sys.path.pop(0)


class ValidationTest(unittest.TestCase):
    def setUp(self):
        self.m = _load_bump_version()

    def test_accepts_release_and_dev(self):
        for good in ("1.7.0", "1.7.0.dev1", "0.0.1", "10.20.30.dev99"):
            self.assertTrue(self.m.is_valid(good), good)

    def test_rejects_malformed(self):
        # dev0 and dev01 are the rows a plain \d+ pattern would pass and the
        # intended one does not -- they are why the pattern is [1-9][0-9]*.
        for bad in (
            "1.7",
            "1.7.0dev1",
            "1.7.0.dev0",
            "1.7.0.dev01",
            "v1.7.0",
            "1.7.0.rc1",
            "1.7.0.dev",
            "",
            None,
        ):
            self.assertFalse(self.m.is_valid(bad), repr(bad))

    def test_validate_raises_on_bad_input(self):
        with self.assertRaises(self.m.VersionError):
            self.m.validate("1.7")


class BumpTest(unittest.TestCase):
    def setUp(self):
        self.m = _load_bump_version()

    def test_next_dev_increments(self):
        self.assertEqual(self.m.next_dev("1.7.0.dev1"), "1.7.0.dev2")

    def test_next_dev_is_arithmetic_not_string(self):
        # dev9 -> dev10 is the discriminating case: a string bump gives
        # "dev91" or similar and passes every other assertion here.
        self.assertEqual(self.m.next_dev("1.7.0.dev9"), "1.7.0.dev10")
        self.assertEqual(self.m.next_dev("1.7.0.dev10"), "1.7.0.dev11")

    def test_next_dev_refuses_a_release_version(self):
        # Deriving "the next dev" from 1.6.0 means guessing whether the next
        # release is a patch, minor or major.
        with self.assertRaises(self.m.VersionError):
            self.m.next_dev("1.7.0")

    def test_to_release_drops_the_suffix(self):
        self.assertEqual(self.m.to_release("1.7.0.dev3"), "1.7.0")

    def test_to_release_refuses_a_release_version(self):
        with self.assertRaises(self.m.VersionError):
            self.m.to_release("1.7.0")

    def test_is_dev(self):
        self.assertTrue(self.m.is_dev("1.7.0.dev1"))
        self.assertFalse(self.m.is_dev("1.7.0"))

    def test_tag_for(self):
        self.assertEqual(self.m.tag_for("1.7.0.dev1"), "v1.7.0.dev1")


class RewriteTest(unittest.TestCase):
    """write_version() must touch exactly one line."""

    def setUp(self):
        self.m = _load_bump_version()
        with open(_VERSION_FILE, "r", encoding="utf-8") as handle:
            self.original = handle.read()
        fd, self.path = tempfile.mkstemp(suffix=".py")
        os.close(fd)
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(self.original)
        self.addCleanup(os.unlink, self.path)

    def test_rewrite_preserves_every_other_line(self):
        self.m.write_version("9.9.9.dev7", self.path)
        with open(self.path, "r", encoding="utf-8") as handle:
            new = handle.read()

        before = self.original.splitlines()
        after = new.splitlines()
        self.assertEqual(len(before), len(after), "line count changed")
        differing = [
            index
            for index, (a, b) in enumerate(zip(before, after))
            if a != b
        ]
        self.assertEqual(
            len(differing), 1, "expected exactly one changed line"
        )
        self.assertTrue(after[differing[0]].startswith("__version__"))

    def test_rewrite_keeps_the_licence_header(self):
        # A rewrite that regenerated the file would be a licensing defect,
        # not a cosmetic one.
        self.m.write_version("9.9.9", self.path)
        with open(self.path, "r", encoding="utf-8") as handle:
            new = handle.read()
        self.assertIn("GNU General Public License", new)
        self.assertIn("Copyright (C) 2026 Jeremiah Ticket", new)

    def test_round_trip(self):
        self.m.write_version("2.3.4.dev5", self.path)
        self.assertEqual(self.m.read_version(self.path), "2.3.4.dev5")

    def test_rewrite_refuses_an_invalid_version(self):
        with self.assertRaises(self.m.VersionError):
            self.m.write_version("nope", self.path)
        self.assertEqual(self.m.read_version(self.path), self.m.read_version(_VERSION_FILE))


class WorkflowAgreementTest(unittest.TestCase):
    """CI and the tooling must accept exactly the same versions."""

    def test_workflow_pattern_matches_the_script(self):
        # If these drift, CI accepts a version bump_version.py rejects (or
        # the reverse) and the disagreement only surfaces at release time.
        m = _load_bump_version()
        with open(_WORKFLOW, "r", encoding="utf-8") as handle:
            workflow = handle.read()
        self.assertIn(
            "pattern='%s'" % (m.VERSION_PATTERN,),
            workflow,
            "build.yml's version pattern has drifted from "
            "scripts/bump_version.py VERSION_PATTERN",
        )


if __name__ == "__main__":
    unittest.main()
