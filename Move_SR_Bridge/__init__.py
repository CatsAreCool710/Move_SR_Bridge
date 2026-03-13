# __init__.py - Ableton Move MIDI Remote Script with screen reader support
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
Move-SR-Bridge -- Drop-in replacement for the stock Ableton Move MIDI
Remote Script that adds screen reader output (speech + braille).

Supports NVDA, JAWS, Window-Eyes, ZoomText, and System Access via the
Tolk abstraction library.

When Live renders content for the Move's 128x64 OLED display, this script
intercepts the text and sends it via TCP to a companion helper process
(sr_helper.exe) which forwards it to the active screen reader.  The OLED
keeps working normally.

The helper process is launched automatically when this script loads and
stopped when it unloads.
"""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)
logger.info("Move_SR_Bridge: Script loading...")

# --------------------------------------------------------------------------
# Re-export get_capabilities from the original Move package so Live can
# identify the hardware (vendor/product IDs, MIDI ports).
# --------------------------------------------------------------------------
from Move import get_capabilities  # noqa: F401

from Move import Move as _OriginalMove
from Move import Specification as _OriginalSpecification

logger.info("Move_SR_Bridge: Original Move script imported successfully")

# --------------------------------------------------------------------------
# Content types for type-aware announcements
# --------------------------------------------------------------------------
_content_types = {}
for _name, _import in [
    ("vertical", "VerticalListContent"),
    ("horizontal", "HorizontalListContent"),
    ("notification", "NotificationContent"),
    ("content", "Content"),
]:
    try:
        _mod = __import__("Move.display_util", fromlist=[_import])
        _content_types[_name] = getattr(_mod, _import)
    except (ImportError, AttributeError):
        pass

logger.info(
    "Move_SR_Bridge: Content types available: %s",
    list(_content_types.keys()) if _content_types else "none (generic fallback)",
)

# --------------------------------------------------------------------------
# Helper process management
# --------------------------------------------------------------------------
_helper_proc = None
_we_launched_helper = False
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

_HELPER_HOST = "127.0.0.1"
_HELPER_PORT = 8765


def _helper_is_running():
    """Probe TCP port 8765 to check if a helper process is already listening."""
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.2)
        s.connect((_HELPER_HOST, _HELPER_PORT))
        s.close()
        return True
    except OSError:
        return False


def _start_helper():
    """Launch sr_helper.exe as a hidden background process.

    If a helper is already listening on port 8765 (e.g. started manually
    via start_helper.bat), we skip launching and set _we_launched_helper
    to False so we don't kill it on disconnect.
    """
    global _helper_proc, _we_launched_helper

    if _helper_is_running():
        logger.info(
            "Move_SR_Bridge: Helper already running on port %d, "
            "not launching a new one",
            _HELPER_PORT,
        )
        _we_launched_helper = False
        return

    exe_path = os.path.join(_SCRIPT_DIR, "sr_helper.exe")
    if not os.path.exists(exe_path):
        logger.warning(
            "Move_SR_Bridge: sr_helper.exe not found at %s -- "
            "speech will not work unless the helper is started manually",
            exe_path,
        )
        _we_launched_helper = False
        return

    try:
        CREATE_NO_WINDOW = 0x08000000
        _helper_proc = subprocess.Popen(
            [exe_path],
            cwd=_SCRIPT_DIR,
            creationflags=CREATE_NO_WINDOW,
        )
        _we_launched_helper = True
        logger.info(
            "Move_SR_Bridge: Helper process started (PID %d)",
            _helper_proc.pid,
        )
    except Exception as e:
        logger.error("Move_SR_Bridge: Failed to start helper: %s", e)
        _helper_proc = None
        _we_launched_helper = False


def _stop_helper():
    """Stop the helper process if we launched it, otherwise just close the socket."""
    global _helper_proc, _we_launched_helper

    if not _we_launched_helper:
        # We didn't launch the helper -- just drop the socket connection
        # without sending quit so a manually-started helper keeps running.
        try:
            from . import sr_bridge

            sr_bridge.close_socket()
        except Exception:
            pass
        logger.info(
            "Move_SR_Bridge: Disconnected from external helper (left it running)"
        )
        return

    # We launched the helper -- send quit and clean up the process
    try:
        from . import sr_bridge

        sr_bridge.disconnect()  # sends quit + closes socket
    except Exception:
        pass

    if _helper_proc is not None:
        # Give it a moment, then terminate if still alive
        try:
            _helper_proc.wait(timeout=2)
            logger.info("Move_SR_Bridge: Helper process exited cleanly")
        except subprocess.TimeoutExpired:
            try:
                _helper_proc.terminate()
                _helper_proc.wait(timeout=2)
                logger.info("Move_SR_Bridge: Helper process terminated")
            except Exception as e:
                logger.warning(
                    "Move_SR_Bridge: Could not terminate helper: %s", e
                )
        except Exception:
            pass

    _helper_proc = None
    _we_launched_helper = False


# --------------------------------------------------------------------------
# Display content formatting
# --------------------------------------------------------------------------
def _format_content(content):
    """Extract human-readable text from a display content object."""
    lines = getattr(content, "lines", None)
    if not lines:
        return None

    text_lines = [str(line).strip() for line in lines if line and str(line).strip()]
    if not text_lines:
        return None

    # Vertical list menus -- announce selected item
    if "vertical" in _content_types and isinstance(
        content, _content_types["vertical"]
    ):
        list_index = getattr(content, "list_index", None)
        if list_index is not None and 0 <= list_index < len(text_lines):
            return text_lines[list_index]
        return ", ".join(text_lines)

    # Horizontal list (name + value)
    if "horizontal" in _content_types and isinstance(
        content, _content_types["horizontal"]
    ):
        if len(text_lines) == 2:
            return text_lines[0] + ": " + text_lines[1]
        return ", ".join(text_lines)

    # Notifications
    if "notification" in _content_types and isinstance(
        content, _content_types["notification"]
    ):
        return " ".join(text_lines)

    return ", ".join(text_lines)


# --------------------------------------------------------------------------
# Display hook installation
# --------------------------------------------------------------------------
def _install_display_hook(control_surface):
    """Monkey-patch Display.display() to intercept content for screen reader."""
    from . import sr_bridge

    display = control_surface.display
    if display is None:
        logger.warning(
            "Move_SR_Bridge: No display object found, cannot install hook"
        )
        return False

    original_display_method = display.display
    last_announced = [None]

    def _intercepted_display(content):
        try:
            text = _format_content(content)
            if text and text != last_announced[0]:
                last_announced[0] = text
                sr_bridge.speak(text)
                sr_bridge.braille(text)
        except Exception as e:
            logger.debug("Move_SR_Bridge: Display hook error: %s", e)
        original_display_method(content)

    display.display = _intercepted_display
    logger.info("Move_SR_Bridge: Display hook installed")

    sr_bridge.speak("Move connected")
    sr_bridge.braille("Move connected")
    return True


# --------------------------------------------------------------------------
# Move subclass with screen reader hooks
# --------------------------------------------------------------------------
class Move(_OriginalMove):
    _sr_hook_installed = False

    def _try_install_hook(self):
        if self._sr_hook_installed:
            return
        if self.display is not None:
            try:
                if _install_display_hook(self):
                    self._sr_hook_installed = True
            except Exception as e:
                logger.error(
                    "Move_SR_Bridge: Failed to install display hook: %s", e
                )

    def on_identified(self, response_bytes):
        super().on_identified(response_bytes)
        logger.info(
            "Move_SR_Bridge: Move identified, installing display hook..."
        )
        self._try_install_hook()

    def disconnect(self):
        if self._sr_hook_installed:
            try:
                from . import sr_bridge

                sr_bridge.speak("Move disconnected")
                sr_bridge.braille("Move disconnected")
            except Exception:
                pass
        logger.info("Move_SR_Bridge: Script unloading")
        _stop_helper()
        super().disconnect()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def create_instance(c_instance):
    logger.info("Move_SR_Bridge: Creating control surface instance")
    _start_helper()
    return Move(specification=_OriginalSpecification, c_instance=c_instance)


logger.info("Move_SR_Bridge: Script loaded successfully")
