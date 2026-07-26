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
(compiled to .exe/.binary or via system Python).  Listens on TCP port
8765 for JSON commands from the Move_SR_Bridge MIDI Remote Script
running inside Ableton Live, and forwards them to the active screen
reader.

Platform backends:
    Windows: Tolk abstraction library (NVDA, JAWS, Window-Eyes, ZoomText,
             System Access)
    macOS:   VoiceOver via AppleScript (macOS Tahoe 26 or later)

Protocol: newline-delimited JSON over TCP on 127.0.0.1:8765
    {"cmd": "speak", "text": "..."}
    {"cmd": "braille", "text": "..."}
    {"cmd": "dialog", "text": "..."}
    {"cmd": "cancel"}
    {"cmd": "quit"}

`dialog` is `speak` plus a platform policy -- see sr_dialog().  `cancel`
is reserved: the protocol accepts it, but nothing in the remote script
currently sends one.
"""

import json
import logging
import os
import platform
import socket
import sys
import threading

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
HOST = "127.0.0.1"
PORT = 8765

# ---------------------------------------------------------------------------
# Logging -- write to the shared per-user state directory
# ---------------------------------------------------------------------------
def _install_dir():
    """Where this helper was installed, i.e. where config.py and Tolk.dll live.

    When frozen, derive it from sys.executable rather than sys.argv[0].
    Both agree for every way the helper is currently launched (the remote
    script and both start_helper scripts all pass an absolute path), but
    argv[0] is whatever the caller typed -- so a helper invoked by bare
    name through PATH would resolve this to the caller's cwd and silently
    lose both config.py and Tolk.dll.  That surfaces as
    "config: config.py unavailable" with speech otherwise working, which
    is the single most confusing failure this project has.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    if sys.argv and sys.argv[0]:
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.dirname(os.path.abspath(__file__))


_script_dir = _install_dir()

# Read the shared ~/.move_sr_bridge/config.ini for the configured log
# level and log path -- best-effort, since this process must start even
# if config.py can't be found/imported (e.g. an unexpected PyInstaller
# bundling gap, or a partial install).
sys.path.insert(0, _script_dir)
try:
    from version import __version__
except Exception:
    __version__ = "unknown"


