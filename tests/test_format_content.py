# test_format_content.py - Display content formatting tests
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
Tests for _format_content(), which turns a Move OLED content object into
the text spoken to the screen reader.

Also covers the speech-normalisation layer: icon-font glyphs, Live's
display-width abbreviations, and sentence-wrapped lines.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stubs

AUTOMATION_CHAR = u"\ue044"


class FormatContentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = stubs.import_bridge()

    def setUp(self):
        # Guard against the silent-fallback trap: if the fake Move package
        # failed to provide display_util, _content_types would be empty,
        # every isinstance branch below would be skipped, and these tests
        # would pass while only ever exercising the final fallback.
        self.assertEqual(
            sorted(self.m._content_types),
            ["content", "horizontal", "notification", "vertical"],
            "content types not registered -- tests would be vacuous",
        )

    # -- empty / degenerate input -------------------------------------
    def test_missing_lines_attribute(self):
        class Bare(object):
            pass

        self.assertIsNone(self.m._format_content(Bare()))

    def test_empty_lines(self):
        self.assertIsNone(self.m._format_content(stubs.Content(lines=[])))

    def test_whitespace_only_lines(self):
        content = stubs.Content(lines=["   ", "", "\t"])
        self.assertIsNone(self.m._format_content(content))

    def test_lines_are_stripped(self):
        content = stubs.Content(lines=["  Track 1  ", "  Volume  "])
        ann = self.m._format_content(content)
        self.assertEqual(ann.text, "Track 1, Volume")
        self.assertIsNone(ann.name)

    # -- vertical list -------------------------------------------------
    def test_vertical_announces_selected_item(self):
        content = stubs.VerticalListContent(
            lines=["Major", "Minor", "Dorian"], list_index=1
        )
        ann = self.m._format_content(content)
        self.assertEqual(ann.text, "Minor")
        self.assertIsNone(ann.name)

    def test_vertical_without_index_joins_all(self):
        content = stubs.VerticalListContent(lines=["Major", "Minor"], list_index=None)
        self.assertEqual(self.m._format_content(content).text, "Major, Minor")

    def test_vertical_with_out_of_range_index_joins_all(self):
        content = stubs.VerticalListContent(lines=["Major", "Minor"], list_index=99)
        self.assertEqual(self.m._format_content(content).text, "Major, Minor")

    # -- list_index must stay aligned with content.lines ----------------
    # Live's index refers to content.lines. Cleaning the lines into a
    # filtered list and then indexing THAT shifted every entry after a
    # dropped line, so the wrong menu item was announced -- confidently,
    # which is worse for a screen-reader user than saying nothing.
    def test_vertical_index_survives_a_blank_line(self):
        content = stubs.VerticalListContent(
            lines=["Reverb", "", "Delay", "Chorus"], list_index=2
        )
        self.assertEqual(
            self.m._format_content(content).text,
            "Delay",
            "a blank line before the selection must not shift the index",
        )

    def test_vertical_index_survives_an_icon_only_line(self):
        # A line that is nothing but an icon-font glyph cleans to "".
        content = stubs.VerticalListContent(
            lines=[u"\ue010", "Filter", "Gain"], list_index=1
        )
        self.assertEqual(
            self.m._format_content(content).text,
            "Filter",
            "an icon-only line before the selection must not shift the index",
        )

    def test_vertical_last_item_after_a_blank_line(self):
        # Previously fell out of range and read the whole list aloud.
        content = stubs.VerticalListContent(
            lines=["Reverb", "", "Delay", "Chorus"], list_index=3
        )
        self.assertEqual(self.m._format_content(content).text, "Chorus")

    def test_vertical_selecting_a_blank_line_joins_all(self):
        # Nothing sensible to announce for the selection itself.
        content = stubs.VerticalListContent(
            lines=["Reverb", "", "Delay"], list_index=1
        )
        self.assertEqual(
            self.m._format_content(content).text, "Reverb, Delay"
        )

    # -- horizontal (name / value) -------------------------------------
    def test_horizontal_pair_reports_name_and_value(self):
        content = stubs.HorizontalListContent(lines=["2-MIDI", "No Device"])
        ann = self.m._format_content(content)
        self.assertEqual(ann.text, "2-MIDI: No Device")
        self.assertEqual(ann.name, "2-MIDI")
        self.assertEqual(
            ann.value, "No Device",
            "value must be reported separately so the caller never has to "
            "slice it back out of text",
        )

    def test_horizontal_non_pair_has_no_name_part(self):
        content = stubs.HorizontalListContent(lines=["A", "B", "C"])
        ann = self.m._format_content(content)
        self.assertEqual(ann.text, "A, B, C")
        self.assertIsNone(ann.name, "only exact pairs are strippable")

    def test_value_is_usable_verbatim_when_name_is_redundant(self):
        content = stubs.HorizontalListContent(lines=["Bass", "Reverb Send"])
        ann = self.m._format_content(content)
        self.assertEqual(ann.value, "Reverb Send")

    def test_value_survives_punctuation_in_name(self):
        content = stubs.HorizontalListContent(lines=["1-Audio: In", "Off"])
        ann = self.m._format_content(content)
        self.assertEqual(ann.value, "Off")

    # -- notifications --------------------------------------------------
    def test_notification_joins_with_spaces_and_is_flagged(self):
        content = stubs.NotificationContent(lines=["Undo", "Delete Clip"])
        ann = self.m._format_content(content)
        self.assertEqual(ann.text, "Undo Delete Clip")
        self.assertTrue(ann.is_notification)

    def test_main_content_is_not_flagged_as_notification(self):
        ann = self.m._format_content(stubs.Content(lines=["Anything"]))
        self.assertFalse(ann.is_notification)

    # -- generic fallback ------------------------------------------------
    def test_generic_content_joins_with_commas(self):
        ann = self.m._format_content(stubs.Content(lines=["Line one", "Two"]))
        self.assertEqual(ann.text, "Line one, Two")

    def test_non_string_lines_are_coerced(self):
        ann = self.m._format_content(stubs.Content(lines=[1, 2.5]))
        self.assertEqual(ann.text, "1, 2.5")


