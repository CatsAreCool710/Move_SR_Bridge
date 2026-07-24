# speech_history_logger.py - macOS-only debug tool that logs every
# phrase VoiceOver speaks (Move_SR_Bridge's own speech or Live's native
# speech), for diagnosing double-speech.
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
Speech History Logger -- standalone macOS debug tool for Move-SR-Bridge.

Polls VoiceOver's AppleScript "content of the last phrase" property and
logs every distinct phrase VoiceOver speaks -- whether triggered by
Move_SR_Bridge (via sr_helper.py) or by Ableton Live's own native
VoiceOver narration (e.g. on track/scene selection change).

This is entirely separate from sr_helper.py: it is not installed to
Live, not started automatically, and not gated by config.ini's
[logging] level.  Run it manually, alongside the helper, only while
diagnosing double-speech.  It performs no automatic tagging of which
source spoke each phrase -- compare timestamps against Move_SR_Bridge.log
(with [logging] level = DEBUG) by eye.

Requires "Allow VoiceOver to be controlled with AppleScript" enabled in
VoiceOver Utility > General.  The first osascript call to VoiceOver may
also trigger a one-time macOS Automation permission dialog.

Usage:
    python3 tools/speech_history_logger.py [--interval SECONDS] [--log-path PATH]

Log output: tools/speech_history.log (truncated on each run) and stdout.
"""

import argparse
import logging
import os
import subprocess
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_LOG_PATH = os.path.join(_SCRIPT_DIR, "speech_history.log")
_DEFAULT_INTERVAL = 0.15

_LAST_PHRASE_SCRIPT = """\
global spokenPhrase
tell application "VoiceOver"
    set spokenPhrase to the content of the last phrase
end tell
spokenPhrase
"""

_ENABLE_APPLESCRIPT_HINT = (
    'VoiceOver AppleScript control is not enabled (or VoiceOver is not '
    'responding).  Open VoiceOver Utility (VO+F8), go to General, and '
    'check "Allow VoiceOver to be controlled with AppleScript".'
)

_WARNING_THROTTLE_SECONDS = 5.0


def _setup_logging(log_path):
    logger = logging.getLogger("speech_history")
    logger.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(console_handler)

    return logger


def _voiceover_running():
    try:
        result = subprocess.run(
            ["pgrep", "-x", "VoiceOver"], capture_output=True, timeout=3
        )
        return result.returncode == 0
    except Exception:
        return False


def _poll_last_phrase():
    """Run the polling AppleScript once.  Returns (success, phrase)."""
    try:
        result = subprocess.run(
            ["osascript", "-e", _LAST_PHRASE_SCRIPT],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return False, ""
        return True, result.stdout.strip("\n")
    except Exception:
        return False, ""


def run(logger, interval, log_path):
    if not _voiceover_running():
        logger.warning(
            "VoiceOver is not running -- waiting for it to start "
            "(Cmd+F5 to enable VoiceOver)"
        )

    logger.info(
        "Speech History Logger started (interval=%.3fs, log=%s)",
        interval,
        log_path,
    )
    logger.info(
        "Note: the first VoiceOver AppleScript call may trigger a "
        "one-time macOS Automation permission dialog."
    )

    last_phrase = None
    last_warning_time = 0.0

    try:
        while True:
            ok, phrase = _poll_last_phrase()
            now = time.monotonic()

            if not ok:
                if now - last_warning_time >= _WARNING_THROTTLE_SECONDS:
                    logger.warning(_ENABLE_APPLESCRIPT_HINT)
                    last_warning_time = now
            else:
                if phrase and phrase != last_phrase:
                    last_phrase = phrase
                    logger.info(phrase)

            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt, shutting down")
    finally:
        logger.info("Speech History Logger stopped")


def main():
    if sys.platform != "darwin":
        print(
            "speech_history_logger.py only works on macOS (it polls "
            "VoiceOver via AppleScript).",
            file=sys.stderr,
        )
        sys.exit(1)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--interval",
        type=float,
        default=_DEFAULT_INTERVAL,
        help="Polling interval in seconds (default: %.2f)" % _DEFAULT_INTERVAL,
    )
    parser.add_argument(
        "--log-path",
        default=_DEFAULT_LOG_PATH,
        help="Log file path (default: %s)" % _DEFAULT_LOG_PATH,
    )
    args = parser.parse_args()

    logger = _setup_logging(args.log_path)
    run(logger, args.interval, args.log_path)


if __name__ == "__main__":
    main()