class _RecordBuffer(logging.Handler):
    """Catch log records emitted before logging is configured.

    config.py logs through its own module logger, and everything it has
    to say -- "Created default config at ...", "Malformed config file
    ..." -- happens during the load_config() call below, which is
    necessarily *before* basicConfig() can run, because its result is
    what sets the level.  With no handler installed those records went to
    logging's last-resort stderr, which in a frozen helper means nowhere
    at all.  So the one process that creates config.ini was the one
    process that could never report having done so.
    """

    def __init__(self):
        logging.Handler.__init__(self, level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


_early_records = _RecordBuffer()
_root_logger = logging.getLogger()
_root_logger.addHandler(_early_records)
# config.py's logger is NOTSET, so it inherits this. Restored by
# basicConfig(level=...) below.
_root_logger.setLevel(logging.DEBUG)

# Why the level ended up where it did, reported at INFO once logging is up.
# Without this the helper had no way to say "I could not read your config"
# or "your level = DEBUG was ignored" -- and the log is the only support
# artefact this project has.  A silently-INFO helper hides every
# `Speaking:` line, which is the one trace that shows speech working.
_config_status = "ok"
try:
    import config as _config_mod

    _log_path = _config_mod.LOG_PATH
    _config_mod.ensure_state_dir()
    _cfg = _config_mod.load_config()
    _log_level_name = _cfg.get("logging", "level", fallback="INFO").strip().upper()
    _log_level = getattr(logging, _log_level_name, None)
    # isinstance, because getattr finds any module attribute and
    # logging.BASIC_FORMAT is a str.  NOTSET is rejected too: setLevel(0)
    # means "inherit", which here silently drops everything below WARNING
    # -- the same invisible outcome, reached a different way.
    if not isinstance(_log_level, int) or _log_level <= logging.NOTSET:
        _config_status = "unknown level %r, using INFO" % (_log_level_name,)
        _log_level = logging.INFO
except Exception as _cfg_err:
    # Fallback copy of config.STATE_DIR, used only on this degraded path.
    _config_status = "config.py unavailable (%s), using INFO" % (_cfg_err,)
    _state_dir = os.path.join(os.path.expanduser("~"), ".move_sr_bridge")
    _log_path = os.path.join(_state_dir, "Move_SR_Bridge.log")
    try:
        os.makedirs(_state_dir, exist_ok=True)
    except OSError:
        pass
    _log_level = logging.INFO

# Detached before basicConfig() runs, and this is load-bearing: basicConfig
# does nothing at all when the root logger already has a handler, and says
# nothing about having skipped.  Leaving the buffer attached would silently
# cost the log file its formatter -- timestamps and level names gone from
# the project's primary support artefact, with speech still working.
_root_logger.removeHandler(_early_records)

# mode="a": __init__.py (running inside Live) writes to this same file in
# append mode and logs several lines before this process even starts.
# Opening with mode="w" here would truncate those lines out from under it
# (and can tear an in-flight write if the timing overlaps).
#
# A file we cannot open must not be fatal -- losing the log is bad, but
# failing to start means losing speech entirely.  Fall back to console-only.
try:
    _handlers = [logging.FileHandler(_log_path, mode="a", encoding="utf-8")]
    _log_file_error = None
except OSError as _e:
    _handlers = []
    _log_file_error = _e

logging.basicConfig(
    level=_log_level,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=_handlers,
)
log = logging.getLogger("sr_helper")

# Belt and braces, not the fix for any observed bug: basicConfig() is a
# no-op when the root logger already has handlers, and it does NOT raise or
# warn when it skips -- `level=` is silently dropped along with everything
# else.  A frozen build could arrive here with logging already touched (a
# PyInstaller runtime hook, or any bundled import that configured it), and
# the symptom would be indistinguishable from the real bug this file
# already carries scars from: `level = DEBUG` honoured by
# `python sr_helper.py` and ignored by sr_helper_mac.  (That one was
# configparser missing from the frozen bundle -- see _config_status above
# and scripts/build_mac.py.)  Set the level on our own logger rather than
# trusting basicConfig to have done it.
log.setLevel(_log_level)
for _h in _handlers:
    _h.setLevel(_log_level)
    if _h not in logging.getLogger().handlers:
        log.addHandler(_h)
        log.propagate = False

# Also log to console if we have one (manual launch via .bat/.sh)
if sys.stderr and hasattr(sys.stderr, "write"):
    try:
        _console = logging.StreamHandler(sys.stderr)
        _console.setLevel(logging.INFO)
        _console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        log.addHandler(_console)
    except Exception:
        pass

if _log_file_error is not None:
    log.warning(
        "Move_SR_Bridge: Could not open log file %s (%s) -- logging to console only",
        _log_path,
        _log_file_error,
    )

# Replay whatever config.py said while there was nowhere to say it.  Done
# here rather than right after basicConfig() so these lines go through the
# same handlers as everything else, and filtered by the configured level
# because they were captured at DEBUG regardless of it.
for _record in _early_records.records:
    if _record.levelno >= _log_level:
        log.handle(_record)
_early_records.records = []

# ---------------------------------------------------------------------------
# Shutdown event -- signals all threads to exit
# ---------------------------------------------------------------------------
_shutdown = threading.Event()

# Guards the platform backend's shared mutable state (_vo_proc on macOS,
# concurrent Tolk DLL calls on Windows) against concurrent client-handler
# threads.
_backend_lock = threading.Lock()

# Maximum decoded characters to buffer per connection while waiting for a
# newline before giving up on that line (protects against unbounded memory
# growth from a client that never sends "\n").
#
# Characters, not bytes: the buffer is measured after decoding, so this is
# what len() actually counts.  Under UTF-8 a character is never fewer than
# one byte, so this stays a real bound on memory -- just a looser one than
# the name "bytes" would have promised.
_MAX_LINE_CHARS = 65536


# ===================================================================
#  Platform-specific screen reader backend
# ===================================================================

if sys.platform == "darwin":
    # ------------------------------------------------------------------
    #  macOS: VoiceOver via AppleScript (osascript)
    # ------------------------------------------------------------------
    import subprocess

    _vo_proc = None

    def _escape_applescript(text):
        """Escape text for safe embedding in AppleScript double-quoted strings."""
        return str(text).replace("\\", "\\\\").replace('"', '\\"')

    def _run_osascript(script):
        """Run an AppleScript snippet via osascript.  Returns True on success."""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()
                if stderr:
                    log.debug("Move_SR_Bridge: osascript stderr: %s", stderr)
                return False
            return True
        except FileNotFoundError:
            log.error("Move_SR_Bridge: osascript not found -- is this really macOS?")
            return False
        except subprocess.TimeoutExpired:
            log.warning("Move_SR_Bridge: osascript timed out")
            return False
        except Exception as e:
            log.warning("Move_SR_Bridge: osascript error: %s", e)
            return False

    def _fire_osascript(script):
        """Fire AppleScript asynchronously.  Non-blocking."""
        global _vo_proc
        with _backend_lock:
            if _vo_proc is not None and _vo_proc.poll() is None:
                try:
                    _vo_proc.kill()
                    _vo_proc.wait(timeout=1)
                except Exception:
                    pass
            try:
                _vo_proc = subprocess.Popen(
                    ["osascript", "-e", script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            except Exception as e:
                log.warning("Move_SR_Bridge: osascript error: %s", e)
                return False

    def _voiceover_running():
        """Check whether the VoiceOver process is running."""
        try:
            result = subprocess.run(
                ["pgrep", "-x", "VoiceOver"],
                capture_output=True, timeout=3,
            )
            return result.returncode == 0
        except Exception:
            return False

    def load_backend():
        """Initialise the macOS VoiceOver backend."""
        mac_ver = platform.mac_ver()[0]
        log.info("Move_SR_Bridge: Detected macOS %s (%s)", mac_ver or "?", platform.machine())

        if not _voiceover_running():
            log.warning(
                "Move_SR_Bridge: VoiceOver is not running -- speech will not work until "
                "VoiceOver is enabled (Cmd+F5)"
            )
            return True  # still allow the server to start

        # Probe whether AppleScript control is enabled
        if not _run_osascript('tell application "VoiceOver" to output ""'):
            log.warning(
                "Move_SR_Bridge: VoiceOver AppleScript control is not enabled.  "
                "Open VoiceOver Utility (VO+F8), go to General, and "
                'check "Allow VoiceOver to be controlled with AppleScript".'
            )
        else:
            log.info("Move_SR_Bridge: VoiceOver AppleScript control is enabled")
        return True

    def unload_backend():
        """Kill any lingering osascript process."""
        global _vo_proc
        with _backend_lock:
            if _vo_proc is not None and _vo_proc.poll() is None:
                try:
                    _vo_proc.kill()
                    _vo_proc.wait(timeout=1)
                except Exception:
                    pass
            _vo_proc = None

    def sr_speak(text):
        """Speak text via VoiceOver AppleScript."""
        escaped = _escape_applescript(text)
        if not _fire_osascript(
            'tell application "VoiceOver" to output "' + escaped + '"'
        ):
            log.warning("Move_SR_Bridge: VoiceOver speak failed for: %s", text)

    def sr_braille(text):
        """Braille is handled automatically by VoiceOver when it speaks."""
        pass

    def sr_cancel():
        """Silence VoiceOver."""
        _fire_osascript('tell application "VoiceOver" to output ""')

    # Both Live 12 Suite and Live 12 Beta report this.
    _LIVE_BUNDLE_ID = "com.ableton.live"

    def _frontmost_bundle_id():
        """Bundle id of the frontmost application, or None.

        `lsappinfo` is Launch Services' own CLI: ~12ms, and unlike
        `System Events` it needs no Accessibility permission, so it cannot
        raise a TCC prompt at the worst possible moment (a modal dialog).
        """
        try:
            asn = subprocess.run(
                ["lsappinfo", "front"],
                capture_output=True, text=True, timeout=2,
            )
            if asn.returncode != 0 or not asn.stdout.strip():
                return None
            info = subprocess.run(
                ["lsappinfo", "info", "-only", "bundleid", asn.stdout.strip()],
                capture_output=True, text=True, timeout=2,
            )
            # Output looks like: "CFBundleIdentifier"="com.ableton.live"
            parts = info.stdout.strip().split('"')
            return parts[3] if len(parts) >= 4 else None
        except Exception as e:
            log.debug("Move_SR_Bridge: could not read frontmost app: %s", e)
            return None

    def sr_dialog(text):
        """Announce a Live modal dialog -- but only if Live is in the background.

        When Live is the frontmost application, VoiceOver announces the
        dialog itself, with more detail than we have (title *and* buttons).
        Measured: our announcement was issued 1ms after the dialog opened
        and never reached VoiceOver, because VoiceOver's own focus
        announcement for the same dialog preempted it 261ms later. There is
        no way to win that race -- VoiceOver's AppleScript `output` command
        takes only a spelling type, with no queue or priority parameter.

        So do not compete. Speak only when Live is NOT frontmost, which is
        exactly when VoiceOver will say nothing and the user, hands on the
        Move, would otherwise have no idea why the device stopped
        responding.
        """
        front = _frontmost_bundle_id()
        if front == _LIVE_BUNDLE_ID:
            log.debug(
                "Move_SR_Bridge: dialog suppressed, Live is frontmost and "
                "VoiceOver announces it natively: %s", text
            )
            return
        log.debug(
            "Move_SR_Bridge: dialog announced, frontmost app is %s: %s",
            front or "unknown", text,
        )
        sr_speak(text)

else:
    # ------------------------------------------------------------------
    #  Windows: Tolk screen reader abstraction library
    # ------------------------------------------------------------------
    import ctypes

    _tolk = None

    def load_backend():
        """Load and initialise the Tolk screen reader library."""
        global _tolk
        dll_path = os.path.join(_script_dir, "Tolk.dll")

        if not os.path.exists(dll_path):
            log.error("Move_SR_Bridge: Tolk.dll not found: %s", dll_path)
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
                log.info("Move_SR_Bridge: Tolk loaded -- detected screen reader: %s", sr)
                log.info(
                    "Move_SR_Bridge:   Speech: %s, Braille: %s",
                    _tolk.Tolk_HasSpeech(),
                    _tolk.Tolk_HasBraille(),
                )
            else:
                log.warning(
                    "Move_SR_Bridge: Tolk loaded but no screen reader detected -- "
                    "will retry when commands arrive"
                )
            return True
        except OSError as e:
            log.error("Move_SR_Bridge: Failed to load Tolk.dll: %s", e)
            _tolk = None
            return False

    def unload_backend():
        """Unload the Tolk library (releases COM, etc.)."""
        global _tolk
        if _tolk is not None:
            # Take the same lock the speak/braille calls use, so this
            # cannot pull the library out from under one already running
            # on a daemon client thread.
            with _backend_lock:
                try:
                    _tolk.Tolk_Unload()
                    log.info("Move_SR_Bridge: Tolk unloaded")
                except Exception:
                    pass
                # Cleared so a later sr_speak() returns instead of calling
                # into an unloaded library.  Client threads are daemons and
                # can still be mid-command when shutdown begins.
                _tolk = None

    def sr_speak(text):
        """Speak text via the active screen reader."""
        if _tolk is None:
            return
        try:
            with _backend_lock:
                _tolk.Tolk_Speak(str(text), True)  # interrupt=True
        except Exception as e:
            log.warning("Move_SR_Bridge: speak error: %s", e)

    def sr_braille(text):
        """Display text on braille display via the active screen reader."""
        if _tolk is None:
            return
        try:
            with _backend_lock:
                _tolk.Tolk_Braille(str(text))
        except Exception as e:
            log.warning("Move_SR_Bridge: braille error: %s", e)

    def sr_cancel():
        """Silence the active screen reader."""
        if _tolk is None:
            return
        try:
            with _backend_lock:
                _tolk.Tolk_Silence()
        except Exception as e:
            log.warning("Move_SR_Bridge: cancel error: %s", e)

    def sr_dialog(text):
        """Announce a Live modal dialog.

        The macOS backend suppresses this when Live is frontmost, because
        VoiceOver announces the dialog itself and wins the race anyway.
        Windows keeps the old unconditional behaviour: the same reasoning
        probably applies to NVDA/JAWS, but this project has no Windows
        machine to measure it on, and guessing would risk silencing a
        message that currently works.
        """
        sr_speak(text)


# ===================================================================
#  Shared: command dispatch, TCP server, main
# ===================================================================


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------
def _handle_speak(msg):
    text = msg.get("text", "")
    log.debug("Move_SR_Bridge: Speaking: %s", text)
    sr_speak(text)


def _handle_quit(_msg):
    log.info("Move_SR_Bridge: Received quit command, shutting down")
    _shutdown.set()


def _handle_dialog(msg):
    text = msg.get("text", "")
    if text:
        sr_dialog(text)


COMMANDS = {
    "speak": _handle_speak,
    "braille": lambda msg: sr_braille(msg.get("text", "")),
    "cancel": lambda _: sr_cancel(),
    "dialog": _handle_dialog,
    "quit": _handle_quit,
}


# ---------------------------------------------------------------------------
# Client handler
# ---------------------------------------------------------------------------
def handle_client(conn, addr):
    log.info("Move_SR_Bridge: Client connected: %s", addr)
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

            if "\n" not in buffer and len(buffer) > _MAX_LINE_CHARS:
                log.warning(
                    "Move_SR_Bridge: Line from %s exceeded %d characters with "
                    "no newline, dropping buffer",
                    addr,
                    _MAX_LINE_CHARS,
                )
                buffer = ""
                continue

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    if not isinstance(msg, dict):
                        log.warning("Move_SR_Bridge: Bad message (not a JSON object): %s", line)
                        continue
                    cmd = msg.get("cmd", "")
                    handler = COMMANDS.get(cmd)
                    if handler:
                        handler(msg)
                    else:
                        log.warning("Move_SR_Bridge: Unknown command: %s", cmd)
                except json.JSONDecodeError as e:
                    log.warning("Move_SR_Bridge: Bad JSON: %s", e)
                except Exception as e:
                    # One malformed command must not take the connection
                    # down with it.  This thread has no console in a frozen
                    # build, so an escaping exception would end the session's
                    # speech and leave no trace of why.
                    log.exception(
                        "Move_SR_Bridge: Command %r failed: %s", line, e
                    )
    except (ConnectionResetError, ConnectionAbortedError, OSError):
        pass
    except Exception as e:
        log.exception("Move_SR_Bridge: Client handler for %s failed: %s", addr, e)
    finally:
        log.info("Move_SR_Bridge: Client disconnected: %s", addr)
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log.info("Move_SR_Bridge: Move-SR-Bridge Helper starting (version %s)", __version__)
    log.info("Move_SR_Bridge: Log file: %s", _log_path)
    # Stated explicitly so "my level = DEBUG is being ignored" is a fact in
    # the log rather than something the user has to infer from absence.
    log.info(
        "Move_SR_Bridge: Log level: %s (config: %s)%s",
        logging.getLevelName(log.getEffectiveLevel()),
        _config_status,
        " [frozen]" if getattr(sys, "frozen", False) else "",
    )

    if not load_backend():
        log.error("Move_SR_Bridge: Cannot continue without screen reader backend")
        sys.exit(1)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform == "win32":
        # Windows SO_REUSEADDR is not the POSIX option of the same name: it
        # lets a second process bind a port an active listener already holds,
        # so a stray helper would silently steal 8765 from the running one
        # instead of failing to start.  SO_EXCLUSIVEADDRUSE is the Windows
        # way to ask for an exclusive bind.
        try:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        except (AttributeError, OSError) as e:
            log.debug("Move_SR_Bridge: SO_EXCLUSIVEADDRUSE unavailable (%s), continuing", e)
    else:
        # POSIX: lets us rebind immediately while an old connection lingers
        # in TIME_WAIT.  Does not permit stealing an active listener.
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((HOST, PORT))
    except OSError as e:
        log.error("Move_SR_Bridge: Cannot bind to port %d: %s", PORT, e)
        # Release the backend we just loaded. Skipping this leaves Tolk
        # loaded and COM initialised on the Windows path, in a process
        # that is about to exit having done nothing.
        unload_backend()
        sys.exit(1)

    server.listen(2)
    server.settimeout(1.0)
    log.info("Move_SR_Bridge: Listening on %s:%d", HOST, PORT)

    # Announced only once the port is actually ours.  Saying it before
    # bind() meant a second helper started against an occupied 8765 told
    # the user it was working and then exited -- the one case where the
    # announcement is most likely to be the only feedback they get.
    sr_speak("Move SR Bridge helper started")

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
            except OSError as e:
                # accept() can fail for reasons that say nothing about the
                # listener: ECONNABORTED when a client goes away mid-
                # handshake, EMFILE when the process is briefly out of
                # descriptors.  Letting those escape the loop closed the
                # socket and ended the process -- and nothing on the Live
                # side watches the helper after launch, so the user got
                # silence for the rest of the session with only a
                # "Helper stopped" line to explain it.
                if _shutdown.is_set():
                    break
                log.warning(
                    "Move_SR_Bridge: accept() failed (%s), continuing", e
                )
                continue
    except KeyboardInterrupt:
        log.info("Move_SR_Bridge: Keyboard interrupt, shutting down")
    finally:
        server.close()
        unload_backend()
        log.info("Move_SR_Bridge: Move-SR-Bridge Helper stopped")


if __name__ == "__main__":
    main()