class SpeechNormalisationTest(unittest.TestCase):
    """The layer that makes Live's on-screen text speakable."""

    @classmethod
    def setUpClass(cls):
        cls.m = stubs.import_bridge()

    # -- automation indicator (icon-font glyph U+E044) -------------------
    def test_automation_glyph_becomes_a_word(self):
        # Live prefixes the parameter name with U+E044 to show automation.
        # Forwarded raw, a screen reader says nothing for it and the
        # automation state is lost entirely.
        content = stubs.HorizontalListContent(
            lines=[AUTOMATION_CHAR + "Cutoff", "800 Hz"]
        )
        ann = self.m._format_content(content)
        self.assertEqual(ann.text, "automated Cutoff: 800 Hz")
        self.assertNotIn(AUTOMATION_CHAR, ann.text)

    def test_automation_glyph_kept_out_of_the_match_key(self):
        # `name` is compared against Live's selected track/scene, so the
        # marker must not leak into it or the comparison can never match.
        content = stubs.HorizontalListContent(
            lines=[AUTOMATION_CHAR + "Bass", "0 dB"]
        )
        ann = self.m._format_content(content)
        self.assertEqual(ann.name, "Bass")
        self.assertEqual(ann.value, "0 dB")

    def test_automation_glyph_handled_outside_name_value_pairs(self):
        content = stubs.Content(lines=[AUTOMATION_CHAR + "Volume"])
        self.assertEqual(self.m._format_content(content).text, "automated Volume")

    def test_unknown_icon_glyphs_are_dropped(self):
        # Any other Private Use Area codepoint is an icon with no spoken
        # form; leaving it in makes readers announce "unknown character".
        content = stubs.Content(lines=[u"\ue001Play\ue002"])
        self.assertEqual(self.m._format_content(content).text, "Play")

    def test_ordinary_unicode_is_untouched(self):
        content = stubs.Content(lines=[u"Café ▲ 日本"])
        self.assertEqual(self.m._format_content(content).text, u"Café ▲ 日本")

    # -- display-width abbreviations -------------------------------------
    def test_abbreviation_is_expanded(self):
        # "Autmtn." is unreadable when spoken; the OLED needs it, we don't.
        content = stubs.VerticalListContent(
            lines=["Autmtn. Arm On"], list_index=0
        )
        self.assertEqual(
            self.m._format_content(content).text, "Automation Arm On"
        )

    # -- wrapped sentences ------------------------------------------------
    def test_wrapped_sentence_joins_without_a_comma(self):
        # Live wraps one sentence across lines; a comma there inserts a
        # spurious pause mid-sentence.
        content = stubs.Content(lines=["Press wheel to", "shut down"])
        self.assertEqual(
            self.m._format_content(content).text, "Press wheel to shut down"
        )

    def test_distinct_fields_still_get_a_comma(self):
        content = stubs.Content(lines=["Cutoff", "800 Hz"])
        self.assertEqual(self.m._format_content(content).text, "Cutoff, 800 Hz")

    def test_continuation_detection_uses_leading_case(self):
        content = stubs.Content(lines=["Track", "Volume"])
        self.assertEqual(self.m._format_content(content).text, "Track, Volume")


