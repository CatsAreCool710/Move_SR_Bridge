# test_step_toggle.py - Tests for the step-button light announcements
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
"""Tests for _install_step_hooks and its helpers.

These need no display hook, no config and no sr_bridge -- just a fake note
editor and an `announce` that appends to a list.
"""

import os
import sys
import types
import unittest

try:
    from unittest import mock
except ImportError:  # pragma: no cover
    import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stubs

FILLED = "NoteEditor.StepFilled"
EMPTY = "NoteEditor.StepEmpty"
MUTED = "NoteEditor.StepMuted"
DISABLED = "NoteEditor.StepDisabled"


class StepHelperTest(unittest.TestCase):
    """The pure helpers."""

    @classmethod
    def setUpClass(cls):
        cls.m = stubs.import_bridge()

    def test_toggle_text(self):
        self.assertEqual(self.m._step_toggle_text(4, True), "Step 5 on")
        self.assertEqual(self.m._step_toggle_text(4, False), "Step 5 off")
        self.assertEqual(self.m._step_toggle_text(0, True), "Step 1 on")
        self.assertEqual(self.m._step_toggle_text(15, False), "Step 16 off")

    def test_index_is_row_major(self):
        editor = stubs.FakeNoteEditor(width=4)
        # (x=3,y=0) and (x=0,y=3) are the discriminating pair: swapping x
        # and y is invisible on the diagonal and at (0,0).
        self.assertEqual(
            self.m._step_index(stubs.FakeStep((0, 3)), editor), 3
        )
        self.assertEqual(
            self.m._step_index(stubs.FakeStep((3, 0)), editor), 12
        )
        self.assertEqual(
            self.m._step_index(stubs.FakeStep((0, 0)), editor), 0
        )

    def test_index_uses_the_live_width(self):
        editor = stubs.FakeNoteEditor(width=8, step_count=32)
        self.assertEqual(
            self.m._step_index(stubs.FakeStep((1, 1)), editor), 9
        )

    def test_index_falls_back_when_width_is_unusable(self):
        # A bare note_editor.width would raise into the caller's catch-all
        # and kill the feature silently for the whole session.
        for width in (None, 0, -1, "4"):
            editor = stubs.FakeNoteEditor(width=width)
            self.assertEqual(
                self.m._step_index(stubs.FakeStep((1, 1)), editor), 5, width
            )
        editor = stubs.FakeNoteEditor()
        del editor.width
        self.assertEqual(
            self.m._step_index(stubs.FakeStep((1, 1)), editor), 5
        )

    def test_index_rejects_non_integer_coordinates(self):
        editor = stubs.FakeNoteEditor()
        for coordinate in ((None, 1), (1, None), ("a", "b")):
            self.assertIsNone(
                self.m._step_index(stubs.FakeStep(coordinate), editor)
            )

    def test_index_is_bounds_checked(self):
        editor = stubs.FakeNoteEditor(width=4, step_count=16)
        self.assertIsNone(
            self.m._step_index(stubs.FakeStep((5, 0)), editor)
        )
        # ...but an unreadable step_count must not silence a valid layout.
        editor = stubs.FakeNoteEditor(width=4)
        del editor.step_count
        self.assertEqual(
            self.m._step_index(stubs.FakeStep((5, 0)), editor), 20
        )

    def test_light_mapping(self):
        editor = stubs.FakeNoteEditor()
        editor.lights = {0: FILLED, 1: MUTED, 2: EMPTY}
        self.assertIs(self.m._step_light(editor, 0), True)
        self.assertIs(self.m._step_light(editor, 1), True)
        self.assertIs(self.m._step_light(editor, 2), False)

    def test_unknown_lights_are_none_not_off(self):
        # "off is anything that is not on" would announce a confident
        # "off" for a disabled step, a playhead frame, or any skin name
        # Ableton adds later. The last row is the one only a frozenset
        # pair can pass.
        editor = stubs.FakeNoteEditor()
        for name in (
            DISABLED,
            "NoteEditor.NoClip",
            "NoteEditor.StepTied",
            "NoteEditor.StepPartiallyTied",
            "NoteEditor.Playhead",
            None,
            "NoteEditor.SomethingNew",
        ):
            editor.lights = {0: name}
            self.assertIsNone(self.m._step_light(editor, 0), name)

    def test_light_survives_a_raising_editor(self):
        editor = stubs.FakeNoteEditor()
        editor._get_color_for_step = mock.Mock(side_effect=RuntimeError("boom"))
        self.assertIsNone(self.m._step_light(editor, 0))

        editor = stubs.FakeNoteEditor()
        editor._visible_steps = mock.Mock(side_effect=RuntimeError("boom"))
        self.assertIsNone(self.m._step_light(editor, 0))


class GetNoteEditorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = stubs.import_bridge()

    def test_reads_through_dict_get(self):
        # component_map["Step_Sequence"] on Live's real ComponentMap
        # constructs the whole step sequencer as a side effect.
        editor = stubs.FakeNoteEditor()
        surface = stubs.step_sequence_surface(note_editor=editor)
        self.assertIs(self.m._get_note_editor(surface), editor)

    def test_missing_component_map(self):
        self.assertIsNone(
            self.m._get_note_editor(types.SimpleNamespace())
        )
        self.assertIsNone(
            self.m._get_note_editor(types.SimpleNamespace(component_map=None))
        )

    def test_factory_without_note_editor_degrades_to_none(self):
        component_map = stubs.StepLookupProxy()
        dict.__setitem__(component_map, "Step_Sequence", object())
        surface = types.SimpleNamespace(component_map=component_map)
        self.assertIsNone(self.m._get_note_editor(surface))

    def test_raising_property_does_not_escape(self):
        class Raising(object):
            @property
            def note_editor(self):
                raise RuntimeError("boom")

        component_map = stubs.StepLookupProxy()
        dict.__setitem__(component_map, "Step_Sequence", Raising())
        surface = types.SimpleNamespace(component_map=component_map)
        self.assertIsNone(self.m._get_note_editor(surface))

    def test_non_dict_component_map_uses_the_subscript(self):
        editor = stubs.FakeNoteEditor()

        class Mapping(object):
            def __getitem__(self, key):
                assert key == "Step_Sequence"
                return stubs.FakeStepSequenceComponent(editor)

        surface = types.SimpleNamespace(component_map=Mapping())
        self.assertIs(self.m._get_note_editor(surface), editor)


