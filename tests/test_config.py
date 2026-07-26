# test_config.py - Tests for config loading and its failure modes
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
"""Tests that a bad config.ini cannot cost the user the control surface.

config.ini is documented as user-editable, and the remote script reads it
at *module import* -- inside Live.  Anything that escapes there makes Live
skip the script entirely, so Move_SR_Bridge simply stops appearing in the
Control Surface dropdown with no indication why.

Two ways in, both of which shipped:

  * `config.read(..., encoding="utf-8")` raises UnicodeDecodeError on a
    file with an invalid byte -- a ValueError, so config.py's own
    `except configparser.Error` handler does not catch it.  Saving
    config.ini from Notepad in its default ANSI encoding with any accented
    character in it produces exactly this.
  * `getattr(logging, name)` finds any module attribute, so a `level =`
    naming a non-level (BASIC_FORMAT is a str) makes setLevel() raise.

Each case runs in its own interpreter, because the package reads the
config once at import and caches the result.
"""

import os
import subprocess
import sys
import tempfile
import shutil
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TESTS_DIR)

# Imports the package under a HOME we control, then reports what it made of
# the config.  Deliberately does NOT go through stubs.import_bridge(), which
# redirects HOME to a temp dir of its own.
_PROBE = """
import sys
sys.path.insert(0, %r)
import stubs
stubs._install_fake_move_package()
sys.path.insert(0, %r)
import logging
import Move_SR_Bridge as m
print("LEVEL=%%s" %% logging.getLevelName(m.logger.getEffectiveLevel()))
print("STATUS=%%s" %% m._config_status)
print("DEBOUNCE=%%s" %% m._cfg.get("debounce", "delay_ms", fallback="?"))
""" % (TESTS_DIR, REPO_ROOT)


class ConfigResilienceTest(unittest.TestCase):
    def _load_with(self, config_bytes):
        """Import the package against a config.ini of exactly these bytes."""
        home = tempfile.mkdtemp(prefix="msb-cfg-test-")
        self.addCleanup(shutil.rmtree, home, True)
        state = os.path.join(home, ".move_sr_bridge")
        os.makedirs(state)
        if config_bytes is not None:
            with open(os.path.join(state, "config.ini"), "wb") as f:
                f.write(config_bytes)

        env = dict(os.environ)
        env["HOME"] = home
        env["USERPROFILE"] = home
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        result = subprocess.run(
            [sys.executable, "-c", _PROBE],
            capture_output=True, text=True, cwd=REPO_ROOT, env=env, timeout=60,
        )
        self.assertEqual(
            result.returncode, 0,
            "importing the package raised, which inside Live means the "
            "control surface disappears from Live's dropdown entirely.\n"
            "stderr:\n%s" % result.stderr,
        )
        out = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                out[k] = v
        return out

    def test_valid_config_is_actually_read(self):
        # The control: without this, every assertion below would pass just
        # as well against a config that was never opened.
        info = self._load_with(
            b"[debounce]\nenabled = true\ndelay_ms = 175\n"
            b"[logging]\nlevel = DEBUG\n"
        )
        self.assertEqual(info["LEVEL"], "DEBUG")
        self.assertEqual(info["DEBOUNCE"], "175")
        self.assertEqual(info["STATUS"], "ok")

    def test_non_utf8_config_does_not_break_the_control_surface(self):
        # Notepad's default ANSI save, with any accented character in it.
        info = self._load_with(
            b"[logging]\n# caf\xe9 au lait\nlevel = DEBUG\n"
        )
        self.assertEqual(info["LEVEL"], "INFO", "should fall back to INFO")
        self.assertIn("unreadable", info["STATUS"], "and say why")

    def test_level_naming_a_non_level_attribute(self):
        # logging.BASIC_FORMAT exists and is a format string, so getattr
        # finds it and setLevel() raises ValueError on it.
        info = self._load_with(b"[logging]\nlevel = BASIC_FORMAT\n")
        self.assertEqual(info["LEVEL"], "INFO")
        self.assertIn("unknown level", info["STATUS"])

    def test_level_notset_does_not_silently_disable_logging(self):
        # setLevel(NOTSET) means "inherit", which drops everything below
        # WARNING -- the same invisible outcome, reached a different way.
        info = self._load_with(b"[logging]\nlevel = notset\n")
        self.assertEqual(info["LEVEL"], "INFO")
        self.assertIn("unknown level", info["STATUS"])

    def test_level_naming_something_that_does_not_exist(self):
        info = self._load_with(b"[logging]\nlevel = CHATTY\n")
        self.assertEqual(info["LEVEL"], "INFO")
        self.assertIn("unknown level", info["STATUS"])

    def test_missing_section_header(self):
        # A configparser.Error, which config.py itself already handled --
        # kept so the two paths stay distinguishable if that ever changes.
        info = self._load_with(b"level = DEBUG\n")
        self.assertEqual(info["LEVEL"], "INFO")

    def test_truncated_mid_write(self):
        info = self._load_with(b"[debounce]\nenabled = tr")
        self.assertEqual(info["LEVEL"], "INFO")

    def test_absent_config_is_created_with_defaults(self):
        info = self._load_with(None)
        self.assertEqual(info["LEVEL"], "INFO")
        self.assertEqual(info["STATUS"], "ok")
        self.assertEqual(
            info["DEBOUNCE"], "300", "the documented default delay"
        )


if __name__ == "__main__":
    unittest.main()
