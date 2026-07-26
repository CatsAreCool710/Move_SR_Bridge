# test_sr_bridge.py - Tests for the TCP client that runs inside Live
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
"""Tests for sr_bridge, the socket client that runs inside Live's Python.

This module had no tests at all, despite being the only thing standing
between Live's callback threads and a socket.  Its failure mode is the
quietest in the project: every send is best-effort and swallows errors, so
a break here costs all speech and logs almost nothing.

No real sockets are opened.  A fake socket class records what was sent and
can be told to fail, which is the interesting half.
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import stubs


class FakeSocket(object):
    """Records sends; optionally fails on connect or on sendall."""

    def __init__(self, fail_connect=False, fail_send=False):
        self.fail_connect = fail_connect
        self.fail_send = fail_send
        self.sent = []
        self.closed = False
        self.timeout = None
        self.connected_to = None

    def settimeout(self, t):
        self.timeout = t

    def connect(self, addr):
        if self.fail_connect:
            raise OSError("connection refused")
        self.connected_to = addr

    def sendall(self, data):
        if self.fail_send:
            raise OSError("broken pipe")
        self.sent.append(data)

    def close(self):
        self.closed = True

    # -- helpers for assertions --------------------------------------
    def messages(self):
        out = []
        for chunk in self.sent:
            for line in chunk.decode("utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
        return out


class SrBridgeTestBase(unittest.TestCase):
    def setUp(self):
        self.bridge = stubs.import_sr_bridge()
        self.bridge.close_socket()
        self.addCleanup(self.bridge.close_socket)

        self.sockets = []

        def fake_socket(*a, **kw):
            s = FakeSocket(**self._socket_kwargs)
            self.sockets.append(s)
            return s

        self._socket_kwargs = {}
        p = mock.patch.object(self.bridge.socket, "socket", fake_socket)
        p.start()
        self.addCleanup(p.stop)

    @property
    def sock(self):
        return self.sockets[-1]


class SendTest(SrBridgeTestBase):
    def test_speak_sends_one_newline_delimited_json_object(self):
        self.bridge.speak("hello")
        self.assertEqual(
            self.sock.messages(), [{"cmd": "speak", "text": "hello"}]
        )
        self.assertTrue(
            self.sock.sent[0].endswith(b"\n"),
            "the protocol is newline-delimited; without the terminator the "
            "helper buffers the message forever",
        )

    def test_non_string_text_is_coerced(self):
        # Live hands us objects, not always strings -- str() is applied at
        # the boundary so json.dumps cannot raise on the callback thread.
        self.bridge.speak(42)
        self.assertEqual(self.sock.messages(), [{"cmd": "speak", "text": "42"}])

    def test_connection_is_reused_across_sends(self):
        self.bridge.speak("one")
        self.bridge.speak("two")
        self.assertEqual(
            len(self.sockets), 1, "should not reconnect for every message"
        )
        self.assertEqual(len(self.sock.messages()), 2)

    def test_timeout_is_set_before_connecting(self):
        # It governs sendall() too, deliberately: a blocked send on Live's
        # display callback or debounce timer is worse than a lost message.
        self.bridge.speak("hello")
        self.assertEqual(self.sock.timeout, 0.1)

    def test_a_refused_connection_is_swallowed(self):
        self._socket_kwargs = {"fail_connect": True}
        self.bridge.speak("hello")            # must not raise
        self.assertEqual(self.sock.sent, [])

    def test_a_failed_send_drops_the_connection_and_reconnects(self):
        self._socket_kwargs = {"fail_send": True}
        self.bridge.speak("lost")
        first = self.sock
        self.assertTrue(first.closed, "a failed send must close the socket")

        # Next call gets a fresh, working socket rather than reusing a dead one.
        self._socket_kwargs = {}
        self.bridge.speak("delivered")
        self.assertIsNot(self.sock, first)
        self.assertEqual(
            self.sock.messages(), [{"cmd": "speak", "text": "delivered"}]
        )


class CommandTest(SrBridgeTestBase):
    def test_dialog_is_its_own_command_not_speak(self):
        # The helper applies a platform policy to `dialog` (dropped on macOS
        # while Live is frontmost). Sending it as `speak` would bypass that.
        self.bridge.dialog("Save changes?")
        self.assertEqual(
            self.sock.messages(),
            [{"cmd": "dialog", "text": "Save changes?"}],
        )

    def test_quit_and_cancel(self):
        self.bridge.quit()
        self.bridge.cancel()
        self.assertEqual(
            self.sock.messages(), [{"cmd": "quit"}, {"cmd": "cancel"}]
        )

    def test_disconnect_sends_quit_then_closes(self):
        self.bridge.speak("hi")
        s = self.sock
        self.bridge.disconnect()
        self.assertEqual(s.messages()[-1], {"cmd": "quit"})
        self.assertTrue(s.closed)

    def test_close_socket_does_not_send_quit(self):
        # This is what keeps a manually-started helper alive when Live
        # disconnects from it -- _stop_helper() relies on the distinction.
        self.bridge.speak("hi")
        s = self.sock
        self.bridge.close_socket()
        self.assertEqual(
            [m["cmd"] for m in s.messages()],
            ["speak"],
            "close_socket must not tell the helper to quit",
        )
        self.assertTrue(s.closed)


class BrailleTest(SrBridgeTestBase):
    def test_braille_is_skipped_on_macos(self):
        # VoiceOver drives the braille display itself whenever it speaks, so
        # sending braille too would duplicate it. Hardcoded, not configurable.
        with mock.patch.object(self.bridge.sys, "platform", "darwin"):
            self.bridge.braille("hello")
        self.assertEqual(
            self.sockets, [], "macOS must not even open a connection for braille"
        )

    def test_braille_is_sent_on_windows(self):
        with mock.patch.object(self.bridge.sys, "platform", "win32"):
            self.bridge.braille("hello")
        self.assertEqual(
            self.sock.messages(), [{"cmd": "braille", "text": "hello"}]
        )


if __name__ == "__main__":
    unittest.main()