class StepHookTest(unittest.TestCase):
    """_install_step_hooks: the wrapper, the listener and the restore."""

    @classmethod
    def setUpClass(cls):
        cls.m = stubs.import_bridge()

    def setUp(self):
        self.announced = []

    def _announce(self, index, is_on):
        self.announced.append((index, is_on))

    def _install(self, editor):
        unwrap = self.m._install_step_hooks(editor, self._announce)
        self.assertIsNotNone(unwrap, "hooks should install")
        self.addCleanup(unwrap)
        return unwrap

    @staticmethod
    def _toggle_to(value):
        """An 'original' that sets the light and fires synchronously."""

        def original(editor, step, can_add_or_remove):
            editor.lights[step.y * editor.width + step.x] = value
            editor.fire_clip_notes()

        return original

    def test_empty_to_filled_announces_on(self):
        editor = stubs.FakeNoteEditor(
            lights={4: EMPTY}, on_release=self._toggle_to(FILLED)
        )
        self._install(editor)
        editor._on_release_step(stubs.FakeStep((1, 0)), True)
        self.assertEqual(self.announced, [(4, True)])

    def test_filled_to_empty_announces_off(self):
        editor = stubs.FakeNoteEditor(
            lights={4: FILLED}, on_release=self._toggle_to(EMPTY)
        )
        self._install(editor)
        editor._on_release_step(stubs.FakeStep((1, 0)), True)
        self.assertEqual(self.announced, [(4, False)])

    def test_deferred_listener_still_announces(self):
        # Adding a `finally` that clears the pending record is the obvious
        # tidy-up, and it silently disables the feature wherever Live fires
        # the LOM listener after _on_release_step has returned.
        def original(editor, step, can_add_or_remove):
            editor.lights[4] = FILLED  # changed, but no event yet

        editor = stubs.FakeNoteEditor(lights={4: EMPTY}, on_release=original)
        self._install(editor)
        editor._on_release_step(stubs.FakeStep((1, 0)), True)
        self.assertEqual(self.announced, [])
        editor.fire_clip_notes()
        self.assertEqual(self.announced, [(4, True)])

    def test_a_chord_announces_once(self):
        # _add_note_in_step fires once per pitch, so clip_notes fires once
        # per pitch too. Consuming the record after announcing would give
        # three announcements for one tap.
        def original(editor, step, can_add_or_remove):
            editor.lights[4] = FILLED
            for _ in range(3):
                editor.fire_clip_notes()

        editor = stubs.FakeNoteEditor(lights={4: EMPTY}, on_release=original)
        self._install(editor)
        editor._on_release_step(stubs.FakeStep((1, 0)), True)
        self.assertEqual(self.announced, [(4, True)])

    def test_record_is_consumed_before_announcing(self):
        # Consuming after the announce still coalesces a plain chord, so
        # that case cannot tell the two orderings apart. Re-entrancy can:
        # if announcing re-enters the listener with the record still armed,
        # it announces again (and recurses). Clearing first makes the
        # nested call a no-op.
        editor = stubs.FakeNoteEditor(lights={4: EMPTY})

        def original(ed, step, can_add_or_remove):
            ed.lights[4] = FILLED
            ed.fire_clip_notes()

        editor._on_release = original

        reentered = []

        def announce(index, is_on):
            self.announced.append((index, is_on))
            if len(reentered) < 3:  # bounded, so a bug fails rather than hangs
                reentered.append(1)
                editor.fire_clip_notes()

        unwrap = self.m._install_step_hooks(editor, announce)
        self.addCleanup(unwrap)
        editor._on_release_step(stubs.FakeStep((1, 0)), True)
        self.assertEqual(self.announced, [(4, True)])

    def test_unchanged_light_is_silent(self):
        # A velocity edit modifies the clip without toggling anything. The
        # diff is what replaces every short-circuit we deliberately do not
        # mirror, so without this test it is untested.
        def original(editor, step, can_add_or_remove):
            editor.fire_clip_notes()

        editor = stubs.FakeNoteEditor(lights={4: FILLED}, on_release=original)
        self._install(editor)
        editor._on_release_step(stubs.FakeStep((1, 0)), True)
        self.assertEqual(self.announced, [])

    def test_clip_notes_without_a_gesture_is_silent(self):
        # Recording, undo, and edits made in Live's own UI.
        editor = stubs.FakeNoteEditor(lights={4: EMPTY})
        self._install(editor)
        editor.lights[4] = FILLED
        editor.fire_clip_notes()
        self.assertEqual(self.announced, [])

    def test_consecutive_gestures(self):
        editor = stubs.FakeNoteEditor(
            lights={4: EMPTY, 9: FILLED},
        )
        self._install(editor)

        editor._on_release = self._toggle_to(FILLED)
        editor._on_release_step(stubs.FakeStep((1, 0)), True)
        editor._on_release = self._toggle_to(EMPTY)
        editor._on_release_step(stubs.FakeStep((2, 1)), True)
        self.assertEqual(self.announced, [(4, True), (9, False)])

    def test_unreadable_before_light_never_arms(self):
        # Otherwise the first readable frame announces a change nobody
        # observed.
        def original(editor, step, can_add_or_remove):
            editor.lights[4] = FILLED
            editor.fire_clip_notes()

        editor = stubs.FakeNoteEditor(lights={4: DISABLED}, on_release=original)
        self._install(editor)
        editor._on_release_step(stubs.FakeStep((1, 0)), True)
        self.assertEqual(self.announced, [])

    def test_unreadable_after_light_is_silent(self):
        # `after != before` without the `after is not None` check would
        # announce "off" here, since None != True.
        def original(editor, step, can_add_or_remove):
            editor.lights[4] = DISABLED
            editor.fire_clip_notes()

        editor = stubs.FakeNoteEditor(lights={4: FILLED}, on_release=original)
        self._install(editor)
        editor._on_release_step(stubs.FakeStep((1, 0)), True)
        self.assertEqual(self.announced, [])

    def test_original_exception_propagates_unchanged(self):
        sentinel = RuntimeError("live blew up")

        def original(editor, step, can_add_or_remove):
            raise sentinel

        editor = stubs.FakeNoteEditor(lights={4: EMPTY}, on_release=original)
        self._install(editor)
        with self.assertRaises(RuntimeError) as caught:
            editor._on_release_step(stubs.FakeStep((1, 0)), True)
        self.assertIs(caught.exception, sentinel)

    def test_announce_failure_is_contained(self):
        def original(editor, step, can_add_or_remove):
            editor.lights[4] = FILLED
            editor.fire_clip_notes()

        editor = stubs.FakeNoteEditor(lights={4: EMPTY}, on_release=original)
        boom = mock.Mock(side_effect=RuntimeError("boom"))
        unwrap = self.m._install_step_hooks(editor, boom)
        self.addCleanup(unwrap)
        with mock.patch.object(self.m, "_log_failure") as log_failure:
            editor._on_release_step(stubs.FakeStep((1, 0)), True)
        self.assertTrue(log_failure.called)

    def test_prologue_failure_still_runs_the_original(self):
        # Putting the original call inside the prologue's try would let a
        # bad step object stop Live editing the clip.
        class Exploding(stubs.FakeStep):
            @property
            def x(self):
                raise RuntimeError("boom")

        editor = stubs.FakeNoteEditor(lights={4: EMPTY})
        self._install(editor)
        with mock.patch.object(self.m, "_log_failure") as log_failure:
            result = editor._on_release_step(Exploding((1, 0)), True)
        self.assertEqual(result, "original-return")
        self.assertEqual(len(editor.calls), 1)
        self.assertEqual(self.announced, [])
        self.assertTrue(log_failure.called)

    def test_return_value_passes_through(self):
        editor = stubs.FakeNoteEditor(lights={4: EMPTY})
        self._install(editor)
        self.assertEqual(
            editor._on_release_step(stubs.FakeStep((1, 0)), True),
            "original-return",
        )

    def test_unwrap_restores_the_class_method_and_the_listener(self):
        editor = stubs.FakeNoteEditor(lights={4: EMPTY})
        unwrap = self.m._install_step_hooks(editor, self._announce)
        self.assertIn("_on_release_step", vars(editor))
        unwrap()
        # setattr(original_bound_method) is behaviourally identical, so this
        # must be asserted on vars(): it would leave the class method
        # permanently shadowed by an instance attribute.
        self.assertNotIn("_on_release_step", vars(editor))
        self.assertNotIn(self.m._STEP_HOOK_MARKER, vars(editor))
        self.assertEqual(editor._listeners, [])

    def test_unwrap_leaves_a_foreign_patch_alone_but_still_unhooks(self):
        editor = stubs.FakeNoteEditor(lights={4: EMPTY})
        unwrap = self.m._install_step_hooks(editor, self._announce)
        foreign = lambda *a, **k: None  # noqa: E731
        editor._on_release_step = foreign
        unwrap()
        self.assertIs(editor._on_release_step, foreign)
        # ...and the listener, the half that can still speak, is gone.
        self.assertEqual(editor._listeners, [])

    def test_double_install_is_refused(self):
        editor = stubs.FakeNoteEditor(
            lights={4: EMPTY}, on_release=self._toggle_to(FILLED)
        )
        self._install(editor)
        self.assertIsNone(
            self.m._install_step_hooks(editor, self._announce)
        )
        editor._on_release_step(stubs.FakeStep((1, 0)), True)
        self.assertEqual(self.announced, [(4, True)])

    def test_no_note_editor(self):
        self.assertIsNone(self.m._install_step_hooks(None, self._announce))

    def test_partial_install_is_refused_outright(self):
        editor = stubs.FakeNoteEditor()
        # Shadow, not delete: the fakes live on the class, exactly as the
        # real component's methods do.
        editor.add_clip_notes_listener = None
        self.assertIsNone(self.m._install_step_hooks(editor, self._announce))
        # Nothing wrapped, so there is nothing left with no way to remove it.
        self.assertNotIn("_on_release_step", vars(editor))

        editor = stubs.FakeNoteEditor()
        editor._on_release_step = None
        self.assertIsNone(self.m._install_step_hooks(editor, self._announce))


if __name__ == "__main__":
    unittest.main()
