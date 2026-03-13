# sr_helper.py - Screen reader bridge helper process for Move-SR-Bridge
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
SR Helper -- TCP server that bridges Ableton Live to screen readers.

Part of the Move-SR-Bridge project.  Runs as a standalone process
(compiled to .exe or via system Python).  Listens on TCP port 8765 for
JSON commands from the Move_SR_Bridge MIDI Remote Script running inside
Ableton Live, and forwards them to the active screen reader via the
Tolk abstraction library.

Supported screen readers (via Tolk):
    NVDA, JAWS, Window-Eyes, ZoomText, System Access

Protocol: newline-delimited JSON over TCP on 127.0.0.1:8765
    {"cmd": "speak", "text": "..."}
    {"cmd": "braille", "text": "..."}
    {"cmd": "cancel"}
    {"cmd": "quit"}
"""

import ctypes
import json
import logging
import os
import socket
import sys
import threading

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
HOST = "127.0.0.1"
PORT = 8765

# ---------------------------------------------------------------------------
# Logging -- write to a file next to the executable/script
# ---------------------------------------------------------------------------
_script_dir = os.path.dirname(os.path.abspath(sys.argv[0] if sys.argv[0] else __file__))
_log_path = os.path.join(_script_dir, "Move_SR_Bridge.log")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(_log_path, mode="w", encoding="utf-8")],
)
log = logging.getLogger("sr_helper")

# Also log to console if we have one (manual launch via .bat)
if sys.stderr and hasattr(sys.stderr, "write"):
    try:
        _console = logging.StreamHandler(sys.stderr)
        _console.setLevel(logging.INFO)
        _console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        log.addHandler(_console)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Shutdown event -- signals all threads to exit
# ---------------------------------------------------------------------------
_shutdown = threading.Event()

# ---------------------------------------------------------------------------
# Tolk screen reader abstraction library
# ---------------------------------------------------------------------------
_tolk = None


def load_tolk():
    """Load and initialize the Tolk screen reader library."""
    global _tolk
    dll_path = os.path.join(_script_dir, "Tolk.dll")

    if not os.path.exists(dll_path):
        log.error("Tolk.dll not found: %s", dll_path)
        return False
    try:
        _tolk = ctypes.cdll.LoadLibrary(dll_path)

        # Set up function signatures for proper wide-string marshaling
        _tolk.Tolk_DetectScreenReader.restype = ctypes.c_wchar_p
        _tolk.Tolk_IsLoaded.restype = ctypes.c_bool
        _tolk.Tolk_HasSpeech.restype = ctypes.c_bool
        _tolk.Tolk_HasBraille.restype = ctypes.c_bool

        _tolk.Tolk_Speak.restype = ctypes.c_bool
        _tolk.Tolk_Speak.argtypes = [ctypes.c_wchar_p, ctypes.c_bool]

        _tolk.Tolk_Braille.restype = ctypes.c_bool
        _tolk.Tolk_Braille.argtypes = [ctypes.c_wchar_p]

        _tolk.Tolk_Output.restype = ctypes.c_bool
        _tolk.Tolk_Output.argtypes = [ctypes.c_wchar_p, ctypes.c_bool]

        _tolk.Tolk_Silence.restype = ctypes.c_bool

        # Initialize Tolk (this also calls CoInitializeEx internally)
        _tolk.Tolk_Load()

        sr = _tolk.Tolk_DetectScreenReader()
        if sr:
            log.info("Tolk loaded -- detected screen reader: %s", sr)
            log.info(
                "  Speech: %s, Braille: %s",
                _tolk.Tolk_HasSpeech(),
                _tolk.Tolk_HasBraille(),
            )
        else:
            log.warning(
                "Tolk loaded but no screen reader detected -- "
                "will retry when commands arrive"
            )
        return True
    except OSError as e:
        log.error("Failed to load Tolk.dll: %s", e)
        _tolk = None
        return False


def unload_tolk():
    """Unload the Tolk library (releases COM, etc.)."""
    if _tolk is not None:
        try:
            _tolk.Tolk_Unload()
            log.info("Tolk unloaded")
        except Exception:
            pass


def sr_speak(text):
    """Speak text via the active screen reader."""
    if _tolk is None:
        return
    try:
        _tolk.Tolk_Speak(str(text), True)  # interrupt=True
    except Exception as e:
        log.warning("speak error: %s", e)


def sr_braille(text):
    """Display text on braille display via the active screen reader."""
    if _tolk is None:
        return
    try:
        _tolk.Tolk_Braille(str(text))
    except Exception as e:
        log.warning("braille error: %s", e)


def sr_cancel():
    """Silence the active screen reader."""
    if _tolk is None:
        return
    try:
        _tolk.Tolk_Silence()
    except Exception as e:
        log.warning("cancel error: %s", e)


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------
def _handle_quit(_msg):
    log.info("Received quit command, shutting down")
    _shutdown.set()


COMMANDS = {
    "speak": lambda msg: sr_speak(msg.get("text", "")),
    "braille": lambda msg: sr_braille(msg.get("text", "")),
    "cancel": lambda _: sr_cancel(),
    "quit": _handle_quit,
}


# ---------------------------------------------------------------------------
# Client handler
# ---------------------------------------------------------------------------
def handle_client(conn, addr):
    log.info("Client connected: %s", addr)
    buffer = ""
    try:
        while not _shutdown.is_set():
            try:
                conn.settimeout(1.0)
                data = conn.recv(4096)
            except socket.timeout:
                continue
            if not data:
                break
            buffer += data.decode("utf-8", errors="replace")

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    cmd = msg.get("cmd", "")
                    handler = COMMANDS.get(cmd)
                    if handler:
                        handler(msg)
                    else:
                        log.warning("Unknown command: %s", cmd)
                except json.JSONDecodeError as e:
                    log.warning("Bad JSON: %s", e)
    except (ConnectionResetError, ConnectionAbortedError, OSError):
        pass
    finally:
        log.info("Client disconnected: %s", addr)
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log.info("Move-SR-Bridge Helper starting")
    log.info("Log file: %s", _log_path)

    if not load_tolk():
        log.error("Cannot continue without Tolk")
        sys.exit(1)

    sr = _tolk.Tolk_DetectScreenReader() if _tolk else None
    if sr:
        sr_speak("Move SR Bridge helper started")
    else:
        log.warning("No screen reader detected -- will retry when commands arrive")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((HOST, PORT))
    except OSError as e:
        log.error("Cannot bind to port %d: %s", PORT, e)
        sys.exit(1)

    server.listen(2)
    server.settimeout(1.0)
    log.info("Listening on %s:%d", HOST, PORT)

    try:
        while not _shutdown.is_set():
            try:
                conn, addr = server.accept()
                t = threading.Thread(
                    target=handle_client, args=(conn, addr), daemon=True
                )
                t.start()
            except socket.timeout:
                continue
    except KeyboardInterrupt:
        log.info("Keyboard interrupt, shutting down")
    finally:
        server.close()
        unload_tolk()
        log.info("Move-SR-Bridge Helper stopped")


if __name__ == "__main__":
    main()
