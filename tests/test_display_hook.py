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


if __name__ == "__main__":
    unittest.main()
