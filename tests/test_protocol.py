# test_protocol.py - Newline-delimited JSON protocol tests
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
Tests for sr_helper.handle_client() -- the newline-delimited JSON parser
that everything the user hears passes through.

handle_client is driven directly over a socketpair rather than by starting
the real server, so these tests never bind port 8765 and cannot disturb (or
be disturbed by) a helper actually running on the machine.
"""

import json
import os
import socket
import sys
import threading
import types
import unittest

try:
    from unittest import mock
except ImportError:  # pragma: no cover
    import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stubs


class ProtocolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper = stubs.import_sr_helper()

    def setUp(self):
        self.spoken = []
        self.brailled = []
        self.cancels = []

        # Restore the real backend hooks afterwards -- leaving recording
        # stubs installed on the module would silently change behaviour for
        # any later test that imports it.
        self.dialogs = []

        for name in ("sr_speak", "sr_braille", "sr_cancel", "sr_dialog",
                     "COMMANDS"):
            self.addCleanup(setattr, self.helper, name, getattr(self.helper, name))

        self.helper.sr_speak = lambda text: self.spoken.append(text)
        self.helper.sr_braille = lambda text: self.brailled.append(text)
        self.helper.sr_cancel = lambda: self.cancels.append(True)
        self.helper.sr_dialog = lambda text: self.dialogs.append(text)

        # COMMANDS captured the originals by reference at import time, so
        # rebuild the table against the recording versions.
        self.helper.COMMANDS = {
            "speak": lambda msg: self.helper.sr_speak(msg.get("text", "")),
            "braille": lambda msg: self.helper.sr_braille(msg.get("text", "")),
            "cancel": lambda _: self.helper.sr_cancel(),
            # The real handler, not a lambda: it owns the empty-text check,
            # and it resolves sr_dialog as a module global at call time, so
            # the recording stub above still applies.
            "dialog": self.helper._handle_dialog,
            "quit": self.helper._handle_quit,
        }

        # A previous test's "quit" would otherwise leave this set and make
        # handle_client return immediately.
        self.helper._shutdown.clear()
        self.addCleanup(self.helper._shutdown.clear)

    def _run(self, *chunks):
        """Feed raw bytes to handle_client and return once it finishes.

        The handler runs on its own thread and is started *before* anything
        is written: a payload larger than the socket buffer (the flood test)
        would otherwise deadlock in sendall() with no reader draining it.
        """
        client, server = socket.socketpair()
        thread = threading.Thread(
            target=self.helper.handle_client, args=(server, ("test", 0))
        )
        thread.daemon = True
        thread.start()
        try:
            for chunk in chunks:
                client.sendall(chunk)
            client.shutdown(socket.SHUT_WR)  # EOF -> handler's recv returns b""
            thread.join(timeout=15)
        finally:
            client.close()
            try:
                server.close()
            except OSError:
                pass
        self.assertFalse(
            thread.is_alive(), "handle_client did not return after EOF"
        )

    @staticmethod
    def _line(**msg):
        return (json.dumps(msg) + "\n").encode("utf-8")

    # -- well-formed commands -------------------------------------------
    def test_speak_command(self):
        self._run(self._line(cmd="speak", text="Track 1"))
        self.assertEqual(self.spoken, ["Track 1"])

    def test_braille_command(self):
        self._run(self._line(cmd="braille", text="Track 1"))
        self.assertEqual(self.brailled, ["Track 1"])

    def test_dialog_command(self):
        # Routed separately from speak: the macOS backend drops it while
        # Live is frontmost, since VoiceOver announces the dialog itself.
        self._run(self._line(cmd="dialog", text="Save changes?"))
        self.assertEqual(self.dialogs, ["Save changes?"])
        self.assertEqual(self.spoken, [])

    def test_dialog_command_with_no_text_is_ignored(self):
        self._run(self._line(cmd="dialog"))
        self.assertEqual(self.dialogs, [])

    def test_cancel_command(self):
        self._run(self._line(cmd="cancel"))
        self.assertEqual(len(self.cancels), 1)

    def test_quit_sets_shutdown(self):
        self._run(self._line(cmd="quit"))
        self.assertTrue(self.helper._shutdown.is_set())

    def test_multiple_commands_in_one_packet(self):
        payload = (
            self._line(cmd="speak", text="one")
            + self._line(cmd="speak", text="two")
            + self._line(cmd="speak", text="three")
        )
        self._run(payload)
        self.assertEqual(self.spoken, ["one", "two", "three"])

    def test_command_split_across_packets(self):
        # The parser must buffer a partial line rather than dropping it.
        whole = self._line(cmd="speak", text="split message")
        self._run(whole[:10], whole[10:])
        self.assertEqual(self.spoken, ["split message"])

    def test_unicode_survives_round_trip(self):
        self._run(self._line(cmd="speak", text="Café ▲ 日本"))
        self.assertEqual(self.spoken, ["Café ▲ 日本"])

    def test_missing_text_defaults_to_empty(self):
        self._run(self._line(cmd="speak"))
        self.assertEqual(self.spoken, [""])

    # -- malformed input must not kill the connection --------------------
    def test_malformed_json_is_skipped(self):
        payload = b"{not json at all}\n" + self._line(cmd="speak", text="after")
        self._run(payload)
        self.assertEqual(
            self.spoken, ["after"], "handler must recover from a bad line"
        )

    def test_non_object_json_is_rejected(self):
        payload = b'["a list"]\n' + self._line(cmd="speak", text="after")
        self._run(payload)
        self.assertEqual(self.spoken, ["after"])

    def test_unknown_command_is_ignored(self):
        payload = self._line(cmd="explode") + self._line(cmd="speak", text="after")
        self._run(payload)
        self.assertEqual(self.spoken, ["after"])

    def test_blank_lines_are_ignored(self):
        payload = b"\n\n   \n" + self._line(cmd="speak", text="after")
        self._run(payload)
        self.assertEqual(self.spoken, ["after"])

    def test_invalid_utf8_does_not_crash(self):
        payload = b"\xff\xfe bad bytes\n" + self._line(cmd="speak", text="after")
        self._run(payload)
        self.assertEqual(self.spoken, ["after"])

    # -- unbounded-buffer guard ------------------------------------------
    def test_oversized_line_is_dropped_and_parser_recovers(self):
        flood = b"x" * (self.helper._MAX_LINE_CHARS + 4096)
        payload = flood + b"\n" + self._line(cmd="speak", text="after flood")
        self._run(payload)
        self.assertEqual(
            self.spoken,
            ["after flood"],
            "buffer guard must drop the flood but keep parsing",
        )


@unittest.skipUnless(
    sys.platform == "darwin", "the frontmost-app gate is the macOS backend"
)
class DialogFocusGateTest(unittest.TestCase):
    """Live's dialogs are only announced when Live is in the background.

    Measured on real logs: with Live frontmost, our announcement went out
    1ms after the dialog opened and never reached VoiceOver -- VoiceOver's
    own focus announcement for the same dialog preempted it 261ms later.
    VoiceOver's AppleScript `output` takes only a spelling type, with no
    queue or priority parameter, so that race cannot be won. Speaking only
    when Live is NOT frontmost is the case VoiceOver does not cover.
    """

    @classmethod
    def setUpClass(cls):
        cls.helper = stubs.import_sr_helper()

    def setUp(self):
        self.spoken = []
        self.addCleanup(
            setattr, self.helper, "sr_speak", self.helper.sr_speak
        )
        self.addCleanup(
            setattr, self.helper, "_frontmost_bundle_id",
            self.helper._frontmost_bundle_id,
        )
        self.helper.sr_speak = self.spoken.append

    def _front(self, bundle_id):
        self.helper._frontmost_bundle_id = lambda: bundle_id

    def test_suppressed_while_live_is_frontmost(self):
        self._front("com.ableton.live")
        self.helper.sr_dialog("Save changes?")
        self.assertEqual(
            self.spoken, [],
            "VoiceOver announces the dialog itself and preempts us anyway",
        )

    def test_announced_when_another_app_is_frontmost(self):
        self._front("com.apple.Safari")
        self.helper.sr_dialog("Save changes?")
        self.assertEqual(
            self.spoken, ["Save changes?"],
            "with Live in the background VoiceOver says nothing, and the "
            "user at the Move has no other way to learn why it went dead",
        )

    def test_announced_when_the_frontmost_app_is_unknown(self):
        # Fail open: being too talkative beats being silently broken.
        self._front(None)
        self.helper.sr_dialog("Save changes?")
        self.assertEqual(self.spoken, ["Save changes?"])

    def test_frontmost_lookup_never_raises(self):
        with mock.patch.object(
            self.helper.subprocess, "run", side_effect=OSError("no lsappinfo")
        ):
            self.assertIsNone(self.helper._frontmost_bundle_id())

    def test_frontmost_lookup_parses_lsappinfo(self):
        # lsappinfo prints:  "CFBundleIdentifier"="com.ableton.live"
        outputs = [
            types.SimpleNamespace(returncode=0, stdout="ASN:0x0-0x123:\n"),
            types.SimpleNamespace(
                returncode=0, stdout='"CFBundleIdentifier"="com.ableton.live"\n'
            ),
        ]
        with mock.patch.object(
            self.helper.subprocess, "run", side_effect=outputs
        ):
            self.assertEqual(
                self.helper._frontmost_bundle_id(), "com.ableton.live"
            )

    def test_frontmost_lookup_handles_a_null_bundle_id(self):
        # lsappinfo answers `"CFBundleIdentifier"=[ NULL ]` for a dead ASN.
        outputs = [
            types.SimpleNamespace(returncode=0, stdout="ASN:0x0-0xdead:\n"),
            types.SimpleNamespace(
                returncode=0, stdout='"CFBundleIdentifier"=[ NULL ] \n'
            ),
        ]
        with mock.patch.object(
            self.helper.subprocess, "run", side_effect=outputs
        ):
            self.assertIsNone(self.helper._frontmost_bundle_id())


@unittest.skipUnless(
    sys.platform == "darwin", "_escape_applescript is macOS-only"
)
class EscapeAppleScriptTest(unittest.TestCase):
    """Text reaches VoiceOver embedded in a double-quoted AppleScript literal.

    Live's dialog messages are the payload most likely to contain a quote,
    and they are exactly what gets forwarded here.  Untested until now.
    """

    def setUp(self):
        self.helper = stubs.import_sr_helper()

    def _escaped(self, text):
        return self.helper._escape_applescript(text)

    def test_double_quotes_are_escaped(self):
        self.assertEqual(self._escaped('Say "hi"'), 'Say \\"hi\\"')

    def test_backslashes_are_escaped_first(self):
        # Order matters: escaping quotes first would then double the
        # backslash that escape just introduced.
        self.assertEqual(self._escaped(r"C:\path"), r"C:\\path")
        self.assertEqual(self._escaped(r'a\"b'), r"a\\\"b")

    def test_non_string_input_is_coerced(self):
        self.assertEqual(self._escaped(42), "42")

    def test_escaped_text_survives_a_real_round_trip(self):
        # The assertions above encode an assumption about AppleScript's
        # string literals. Check it against the real interpreter rather
        # than trusting it, since getting this wrong means either a
        # mangled announcement or a script that will not compile.
        import subprocess

        for original in [
            'Save changes to "Untitled"?',
            r"back\slash",
            r'both " and \ together',
            "plain text",
        ]:
            script = 'return "%s"' % self._escaped(original)
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(
                result.returncode, 0,
                "osascript rejected the escaped form of %r: %s"
                % (original, result.stderr.strip()),
            )
            self.assertEqual(
                result.stdout.rstrip("\n"), original,
                "escaping changed the text VoiceOver would speak",
            )


if __name__ == "__main__":
    unittest.main()
