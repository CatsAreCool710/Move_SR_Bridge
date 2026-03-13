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

logger = logging.getLogger(__name__)

_HELPER_HOST = "127.0.0.1"
_HELPER_PORT = 8765
_sock = None


def _ensure_connected():
    """Connect to the SR helper process if not already connected."""
    global _sock
    if _sock is not None:
        return True
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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
    if not _ensure_connected():
        return
    try:
        data = json.dumps(msg) + "\n"
        _sock.sendall(data.encode("utf-8"))
    except OSError:
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
    _send({"cmd": "braille", "text": str(text)})


def cancel():
    """Cancel current speech."""
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