class UrgencyTest(unittest.TestCase):
    """Critical screens must not wait behind the debounce."""

    @classmethod
    def setUpClass(cls):
        cls.m = stubs.import_bridge()

    def _ann(self, *lines):
        return self.m._format_content(stubs.Content(lines=list(lines)))

    def test_shutdown_prompt_is_urgent(self):
        self.assertTrue(
            self.m._is_urgent(self._ann("Press wheel to", "shut down"))
        )

    def test_ordinary_screen_is_not_urgent(self):
        self.assertFalse(self.m._is_urgent(self._ann("Cutoff", "800 Hz")))

    def test_open_dialog_makes_everything_urgent(self):
        # A modal dialog blocks Live entirely, so whatever is on screen
        # needs saying now rather than after the debounce delay.
        original = self.m._dialog_is_open
        self.m._dialog_is_open = lambda: True
        try:
            self.assertTrue(self.m._is_urgent(self._ann("Cutoff", "800 Hz")))
        finally:
            self.m._dialog_is_open = original

    def test_dialog_probe_reads_lives_open_dialog_count(self):
        # The actual signal, per Move/dialog.py:
        #   any_dialog_open = application.open_dialog_count > 0
        # Outside Live `_Live` is None and the function short-circuits, so
        # this used to assert nothing at all: the old version checked only
        # that the result was True or False, which no boolean can fail.
        original = self.m._Live
        try:
            for count, expected in ((0, False), (1, True), (3, True)):
                self.m._Live = _FakeLive(open_dialog_count=count)
                self.assertIs(
                    self.m._dialog_is_open(),
                    expected,
                    "open_dialog_count=%d should mean dialog_open=%s"
                    % (count, expected),
                )
        finally:
            self.m._Live = original

    def test_dialog_probe_never_raises(self):
        # Runs on every display update, on Live's own callback thread, so a
        # failure here must degrade to "no dialog" rather than break the
        # display hook. Driven with a property that raises, because that is
        # the case a plain None check would miss.
        original = self.m._Live
        try:
            self.m._Live = _FakeLive(raises=RuntimeError("Live is busy"))
            self.assertFalse(self.m._dialog_is_open())
        finally:
            self.m._Live = original


class _FakeLive(object):
    """Stands in for the `Live` module's Application accessor."""

    def __init__(self, open_dialog_count=0, raises=None):
        self._count = open_dialog_count
        self._raises = raises
        self.Application = self

    def get_application(self):
        if self._raises is not None:
            raise self._raises
        return self

    @property
    def open_dialog_count(self):
        return self._count


if __name__ == "__main__":
    unittest.main()
