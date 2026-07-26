# stubs.py - Test scaffolding for importing Move_SR_Bridge outside Live
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
Shared scaffolding for the Move-SR-Bridge test suite.

The package under test imports `Move`, which only exists inside Ableton
Live.  This module fakes it convincingly enough to import the real code,
then hands back the imported module.

Two details matter and are easy to get wrong:

1.  The fake `Move` package must expose a `display_util` submodule with
    real classes.  `__init__.py` populates `_content_types` from it at
    import time and every branch of `_format_content()` is guarded by
    `isinstance` against those classes.  Without them `_content_types`
    stays empty, every branch is skipped, and the formatting tests would
    silently only ever exercise the final fallback -- passing while
    testing nothing.

2.  HOME is redirected to a temp directory *before* import, because
    importing the package creates and opens
    `~/.move_sr_bridge/Move_SR_Bridge.log`.  Tests must not append to the
    user's real log.
"""

import atexit
import logging
import os
import shutil
import sys
import tempfile
import types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_temp_home = None


# ---------------------------------------------------------------------------
# Fake display content classes (mirror Move.display_util)
# ---------------------------------------------------------------------------
class Content(object):
    def __init__(self, lines=None):
        self.lines = lines or []


class VerticalListContent(Content):
    def __init__(self, lines=None, list_index=None):
        Content.__init__(self, lines)
        self.list_index = list_index


class HorizontalListContent(Content):
    pass


class NotificationContent(Content):
    pass


# ---------------------------------------------------------------------------
# Fake Move package
# ---------------------------------------------------------------------------
class FakeMoveControlSurface(object):
    """Stands in for the stock Move control surface base class."""

    def __init__(self, *args, **kwargs):
        self.display = None

    def on_identified(self, response_bytes):
        pass

    def disconnect(self):
        pass


def _install_fake_move_package():
    display_util = types.ModuleType("Move.display_util")
    display_util.Content = Content
    display_util.VerticalListContent = VerticalListContent
    display_util.HorizontalListContent = HorizontalListContent
    display_util.NotificationContent = NotificationContent

    move = types.ModuleType("Move")
    move.__path__ = []  # mark as a package so `Move.display_util` resolves
    move.get_capabilities = lambda: {}
    move.Move = FakeMoveControlSurface
    move.Specification = object()
    move.display_util = display_util

    sys.modules["Move"] = move
    sys.modules["Move.display_util"] = display_util


def _redirect_home():
    """Point HOME at a temp dir so tests never touch ~/.move_sr_bridge.

    Registered for cleanup at interpreter exit: the directory used to be
    left behind, one per run, each holding a log file nothing would ever
    read again.
    """
    global _temp_home
    if _temp_home is None:
        _temp_home = tempfile.mkdtemp(prefix="move_sr_bridge_test_home_")
        atexit.register(shutil.rmtree, _temp_home, True)
    os.environ["HOME"] = _temp_home
    os.environ["USERPROFILE"] = _temp_home
    return _temp_home


def import_bridge():
    """Import (once) and return the real Move_SR_Bridge package."""
    # Redirect first, unconditionally, and only then take the early exit.
    # Doing it the other way round meant a runner that had already imported
    # the package (a plugin, a conftest, an earlier `import Move_SR_Bridge`)
    # left HOME pointing at the real one -- so the safety net was missing
    # exactly when something unusual was going on.
    _redirect_home()
    if "Move_SR_Bridge" in sys.modules:
        return sys.modules["Move_SR_Bridge"]

    _install_fake_move_package()
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)

    import Move_SR_Bridge

    return Move_SR_Bridge


def import_sr_bridge():
    """Import (once) and return the sr_bridge module.

    Reached through the package rather than as a bare module, because
    that is how it is imported at runtime (`from . import sr_bridge`) and
    the module identity has to match for patching to take effect.
    """
    import_bridge()
    from Move_SR_Bridge import sr_bridge

    return sr_bridge


def import_sr_helper():
    """Import (once) and return the sr_helper module."""
    # Redirected before the early exit, for the same reason as import_bridge.
    _redirect_home()
    if "sr_helper" in sys.modules:
        return sys.modules["sr_helper"]

    package_dir = os.path.join(REPO_ROOT, "Move_SR_Bridge")
    if package_dir not in sys.path:
        sys.path.insert(0, package_dir)

    import sr_helper

    # sr_helper logs to stderr on import.  Several protocol tests exercise
    # its warning paths on purpose, and the output buries the test results.
    # Set MOVE_SR_TEST_VERBOSE=1 to see it while debugging a failure.
    if not os.environ.get("MOVE_SR_TEST_VERBOSE"):
        sr_helper.log.handlers = [logging.NullHandler()]
        sr_helper.log.propagate = False

    return sr_helper
