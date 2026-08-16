# test_display_hook.py - Announcement flow through the display hook
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
Tests for what the installed display hook actually announces.

Debounce is disabled so speech is synchronous and assertions are exact;
the debounce path itself is covered in test_helper_lifecycle.py.
"""

import configparser
import os
import sys
import threading
import time
import types
import unittest

try:
    from unittest import mock
except ImportError:  # pragma: no cover
    import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stubs


class DisplayHookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = stubs.import_bridge()

    def setUp(self):
        self.spoken = []
        # Records what Live's own display method was handed. The OLED keeps
        # working only because the hook calls this for every frame, outside
        # its try and never behind an early return -- so it has to be
        # observable, not a black hole.
        self.rendered = []
        self.original_display = self.rendered.append
        self.display = types.SimpleNamespace(display=self.original_display)
        self.surface = types.SimpleNamespace(display=self.display, song=None)

        # `dialog` is a separate command: the helper drops it while Live
        # is frontmost, so it must not be confused with plain speech.
        self.dialogs = []
        # Braille was previously thrown away by every fake in the suite, so
        # nothing checked the hook sends it at all.
        self.brailled = []
        fake_bridge = types.SimpleNamespace(
            speak=self.spoken.append,
            braille=self.brailled.append,
            dialog=self.dialogs.append,
        )

        cfg = configparser.ConfigParser()
        cfg.read_dict({
            "debounce": {"enabled": "false", "delay_ms": "0"},
            "logging": {"level": "INFO"},
        })

        patchers = [
            # `from . import sr_bridge` resolves the package attribute, so
            # patching sys.modules alone would be ignored.
            mock.patch.object(self.m, "sr_bridge", fake_bridge, create=True),
            mock.patch.dict(
                sys.modules, {"Move_SR_Bridge.sr_bridge": fake_bridge}
            ),
            mock.patch.object(self.m, "_cfg", cfg),
            # No Live here, so nothing is ever "urgent" unless a test says so.
            mock.patch.object(self.m, "_dialog_is_open", lambda: False),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

        self.teardown_hook = self.m._install_display_hook(self.surface)
        self.assertIsNotNone(self.teardown_hook, "hook should install")
        del self.spoken[:]   # drop "Move connected"
        del self.brailled[:]
        del self.rendered[:]

    def show(self, content):
        self.display.display(content)

    # -- braille tracks speech -----------------------------------------
    def test_announcements_go_to_braille_as_well_as_speech(self):
        # On Windows the braille display is driven by these sends. (On macOS
        # sr_bridge drops them, because VoiceOver brailles what it speaks --
        # but that decision belongs to sr_bridge, not to the hook.)
        self.show(stubs.HorizontalListContent(lines=["Cutoff", "800 Hz"]))
        self.assertEqual(self.spoken, ["Cutoff: 800 Hz"])
        self.assertEqual(
            self.brailled,
            self.spoken,
            "braille must carry the same text as speech",
        )

    # -- Live's own rendering must always happen -----------------------
    def test_every_frame_reaches_lives_display_method(self):
        # Including the ones we deliberately say nothing about. The OLED is
        # not ours to break: suppressing speech is the whole job, dropping
        # a frame is a bug the user sees as a frozen screen.
        frames = [
            stubs.HorizontalListContent(lines=["Cutoff", "800 Hz"]),
            stubs.HorizontalListContent(lines=["Cutoff", "800 Hz"]),  # unchanged
            stubs.NotificationContent(lines=["Copy..."]),
            stubs.Content(lines=[]),                                  # empty
        ]
        for f in frames:
            self.show(f)

        self.assertEqual(
            self.rendered,
            frames,
            "every frame must be forwarded to Live's display method, "
            "whatever we decided about speech",
        )

    def test_lives_display_method_runs_even_when_our_hook_raises(self):
        # The catch-all in _intercepted_display exists for exactly this.
        # If an exception could skip the forwarding call, one bug in our
        # formatting would freeze the Move's screen.
        boom = stubs.HorizontalListContent(lines=["Cutoff", "800 Hz"])
        with mock.patch.object(
            self.m, "_format_content", side_effect=RuntimeError("boom")
        ):
            self.show(boom)

        self.assertEqual(self.spoken, [], "nothing should have been spoken")
        self.assertEqual(
            self.rendered,
            [boom],
            "a failure in our own code must not cost Live its render",
        )

    def test_teardown_restores_lives_display_method(self):
        # While the patch is in place, a frame arriving after disconnect()
        # re-enters the hook, can start a fresh debounce timer, and can
        # speak after "Move disconnected".
        self.assertIsNot(
            self.display.display,
            self.original_display,
            "setUp should have left our hook installed",
        )

        self.teardown_hook()

        self.assertIs(
            self.display.display,
            self.original_display,
            "teardown must put Live's own display method back",
        )
        del self.spoken[:]
        self.show(stubs.HorizontalListContent(lines=["Cutoff", "800 Hz"]))
        self.assertEqual(
            self.spoken, [], "a frame after teardown must not be announced"
        )

    # -- the notification-revert regression ----------------------------
    def test_notification_does_not_cause_the_screen_to_repeat(self):
        main = stubs.HorizontalListContent(lines=["Cutoff", "800 Hz"])

        self.show(main)
        self.show(stubs.NotificationContent(lines=["Copy..."]))
        self.show(stubs.HorizontalListContent(lines=["Cutoff", "800 Hz"]))

        self.assertEqual(
            self.spoken,
            ["Cutoff: 800 Hz", "Copy..."],
            "the unchanged screen underneath a notification must not be "
            "announced again when the notification clears -- Live raises "
            "notifications constantly, so this roughly doubles speech",
        )

    def test_screen_change_across_a_notification_is_still_announced(self):
        self.show(stubs.HorizontalListContent(lines=["Cutoff", "800 Hz"]))
        self.show(stubs.NotificationContent(lines=["Copy..."]))
        self.show(stubs.HorizontalListContent(lines=["Cutoff", "900 Hz"]))

        self.assertEqual(
            self.spoken, ["Cutoff: 800 Hz", "Copy...", "Cutoff: 900 Hz"]
        )

    def test_repeated_notification_is_announced_once(self):
        self.show(stubs.NotificationContent(lines=["Undo"]))
        self.show(stubs.NotificationContent(lines=["Undo"]))
        self.assertEqual(self.spoken, ["Undo"])

    def test_same_notification_after_a_screen_change_is_announced_again(self):
        self.show(stubs.NotificationContent(lines=["Undo"]))
        self.show(stubs.HorizontalListContent(lines=["Cutoff", "800 Hz"]))
        self.show(stubs.NotificationContent(lines=["Undo"]))
        self.assertEqual(self.spoken, ["Undo", "Cutoff: 800 Hz", "Undo"])

    # -- ordinary change detection still holds -------------------------
    def test_unchanged_screen_is_not_repeated(self):
        for _ in range(3):
            self.show(stubs.HorizontalListContent(lines=["Cutoff", "800 Hz"]))
        self.assertEqual(self.spoken, ["Cutoff: 800 Hz"])

    def test_distinct_screens_are_each_announced(self):
        self.show(stubs.HorizontalListContent(lines=["1-MIDI", "No Device"]))
        self.show(stubs.HorizontalListContent(lines=["2-MIDI", "No Device"]))
        self.assertEqual(
            self.spoken,
            ["1-MIDI: No Device", "2-MIDI: No Device"],
            "identical-sounding screens on different tracks are still "
            "distinct updates",
        )

    def test_empty_content_says_nothing(self):
        self.show(stubs.Content(lines=[]))
        self.show(stubs.Content(lines=["  "]))
        self.assertEqual(self.spoken, [])

    # -- speech normalisation reaches the wire -------------------------
    def test_automation_glyph_never_reaches_the_screen_reader(self):
        self.show(
            stubs.HorizontalListContent(lines=[u"\ue044Cutoff", "800 Hz"])
        )
        self.assertEqual(self.spoken, ["automated Cutoff: 800 Hz"])
        for said in self.spoken:
            self.assertFalse(
                any(u"\ue000" <= ch <= u"\uf8ff" for ch in said),
                "an icon-font glyph must never be sent to speech",
            )

    def test_redundant_track_name_is_still_stripped(self):
        # Live announces the selected track itself; we speak only the value.
        self.surface.song = types.SimpleNamespace(
            view=types.SimpleNamespace(
                selected_track=types.SimpleNamespace(name="Bass"),
                selected_scene=types.SimpleNamespace(name="Scene 1"),
            )
        )
        self.show(stubs.HorizontalListContent(lines=["Bass", "0 dB"]))
        self.assertEqual(self.spoken, ["0 dB"])

    def test_automated_parameter_still_matches_a_track_name(self):
        # Two things at once. The glyph must not leak into the match key,
        # or the redundant name never strips -- but stripping the name must
        # not take the automation marker with it, since the marker rides on
        # the name. Losing it would mean a blind user turning an automated
        # parameter on the selected track hears a bare "0 dB" and has no
        # way to tell it is automated, which is exactly what the whole
        # _AUTOMATION_CHAR path exists to prevent.
        self.surface.song = types.SimpleNamespace(
            view=types.SimpleNamespace(
                selected_track=types.SimpleNamespace(name="Bass"),
                selected_scene=None,
            )
        )
        self.show(stubs.HorizontalListContent(lines=[u"\ue044Bass", "0 dB"]))
        self.assertEqual(self.spoken, ["automated, 0 dB"])

    def test_unautomated_match_does_not_gain_an_automation_marker(self):
        # The other half of the above: "automated" must appear only when
        # Live actually drew the glyph.
        self.surface.song = types.SimpleNamespace(
            view=types.SimpleNamespace(
                selected_track=types.SimpleNamespace(name="Bass"),
                selected_scene=None,
            )
        )
        self.show(stubs.HorizontalListContent(lines=["Bass", "0 dB"]))
        self.assertEqual(self.spoken, ["0 dB"])


class FakeParameter(object):
    """Stand-in for a Live DeviceParameter.

    Live's own `parameter_view` renders a parameter's value with
    `str(active_parameter)` in one of its branches, which is why
    `_parameter_value_text()` uses the same.
    """

    def __init__(self, value_string="-6.0 dB"):
        self.value_string = value_string

    def __str__(self):
        return self.value_string


class CriticalDisplayStateTest(unittest.TestCase):
    """Screens Live paints *over* the main view, then takes away again.

    Live's `Move/display.py: in_critical_display_state()` is
        active_parameter.parameter is not None
        or firmware.shut_down_state != none
        or dialog.any_dialog_open
    Each of those renders an overlay: the main view is unchanged
    underneath and comes straight back. Announcing it a second time on the
    way back is pure noise -- the same defect the notification handling
    already solves.
    """

    @classmethod
    def setUpClass(cls):
        cls.m = stubs.import_bridge()

    def setUp(self):
        self.spoken = []
        self.display = types.SimpleNamespace(display=lambda content: None)
        # component_map is what ControlSurfaceMappingMixin.__init__ sets;
        # 'Active_Parameter' is the key Live's own component map uses.
        self.active_parameter = [None]
        component_map = _LookupProxy(self.active_parameter)
        self.surface = types.SimpleNamespace(
            display=self.display, song=None, component_map=component_map
        )
        self.dialog_open = [False]

        # `dialog` is a separate command: the helper drops it while Live
        # is frontmost, so it must not be confused with plain speech.
        self.dialogs = []
        fake_bridge = types.SimpleNamespace(
            speak=self.spoken.append,
            braille=lambda text: None,
            dialog=self.dialogs.append,
        )
        cfg = configparser.ConfigParser()
        cfg.read_dict({
            "debounce": {"enabled": "false", "delay_ms": "0"},
            "logging": {"level": "INFO"},
        })
        patchers = [
            mock.patch.object(self.m, "sr_bridge", fake_bridge, create=True),
            mock.patch.dict(
                sys.modules, {"Move_SR_Bridge.sr_bridge": fake_bridge}
            ),
            mock.patch.object(self.m, "_cfg", cfg),
            mock.patch.object(
                self.m, "_dialog_is_open", lambda: self.dialog_open[0]
            ),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        self.assertIsNotNone(
            self.m._install_display_hook(self.surface), "hook should install"
        )
        del self.spoken[:]

    def show(self, content):
        self.display.display(content)

    def main_screen(self):
        return stubs.HorizontalListContent(lines=["2-MIDI", "No Device"])

    # -- the encoder-touch regression ----------------------------------
    def test_touching_an_encoder_does_not_repeat_the_screen_underneath(self):
        # Reproduced from the real log:
        #   Speaking: Volume
        #   Speaking: No Device      <- 1.3s later, nothing had changed
        self.show(self.main_screen())
        self.assertEqual(self.spoken, ["2-MIDI: No Device"])

        self.active_parameter[0] = FakeParameter("-6.0 dB")
        self.show(stubs.Content(lines=["Volume", "", ""]))

        self.active_parameter[0] = None
        self.show(self.main_screen())

        self.assertEqual(
            self.spoken,
            ["2-MIDI: No Device", "Volume, -6.0 dB"],
            "the screen underneath an encoder overlay is unchanged when the "
            "overlay clears; announcing it again is noise",
        )

    def test_master_volume_overlay_announces_the_level(self):
        # Live renders Content(lines=['Volume', '', ''], value=<0-1 float>)
        # for the master volume encoder -- the level is ONLY in the bar
        # graphic, so speech had the parameter name and no value at all.
        self.active_parameter[0] = FakeParameter("-11.5 dB")
        self.show(stubs.Content(lines=["Volume", "", ""]))
        self.assertEqual(
            self.spoken,
            ["Volume, -11.5 dB"],
            "a blind user turning the master volume must hear the level",
        )

    def test_overlay_that_already_has_a_value_is_not_doubled(self):
        # Every other parameter_view branch puts a value string in lines.
        self.active_parameter[0] = FakeParameter("800 Hz")
        self.show(stubs.Content(lines=["Cutoff", "", "800 Hz"]))
        self.assertEqual(self.spoken, ["Cutoff, 800 Hz"])

    def test_a_genuinely_new_screen_after_an_overlay_is_announced(self):
        self.show(self.main_screen())
        self.active_parameter[0] = FakeParameter("-6.0 dB")
        self.show(stubs.Content(lines=["Volume", "", ""]))
        self.active_parameter[0] = None
        self.show(stubs.HorizontalListContent(lines=["3-Audio", "No Clip"]))
        self.assertEqual(
            self.spoken,
            ["2-MIDI: No Device", "Volume, -6.0 dB", "3-Audio: No Clip"],
            "suppressing the revert must not suppress a real change",
        )

    def test_repeated_encoder_moves_are_each_announced(self):
        self.active_parameter[0] = FakeParameter("-6.0 dB")
        self.show(stubs.Content(lines=["Volume", "", ""]))
        self.active_parameter[0] = FakeParameter("-7.0 dB")
        self.show(stubs.Content(lines=["Volume", "", ""]))
        self.assertEqual(self.spoken, ["Volume, -6.0 dB", "Volume, -7.0 dB"])

    # -- the modal-dialog regression -----------------------------------
    def test_dialog_screen_flap_is_announced_once(self):
        # Reproduced from the real log: while one dialog was open Live
        # rendered the message, then the view underneath, then the message
        # again -- because the Move's cached any_dialog_open lags
        # open_dialog_count.
        self.show(self.main_screen())
        del self.spoken[:]

        self.dialog_open[0] = True
        msg = "Live is showing a dialog that needs your attention."
        self.show(stubs.Content(lines=[msg]))
        self.show(self.main_screen())        # Live's flap
        self.show(stubs.Content(lines=[msg]))
        self.show(self.main_screen())

        self.assertEqual(
            self.dialogs.count(msg), 1,
            "the dialog message must not repeat as Live flaps",
        )
        self.assertEqual(
            self.dialogs.count("2-MIDI: No Device"), 1,
            "nor must the screen underneath it",
        )

    def test_dialog_message_is_announced_even_if_the_flap_comes_first(self):
        # The flap can present the stale main view BEFORE the dialog
        # message. Spending the episode's announcement on the first screen
        # seen would then never tell the user there is a dialog at all --
        # which is the whole point of the message.
        self.show(self.main_screen())
        del self.spoken[:]

        self.dialog_open[0] = True
        msg = "Live is showing a dialog that needs your attention."
        self.show(self.main_screen())        # flap arrives first
        self.show(stubs.Content(lines=[msg]))

        self.assertIn(
            msg, self.dialogs,
            "the dialog message must be announced whenever it appears, not "
            "only when it happens to render first",
        )

    def test_screen_underneath_a_dialog_is_not_repeated_on_dismiss(self):
        self.show(self.main_screen())
        self.dialog_open[0] = True
        self.show(stubs.Content(
            lines=["Live is showing a dialog that needs your attention."]
        ))
        del self.spoken[:]

        self.dialog_open[0] = False
        self.show(self.main_screen())
        self.assertEqual(
            self.spoken, [],
            "dismissing a dialog returns to the screen the user was already "
            "on; that is not a change",
        )

    def test_change_made_by_a_dialog_is_announced_on_dismiss(self):
        self.show(self.main_screen())
        self.dialog_open[0] = True
        self.show(stubs.Content(
            lines=["Live is showing a dialog that needs your attention."]
        ))
        del self.spoken[:]

        self.dialog_open[0] = False
        self.show(stubs.HorizontalListContent(lines=["1-MIDI", "Wavetable"]))
        self.assertEqual(self.spoken, ["1-MIDI: Wavetable"])

    def test_a_second_dialog_is_announced_again(self):
        msg = "Live is showing a dialog that needs your attention."
        self.dialog_open[0] = True
        self.show(stubs.Content(lines=[msg]))
        self.dialog_open[0] = False
        self.show(self.main_screen())
        del self.spoken[:]
        del self.dialogs[:]

        self.dialog_open[0] = True
        self.show(stubs.Content(lines=[msg]))
        self.assertEqual(
            self.dialogs, [msg],
            "the per-episode dedupe must reset when the dialog closes",
        )

    def test_lives_real_dialog_text_is_preferred(self):
        # Application.current_dialog_message is "Text of the last dialog
        # that appeared". "Save changes to Untitled before closing?" is the
        # question the user has to answer; the Move's own screen only says
        # a dialog exists.
        real = 'Save changes to "Untitled" before closing?'
        with mock.patch.object(self.m, "_get_dialog_message", lambda: real):
            self.dialog_open[0] = True
            self.show(stubs.Content(
                lines=["Live is showing a dialog that needs your attention."]
            ))
        self.assertEqual(self.dialogs, [real])

    def test_falls_back_to_the_oled_text_when_live_offers_none(self):
        # current_dialog_message is read defensively -- a Live version that
        # does not expose it must not cost the announcement entirely.
        generic = "Live is showing a dialog that needs your attention."
        with mock.patch.object(self.m, "_get_dialog_message", lambda: None):
            self.dialog_open[0] = True
            self.show(stubs.Content(lines=[generic]))
        self.assertEqual(self.dialogs, [generic])

    def test_dialog_probe_never_raises(self):
        # Runs while a modal dialog has Live's UI blocked; it must not be
        # the thing that turns a dialog into a broken control surface.
        class Exploding(object):
            @property
            def current_dialog_message(self):
                raise RuntimeError("boom")

        fake_live = types.SimpleNamespace(
            Application=types.SimpleNamespace(
                get_application=lambda: Exploding()
            )
        )
        with mock.patch.object(self.m, "_Live", fake_live):
            self.assertIsNone(self.m._get_dialog_message())

    def test_dialog_message_is_not_read_on_every_redraw(self):
        # Live redraws ~5x a second, and keeps doing it for the whole time
        # a dialog is up (35s in one measured log). Resolving the dialog
        # text per redraw meant a Live API read on Live's own callback
        # thread at that rate; it must be per distinct screen instead.
        reads = []

        def counting_read():
            reads.append(1)
            return "Delete this device?"

        with mock.patch.object(
            self.m, "_get_dialog_message", counting_read
        ):
            self.dialog_open[0] = True
            for _ in range(50):
                self.show(stubs.Content(
                    lines=["Live is showing a dialog that needs your attention."]
                ))

        self.assertEqual(
            len(reads), 1,
            "the dialog text must be resolved once per distinct screen, "
            "not once per redraw",
        )
        self.assertEqual(self.dialogs, ["Delete this device?"])

    def test_two_screens_sharing_one_dialog_text_speak_once(self):
        # The flap shows different screens while the same dialog is open.
        # Both resolve to the same current_dialog_message, and announcing
        # it per screen would be exactly the repetition this branch exists
        # to stop.
        with mock.patch.object(
            self.m, "_get_dialog_message", lambda: "Delete this device?"
        ):
            self.dialog_open[0] = True
            self.show(stubs.Content(
                lines=["Live is showing a dialog that needs your attention."]
            ))
            self.show(self.main_screen())      # the flap
        self.assertEqual(
            self.dialogs, ["Delete this device?"],
            "one dialog, one announcement -- however many screens Live "
            "renders behind it",
        )

    def test_missing_dialog_message_property_is_treated_as_absent(self):
        # Live 12 does expose it (it is in _MxDCore/LomTypes.pyc), but the
        # caller must survive a Live that does not.
        fake_live = types.SimpleNamespace(
            Application=types.SimpleNamespace(
                get_application=lambda: types.SimpleNamespace()
            )
        )
        with mock.patch.object(self.m, "_Live", fake_live):
            self.assertIsNone(self.m._get_dialog_message())

    def test_dialog_message_is_returned_when_live_reports_one(self):
        fake_live = types.SimpleNamespace(
            Application=types.SimpleNamespace(
                get_application=lambda: types.SimpleNamespace(
                    current_dialog_message="  Delete this device?  "
                )
            )
        )
        with mock.patch.object(self.m, "_Live", fake_live):
            self.assertEqual(
                self.m._get_dialog_message(), "Delete this device?"
            )

    def test_empty_dialog_message_is_treated_as_absent(self):
        # "Empty if all dialogs just disappeared" -- must not announce "".
        fake_live = types.SimpleNamespace(
            Application=types.SimpleNamespace(
                get_application=lambda: types.SimpleNamespace(
                    current_dialog_message="   "
                )
            )
        )
        with mock.patch.object(self.m, "_Live", fake_live):
            self.assertIsNone(self.m._get_dialog_message())

    # -- the shutdown prompt --------------------------------------------
    def test_shutdown_prompt_does_not_repeat_the_screen_underneath(self):
        self.show(self.main_screen())
        self.show(stubs.Content(lines=["Press wheel to", "shut down"]))
        self.show(self.main_screen())
        self.assertEqual(
            self.spoken,
            ["2-MIDI: No Device", "Press wheel to shut down"],
            "the shutdown prompt is an overlay too -- cancelling it returns "
            "to an unchanged screen",
        )

    # -- the surface may not have the component at all -------------------
    def test_missing_component_map_is_harmless(self):
        bare = types.SimpleNamespace(display=self.display, song=None)
        self.assertIsNone(self.m._get_active_parameter(bare))

    def test_component_map_that_raises_is_harmless(self):
        class Exploding(object):
            def __getitem__(self, key):
                raise KeyError(key)

        surface = types.SimpleNamespace(component_map=Exploding())
        self.assertIsNone(self.m._get_active_parameter(surface))


class _LookupProxy(dict):
    """Stand-in for Live's ComponentMap, which is a dict subclass.

    Subclassing dict on purpose: `_get_active_parameter()` reads through
    `dict.get` precisely to avoid Live's ComponentMap.__getitem__, which
    lazily constructs an absent component. A non-dict fake would exercise
    the fallback branch instead of the one that actually runs in Live.
    """

    def __init__(self, parameter_slot):
        super(_LookupProxy, self).__init__()
        self["Active_Parameter"] = _FakeActiveParameterComponent(
            parameter_slot
        )

    def __getitem__(self, key):
        raise AssertionError(
            "_get_active_parameter must not use ComponentMap.__getitem__ -- "
            "it lazily constructs components as a side effect"
        )


class _FakeActiveParameterComponent(object):
    """Live's ActiveParameterComponent exposes `parameter` as a property."""

    def __init__(self, parameter_slot):
        self._slot = parameter_slot

    @property
    def parameter(self):
        return self._slot[0]


