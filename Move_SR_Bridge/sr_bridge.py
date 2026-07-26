# sr_bridge.py - TCP socket client for SR helper (runs inside Ableton Live)
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
TCP socket client that sends speech/braille commands to the screen reader
helper process.  This module is part of Move-SR-Bridge and runs inside
Ableton Live's embedded Python, which does NOT have ctypes -- hence the
need for an out-of-process bridge.

Protocol: newline-delimited JSON over TCP to 127.0.0.1:8765
"""

import json
import logging
import socket
import sys
import threading

logger = logging.getLogger(__name__)

_HELPER_HOST = "127.0.0.1"
_HELPER_PORT = 8765
_sock = None

# Guards _sock.  Two threads reach this module: Live's main thread (the
# display hook, and connect/disconnect announcements) and the debounce
# timer thread in __init__.py.  Without the lock, the main thread running
# close_socket() during disconnect() could set _sock = None in between a
# timer thread's connection check and its sendall(), raising AttributeError
# on None -- which _send()'s OSError handler would not catch, killing the
# timer thread with a traceback into Live's stderr.
_sock_lock = threading.Lock()


def _ensure_connected_locked():
    """Connect to the SR helper if not already connected.

    Caller must hold _sock_lock.
    """
    global _sock
    if _sock is not None:
        return True
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Deliberately left set for the life of the socket, so it governs
        # sendall() in _send() as well as this connect().  Both run on
        # threads Live owns -- the display callback and the debounce timer
        # -- and blocking either of them is worse than losing one
        # announcement, so a send that cannot complete in 100ms drops the
        # connection instead.  The next call reconnects.
        s.settimeout(0.1)
        s.connect((_HELPER_HOST, _HELPER_PORT))
        _sock = s
        logger.info(
            "Move_SR_Bridge: Connected to SR helper on port %d",
            _HELPER_PORT,
        )
        return True
    except OSError:
        _sock = None
        return False


def _send(msg):
    """Send a JSON message to the helper. Reconnects on failure."""
    global _sock
    with _sock_lock:
        if not _ensure_connected_locked():
            return
        try:
            data = json.dumps(msg) + "\n"
            _sock.sendall(data.encode("utf-8"))
        except Exception as e:
            logger.debug(
                "Move_SR_Bridge: Send failed, dropping connection: %s", e
            )
            try:
                _sock.close()
            except Exception:
                pass
            _sock = None


def speak(text):
    """Speak text via the active screen reader."""
    _send({"cmd": "speak", "text": str(text)})


def braille(text):
    """Display text on braille display via the active screen reader."""
    if sys.platform == "darwin":
        return
    _send({"cmd": "braille", "text": str(text)})


def dialog(text):
    """Announce a Live modal dialog.

    Separate from speak() because the helper applies a platform policy to
    it: on macOS it is dropped while Live is frontmost, since VoiceOver
    announces the dialog itself and preempts us anyway.  That decision
    needs the OS-level focus state, which belongs in the helper -- this
    process must not shell out from Live's callback thread, least of all
    while a modal dialog has Live's UI blocked.
    """
    _send({"cmd": "dialog", "text": str(text)})


def cancel():
    """Cancel current speech.

    Reserved protocol surface: the helper implements the command, but
    nothing in this package sends one.  Speech is cut off by the next
    utterance in practice, and the debounce already drops superseded text
    before it is ever sent.  Kept because it is part of the documented
    protocol and costs nothing -- not because it is wired up.
    """
    _send({"cmd": "cancel"})


def quit():
    """Tell the helper process to shut down."""
    _send({"cmd": "quit"})


def close_socket():
    """Close the socket without sending a quit command.

    Use this when disconnecting from a helper that was already running
    (i.e. one we did not launch ourselves) so we don't kill it.
    """
    global _sock
    with _sock_lock:
        if _sock is not None:
            try:
                _sock.close()
            except Exception:
                pass
            _sock = None


def disconnect():
    """Send quit command and close the socket."""
    try:
        quit()
    except Exception:
        pass
    close_socket()
