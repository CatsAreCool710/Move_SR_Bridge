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
    def __init__(self, lines=None, list_index=None, list_cursor_char=""):
        Content.__init__(self, lines)
        self.list_index = list_index
        # Live sends one char for the whole content, describing the
        # SELECTED row: '>' when that item opens a submenu, '-' for a leaf.
        self.list_cursor_char = list_cursor_char


class HorizontalListContent(Content):
    pass


class NotificationContent(Content):
    pass


# ---------------------------------------------------------------------------
# Fake step sequencer (mirrors ableton.v3 NoteEditorComponent)
# ---------------------------------------------------------------------------
class FakeStep(object):
    """Stands in for StepButtonControl.State.

    x/y are properties over `coordinate`, exactly as the real class derives
    them, so a subclass can make one *raise* -- which a SimpleNamespace
    cannot express, and which is the case a hasattr/None check misses.
    """

    def __init__(self, coordinate, is_active=True):
        self.coordinate = coordinate
        self.is_active = is_active

    @property
    def x(self):
        return self.coordinate[1]

    @property
    def y(self):
        return self.coordinate[0]


class FakeNoteEditor(object):
    """Fake note editor with the three methods the step hooks touch.

    They are defined on the CLASS on purpose: the restore assertion is
    `vars(note_editor)` being empty afterwards, which is unobservable if
    the originals live in the instance dict.

    `lights` is a mutable {index: skin_name} a test edits to simulate the
    clip changing.  `on_release` is what the "original" does when called --
    typically edit `lights` and then fire_clip_notes(), which is the real
    sequence; a test can also fire later, or not at all.
    """

    def __init__(self, width=4, step_count=16, lights=None, on_release=None):
        self.width = width
        self.step_count = step_count
        self.lights = dict(lights or {})
        self._on_release = on_release
        self._listeners = []
        self.calls = []

    # --- the method the hooks wrap -------------------------------------
    def _on_release_step(self, step, can_add_or_remove=False):
        self.calls.append(("release", step, can_add_or_remove))
        if self._on_release is not None:
            self._on_release(self, step, can_add_or_remove)
        return "original-return"

    # --- the light read ------------------------------------------------
    def _visible_steps(self):
        return {i: object() for i in range(self.step_count)}

    def _get_color_for_step(self, index, visible_steps):
        return self.lights.get(index, "NoteEditor.StepEmpty")

    # --- the clip_notes event triad ableton.v2 generates ----------------
    def add_clip_notes_listener(self, fn):
        self._listeners.append(fn)

    def remove_clip_notes_listener(self, fn):
        self._listeners.remove(fn)

    def clip_notes_has_listener(self, fn):
        return fn in self._listeners

    def fire_clip_notes(self):
        for fn in list(self._listeners):
            fn()


class FakeStepSequenceComponent(object):
    """note_editor is a property, matching the v3 base, so a test can make
    it raise."""

    def __init__(self, note_editor):
        self._note_editor = note_editor

    @property
    def note_editor(self):
        return self._note_editor


class StepLookupProxy(dict):
    """dict whose __getitem__ raises, proving _get_note_editor uses dict.get.

    Deliberately a separate copy from test_display_hook.py's _LookupProxy:
    that file is dense with subtle assertions and this change has no reason
    to touch it.
    """

    def __getitem__(self, key):
        raise AssertionError(
            "component_map[%r] must not be used -- Live's ComponentMap "
            "constructs the component as a side effect" % (key,)
        )


def step_sequence_surface(display=None, note_editor=None):
    """A control surface carrying a Step_Sequence component."""
    if note_editor is None:
        note_editor = FakeNoteEditor()
    component_map = StepLookupProxy()
    dict.__setitem__(
        component_map, "Step_Sequence", FakeStepSequenceComponent(note_editor)
    )
    return types.SimpleNamespace(
        display=display, song=None, component_map=component_map
    )


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