class UrgentBypassTest(unittest.TestCase):
    """Urgent screens are spoken immediately, not after the debounce."""

    @classmethod
    def setUpClass(cls):
        cls.m = stubs.import_bridge()

    def setUp(self):
        self.spoken = []
        self.display = types.SimpleNamespace(display=lambda content: None)
        self.surface = types.SimpleNamespace(display=self.display, song=None)
        # `dialog` is a separate command: the helper drops it while Live
        # is frontmost, so it must not be confused with plain speech.
        self.dialogs = []
        fake_bridge = types.SimpleNamespace(
            speak=self.spoken.append,
            braille=lambda text: None,
            dialog=self.dialogs.append,
        )
        cfg = configparser.ConfigParser()
        # Debounce ON with a long delay: anything non-urgent stays silent
        # for the duration of the test, so anything we hear bypassed it.
        cfg.read_dict({
            "debounce": {"enabled": "true", "delay_ms": "30000"},
            "logging": {"level": "INFO"},
        })
        self.dialog_open = [False]
        patchers = [
            mock.patch.object(self.m, "sr_bridge", fake_bridge, create=True),
            mock.patch.dict(
                sys.modules, {"Move_SR_Bridge.sr_bridge": fake_bridge}
            ),
            mock.patch.object(self.m, "_cfg", cfg),
            mock.patch.object(
                self.m, "_dialog_is_open", lambda: self.dialog_open[0]
            ),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        cancel = self.m._install_display_hook(self.surface)
        self.addCleanup(cancel)
        del self.spoken[:]

    def test_ordinary_screen_waits_for_the_debounce(self):
        self.display.display(
            stubs.HorizontalListContent(lines=["Cutoff", "800 Hz"])
        )
        self.assertEqual(self.spoken, [], "should still be queued")

    def test_shutdown_prompt_bypasses_the_debounce(self):
        self.display.display(
            stubs.Content(lines=["Press wheel to", "shut down"])
        )
        self.assertEqual(self.spoken, ["Press wheel to shut down"])

    def test_open_dialog_bypasses_the_debounce(self):
        self.dialog_open[0] = True
        self.display.display(
            stubs.Content(
                lines=["Live is showing a dialog that needs your attention."]
            )
        )
        self.assertEqual(
            self.dialogs,
            ["Live is showing a dialog that needs your attention."],
            "a modal dialog blocks Live entirely -- it must not wait",
        )
        self.assertEqual(
            self.spoken, [],
            "and it must go out as a dialog, not as plain speech -- the "
            "helper applies a suppression policy to dialogs only",
        )

    def test_urgent_message_drops_queued_chatter(self):
        self.display.display(
            stubs.HorizontalListContent(lines=["Cutoff", "800 Hz"])
        )
        self.display.display(
            stubs.Content(lines=["Press wheel to", "shut down"])
        )
        self.assertEqual(
            self.spoken,
            ["Press wheel to shut down"],
            "the queued announcement must be dropped, not spoken after",
        )


class ConfigValueTest(unittest.TestCase):
    """_cfg_value: the one place a config read can fail."""

    @classmethod
    def setUpClass(cls):
        cls.m = stubs.import_bridge()

    def _with_config(self, mapping):
        cfg = configparser.ConfigParser()
        cfg.read_dict(mapping)
        patcher = mock.patch.object(self.m, "_cfg", cfg)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reads_a_present_value(self):
        self._with_config({"debounce": {"enabled": "false", "delay_ms": "50"}})
        self.assertIs(self.m._cfg_value("debounce", "enabled", True), False)
        self.assertEqual(self.m._cfg_value("debounce", "delay_ms", 300), 50)

    def test_missing_section_returns_the_default_quietly(self):
        # The normal case for anyone upgrading: config.py only writes the
        # file when it does not exist, so an old config.ini has no [speech].
        #
        # The catch-all would return the default here even without
        # `fallback=`, so asserting the value alone proves nothing. What
        # `fallback=` actually buys is *silence*: without it every
        # upgrading user gets a spurious warning on every launch for a
        # config that is doing nothing wrong.
        self._with_config({"logging": {"level": "INFO"}})
        with mock.patch.object(self.m.logger, "warning") as warn:
            self.assertIs(self.m._cfg_value("speech", "step_toggles", True), True)
        self.assertFalse(
            warn.called,
            "a missing section is the normal upgrade path, not a fault",
        )

    def test_missing_option_returns_the_default_quietly(self):
        self._with_config({"speech": {}})
        with mock.patch.object(self.m.logger, "warning") as warn:
            self.assertIs(self.m._cfg_value("speech", "step_toggles", True), True)
        self.assertFalse(warn.called)

    def test_malformed_value_returns_the_default_and_warns(self):
        # fallback= does NOT rescue this one -- only the except does.
        self._with_config({"speech": {"step_toggles": "banana"}})
        with mock.patch.object(self.m.logger, "warning") as warn:
            self.assertIs(self.m._cfg_value("speech", "step_toggles", True), True)
        self.assertTrue(warn.called)

    def test_malformed_int_returns_the_default(self):
        self._with_config({"debounce": {"delay_ms": "soon"}})
        self.assertEqual(self.m._cfg_value("debounce", "delay_ms", 300), 300)

    def test_bool_default_uses_getboolean_not_getint(self):
        # bool is a subclass of int, so an isinstance-keyed lookup can send
        # True to getint and raise on "true". The mapping is keyed on exact
        # type for this reason.
        self._with_config({"speech": {"step_toggles": "false"}})
        self.assertIs(self.m._cfg_value("speech", "step_toggles", True), False)

    def test_never_raises_on_a_hostile_parser(self):
        class Hostile(object):
            def getboolean(self, *a, **k):
                raise RuntimeError("boom")

        patcher = mock.patch.object(self.m, "_cfg", Hostile())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertIs(self.m._cfg_value("speech", "step_toggles", True), True)


class ConfigRobustnessTest(unittest.TestCase):
    """No config, however broken, may cost the user the display hook.

    These drive the whole of _install_display_hook rather than one read,
    because the guarantee wanted is about the file, not a single setting.
    """

    @classmethod
    def setUpClass(cls):
        cls.m = stubs.import_bridge()

    def _install_with(self, mapping):
        spoken = []
        rendered = []
        display = types.SimpleNamespace(display=rendered.append)
        surface = types.SimpleNamespace(display=display, song=None)
        fake_bridge = types.SimpleNamespace(
            speak=spoken.append, braille=[].append, dialog=[].append
        )
        cfg = configparser.ConfigParser()
        cfg.read_dict(mapping)
        patchers = [
            mock.patch.object(self.m, "sr_bridge", fake_bridge, create=True),
            mock.patch.dict(
                sys.modules, {"Move_SR_Bridge.sr_bridge": fake_bridge}
            ),
            mock.patch.object(self.m, "_cfg", cfg),
            mock.patch.object(self.m, "_dialog_is_open", lambda: False),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        teardown = self.m._install_display_hook(surface)
        if teardown is not None:
            self.addCleanup(teardown)
        return teardown, display, spoken, rendered

    def _assert_hook_works(self, mapping):
        """Install against `mapping` and prove the hook is alive.

        Falling back to the built-in defaults means the debounce is on at
        300ms, so speech is queued rather than immediate -- wait for it
        rather than assuming, since asserting only on the install would
        pass against a hook that speaks nothing.
        """
        teardown, display, spoken, rendered = self._install_with(mapping)
        self.assertIsNotNone(
            teardown, "a bad config.ini must not cost the display hook"
        )
        del spoken[:]
        del rendered[:]
        display.display(stubs.Content(lines=["Still working"]))
        # Live's own rendering is unconditional and immediate.
        self.assertEqual(len(rendered), 1, "the OLED must keep working")
        deadline = time.time() + 3.0
        while not spoken and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(spoken, ["Still working"])

    def test_completely_empty_config_still_installs(self):
        # The strongest form of the guarantee: not one section present, so
        # every read in the function takes the missing-section path.
        self._assert_hook_works({})

    def test_every_value_malformed_still_installs(self):
        self._assert_hook_works({
            "debounce": {"enabled": "banana", "delay_ms": "soon"},
            "logging": {"level": "LOUD"},
            "speech": {"step_toggles": "perhaps"},
        })

    def test_sections_present_but_empty_still_installs(self):
        self._assert_hook_works({
            "debounce": {}, "logging": {}, "speech": {},
        })


class StepToggleWiringTest(unittest.TestCase):
    """The step hooks reaching the display hook's closure.

    Every test in test_step_toggle.py passes against a feature that is
    never installed; these are the ones that prove it is wired up.
    """

    @classmethod
    def setUpClass(cls):
        cls.m = stubs.import_bridge()

    def _install(self, config=None, editor=None, speak=None):
        self.spoken = []
        self.brailled = []
        self.rendered = []
        display = types.SimpleNamespace(display=self.rendered.append)
        self.editor = editor if editor is not None else stubs.FakeNoteEditor(
            lights={4: "NoteEditor.StepEmpty"},
            on_release=self._toggle_to("NoteEditor.StepFilled"),
        )
        surface = stubs.step_sequence_surface(
            display=display, note_editor=self.editor
        )
        fake_bridge = types.SimpleNamespace(
            speak=speak if speak is not None else self.spoken.append,
            braille=self.brailled.append,
            dialog=[].append,
        )
        cfg = configparser.ConfigParser()
        cfg.read_dict(config if config is not None else {
            "debounce": {"enabled": "false", "delay_ms": "0"},
            "logging": {"level": "INFO"},
            "speech": {"step_toggles": "true"},
        })
        patchers = [
            mock.patch.object(self.m, "sr_bridge", fake_bridge, create=True),
            mock.patch.dict(
                sys.modules, {"Move_SR_Bridge.sr_bridge": fake_bridge}
            ),
            mock.patch.object(self.m, "_cfg", cfg),
            mock.patch.object(self.m, "_dialog_is_open", lambda: False),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

        self.display = display
        teardown = self.m._install_display_hook(surface)
        del self.spoken[:]
        del self.brailled[:]
        del self.rendered[:]
        return teardown

    @staticmethod
    def _toggle_to(value):
        def original(editor, step, can_add_or_remove):
            editor.lights[step.y * editor.width + step.x] = value
            editor.fire_clip_notes()

        return original

    def test_step_toggle_is_announced_end_to_end(self):
        # Catches forgetting to call _install_step_hooks at all.
        teardown = self._install()
        self.assertIsNotNone(teardown)
        self.addCleanup(teardown)
        self.editor._on_release_step(stubs.FakeStep((1, 0)), True)
        self.assertEqual(self.spoken, ["Step 5 on"])
        self.assertEqual(
            self.brailled, self.spoken,
            "braille must carry the same text as speech",
        )

    def test_disabled_wraps_nothing_at_all(self):
        # A gate applied at announce time would still hold the closure --
        # and through it the control surface -- alive all session, so this
        # is asserted on vars(), not only on silence.
        teardown = self._install(config={
            "debounce": {"enabled": "false", "delay_ms": "0"},
            "logging": {"level": "INFO"},
            "speech": {"step_toggles": "false"},
        })
        self.addCleanup(teardown)
        self.assertNotIn("_on_release_step", vars(self.editor))
        self.assertEqual(self.editor._listeners, [])
        self.editor._on_release_step(stubs.FakeStep((1, 0)), True)
        self.assertEqual(self.spoken, [])

    def test_missing_speech_section_still_installs_the_hook(self):
        # The single most likely way this change breaks real users: every
        # config.ini written before 1.7.0 lacks [speech], and config.py only
        # writes the file when it does not exist. Without fallback=,
        # NoSectionError escapes _install_display_hook and the user loses
        # the display hook entirely.
        teardown = self._install(config={
            "debounce": {"enabled": "false", "delay_ms": "0"},
            "logging": {"level": "INFO"},
        })
        self.assertIsNotNone(teardown, "hook must install without [speech]")
        self.addCleanup(teardown)
        self.editor._on_release_step(stubs.FakeStep((1, 0)), True)
        self.assertEqual(self.spoken, ["Step 5 on"])

    def test_garbage_value_falls_back_to_enabled(self):
        teardown = self._install(config={
            "debounce": {"enabled": "false", "delay_ms": "0"},
            "logging": {"level": "INFO"},
            "speech": {"step_toggles": "banana"},
        })
        self.assertIsNotNone(teardown)
        self.addCleanup(teardown)
        self.editor._on_release_step(stubs.FakeStep((1, 0)), True)
        self.assertEqual(self.spoken, ["Step 5 on"])

    def test_absent_step_sequence_does_not_take_the_hook_down(self):
        self.spoken = []
        self.brailled = []
        rendered = []
        display = types.SimpleNamespace(display=rendered.append)
        surface = types.SimpleNamespace(display=display, song=None)
        fake_bridge = types.SimpleNamespace(
            speak=self.spoken.append,
            braille=self.brailled.append,
            dialog=[].append,
        )
        cfg = configparser.ConfigParser()
        cfg.read_dict({
            "debounce": {"enabled": "false", "delay_ms": "0"},
            "logging": {"level": "INFO"},
        })
        patchers = [
            mock.patch.object(self.m, "sr_bridge", fake_bridge, create=True),
            mock.patch.dict(
                sys.modules, {"Move_SR_Bridge.sr_bridge": fake_bridge}
            ),
            mock.patch.object(self.m, "_cfg", cfg),
            mock.patch.object(self.m, "_dialog_is_open", lambda: False),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

        teardown = self.m._install_display_hook(surface)
        self.assertIsNotNone(teardown)
        self.addCleanup(teardown)
        del self.spoken[:]
        display.display(stubs.Content(lines=["Still working"]))
        self.assertEqual(self.spoken, ["Still working"])

    def test_teardown_unwraps_the_step_hooks(self):
        teardown = self._install()
        teardown()
        self.assertNotIn("_on_release_step", vars(self.editor))
        self.assertEqual(self.editor._listeners, [])
        self.editor._on_release_step(stubs.FakeStep((1, 0)), True)
        self.assertEqual(self.spoken, [])

    def test_failing_step_unwrap_still_restores_the_display(self):
        # _install_step_hooks' own unwrap is internally guarded and will not
        # raise, so patch it to return one that does. This tests _teardown's
        # guard: putting the step unwrap outside a try/except, or after the
        # display restore, would leave Live's display method patched for the
        # rest of the session.
        exploding = mock.Mock(side_effect=RuntimeError("boom"))
        with mock.patch.object(
            self.m, "_install_step_hooks", return_value=exploding
        ):
            teardown = self._install()
        original = self.display.display
        teardown()
        self.assertTrue(exploding.called, "the unwrap should have been tried")
        self.assertNotEqual(
            self.display.display,
            original,
            "the display restore must not be skipped by a failing unwrap",
        )
        self.assertEqual(self.display.display, self.rendered.append)

    def test_toggle_preempts_a_queued_display_announcement(self):
        # Two halves, and both are needed. Half one alone still passes if
        # _speak_now is replaced by a bare sr_bridge.speak -- and the user
        # then hears "Step 5 on" followed by "Velocity: 100" 40ms later,
        # which is the exact defect this feature exists to prevent.
        second = threading.Event()
        seen = []

        def speak(text):
            seen.append(text)
            if len(seen) > 1:
                second.set()

        teardown = self._install(
            config={
                "debounce": {"enabled": "true", "delay_ms": "40"},
                "logging": {"level": "INFO"},
                "speech": {"step_toggles": "true"},
            },
            speak=speak,
        )
        self.addCleanup(teardown)
        del seen[:]

        self.display.display(
            stubs.HorizontalListContent(lines=["Velocity", "100"])
        )
        self.assertEqual(seen, [], "the overlay should be queued, not spoken")

        self.editor._on_release_step(stubs.FakeStep((1, 0)), True)
        self.assertEqual(seen, ["Step 5 on"], "the toggle must bypass the debounce")

        self.assertFalse(
            second.wait(0.5),
            "the queued 'Velocity' announcement must be cancelled, not "
            "spoken 40ms later",
        )
        self.assertEqual(seen, ["Step 5 on"])


if __name__ == "__main__":
    unittest.main()
