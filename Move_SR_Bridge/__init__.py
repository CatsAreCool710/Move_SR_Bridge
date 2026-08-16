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

Platform backends:
    Windows: NVDA, JAWS, Window-Eyes, ZoomText, System Access via Tolk
    macOS:   VoiceOver via AppleScript (Tahoe 26 or later)

When Live renders content for the Move's 128x64 OLED display, this script
intercepts the text and sends it via TCP to a companion helper process
(sr_helper.exe on Windows, sr_helper_mac on macOS) which forwards it to
the active screen reader.  The OLED keeps working normally.

The helper process is launched automatically when this script loads and
stopped when it unloads.
"""

import collections
import logging
import os
import socket
import subprocess
import sys
import threading
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------
# Load the config module first -- it owns the per-user state directory that
# the log file lives in.  Guarded: config is an optional convenience, and a
# bare ImportError here would propagate out of module import, making Live
# skip the script entirely so it never appears in the Control Surface
# dropdown.  Losing the config file must never cost the user the whole
# control surface.
# --------------------------------------------------------------------------
try:
    from . import config as _config_mod
except Exception:  # pragma: no cover -- degraded install
    _config_mod = None
    # Fallback copy of config.STATE_DIR, used only on this degraded path.
    _STATE_DIR = os.path.join(os.path.expanduser("~"), ".move_sr_bridge")
    _LOG_PATH = os.path.join(_STATE_DIR, "Move_SR_Bridge.log")
else:
    _STATE_DIR = _config_mod.STATE_DIR
    _LOG_PATH = _config_mod.LOG_PATH

try:
    from .version import __version__
except Exception:  # pragma: no cover -- degraded install
    __version__ = "unknown"

logger = logging.getLogger(__name__)
if not logger.handlers:
    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
        _log_handler = logging.FileHandler(_LOG_PATH, mode="a", encoding="utf-8")
        _log_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )
        logger.addHandler(_log_handler)
        logger.setLevel(logging.DEBUG)
    except OSError:
        pass

logger.info("Move_SR_Bridge: Script loading (version %s)...", __version__)

# --------------------------------------------------------------------------
# Load user configuration (~/.move_sr_bridge/config.ini)
#
# Everything here is best-effort, and the blanket `except Exception` is the
# point of it.  This runs at *module import*, inside Live, so anything that
# escapes makes Live skip the script and Move_SR_Bridge vanishes from the
# Control Surface dropdown -- the exact cost the guard above refuses to pay
# for a missing config.py, and there is no reason a *malformed* one should
# cost more than a missing one.
#
# config.py's own handler catches configparser.Error, which does NOT cover
# the likeliest corruption: config.ini is documented as user-editable, and
# saving it from Notepad in its default ANSI encoding makes
# `read(encoding="utf-8")` raise UnicodeDecodeError -- a ValueError.  A bad
# `level =` value is the same story from the other direction: getattr can
# hand back any module attribute, and logging.BASIC_FORMAT is a str, so
# setLevel() raises ValueError on it.
#
# sr_helper.py has always done both checks (see its _config_status block);
# this is the same thing on the side where the blast radius is larger.
# --------------------------------------------------------------------------
import configparser as _configparser

# Must stay in step with config.py's _DEFAULTS -- an installer-side copy
# drifting out of sync (missing a whole section) has shipped here before.
_DEFAULT_SETTINGS = {
    "debounce": {"enabled": "true", "delay_ms": "300"},
    "logging": {"level": "INFO"},
    "speech": {"step_toggles": "true"},
}


def _fallback_config():
    cfg = _configparser.ConfigParser()
    cfg.read_dict(_DEFAULT_SETTINGS)
    return cfg


# Why the level ended up where it did, reported once logging is up.  A
# silently-INFO script hides every DEBUG trace, which is indistinguishable
# from "the hook never ran" in the log -- the project's only support
# artefact.
_config_status = "ok"
_log_level = logging.INFO

if _config_mod is None:
    _cfg = _fallback_config()
    _config_status = (
        "config.py is missing from the install directory (%s), using "
        "built-in defaults -- reinstall to restore config.ini support"
        % (_SCRIPT_DIR,)
    )
else:
    try:
        _cfg = _config_mod.load_config()
    except Exception as _cfg_err:
        _cfg = _fallback_config()
        _config_status = "config.ini unreadable (%s), using built-in defaults" % (
            _cfg_err,
        )

    try:
        _log_level_name = _cfg.get("logging", "level", fallback="INFO").strip().upper()
    except Exception:
        _log_level_name = "INFO"

    _level_attr = getattr(logging, _log_level_name, None)
    # isinstance, not a None check: getattr finds any module attribute, and
    # `level = BASIC_FORMAT` would otherwise hand setLevel() a format string.
    if isinstance(_level_attr, int) and _level_attr > logging.NOTSET:
        _log_level = _level_attr
    elif _config_status == "ok":
        # NOTSET is excluded on purpose: setLevel(0) inherits from the root
        # logger, which silently drops everything below WARNING.
        _config_status = "unknown level %r, using INFO" % (_log_level_name,)

logger.setLevel(_log_level)
if _config_status != "ok":
    logger.error("Move_SR_Bridge: %s", _config_status)


# --------------------------------------------------------------------------
# Reporting for the catch-alls that keep this script alive inside Live
# --------------------------------------------------------------------------
_reported_failures = set()


def _log_failure(site, exc):
    """Report an exception that was swallowed to protect a Live callback.

    Loudly the first time, quietly after.  Both call sites sit on paths
    Live drives several times a second, so logging every occurrence at
    ERROR would bury the log in one repeated line -- but logging them all
    at DEBUG (which is what they used to do) means that at the default
    `level = INFO` a hook failing on every single frame produces a
    completely silent, completely dead bridge.  Neither end of that is
    usable, so: first occurrence at ERROR, the rest at DEBUG.
    """
    if site in _reported_failures:
        logger.debug("Move_SR_Bridge: %s error: %s", site, exc)
    else:
        _reported_failures.add(site)
        logger.error(
            "Move_SR_Bridge: %s error: %s "
            "(repeats of this one are logged at DEBUG)",
            site,
            exc,
        )

# --------------------------------------------------------------------------
# Re-export get_capabilities from the original Move package so Live can
# identify the hardware (vendor/product IDs, MIDI ports).
# --------------------------------------------------------------------------
from Move import get_capabilities  # noqa: F401

from Move import Move as _OriginalMove
from Move import Specification as _OriginalSpecification

# Used to read Live's modal-dialog state directly (see _dialog_is_open).
# Guarded so the module still imports outside Live, e.g. under the tests.
try:
    import Live as _Live
except Exception:  # pragma: no cover -- not running inside Live
    _Live = None

logger.info("Move_SR_Bridge: Original Move script imported successfully")

# --------------------------------------------------------------------------
# Content types for type-aware announcements
# --------------------------------------------------------------------------
_content_types = {}
# "content" is registered but deliberately never read by _format_content:
# plain Content is what the final fallback handles, and it needs no
# isinstance test to do so.  It earns its place twice over anyway --
# it feeds the startup diagnostic below, which is how a failed
# display_util import is recognised, and tests/test_format_content.py's
# setUp asserts all four keys are present.  That assertion is what stops
# the formatting tests going vacuous: with an empty _content_types every
# isinstance falls through to the fallback and the tests pass while
# testing nothing.  Do not delete it as dead, and do not "complete" it
# with a branch.
for _name, _import in [
    ("vertical", "VerticalListContent"),
    ("horizontal", "HorizontalListContent"),
    ("notification", "NotificationContent"),
    ("content", "Content"),
]:
    try:
        _mod = __import__("Move.display_util", fromlist=[_import])
        _content_types[_name] = getattr(_mod, _import)
    except ImportError:
        logger.debug(
            "Move_SR_Bridge: Could not import Move.display_util"
        )
    except AttributeError:
        logger.debug(
            "Move_SR_Bridge: Move.display_util has no %s", _import
        )

logger.info(
    "Move_SR_Bridge: Content types available: vertical=%s, "
    "horizontal=%s, notification=%s, content=%s",
    "vertical" in _content_types,
    "horizontal" in _content_types,
    "notification" in _content_types,
    "content" in _content_types,
)

# --------------------------------------------------------------------------
# Helper process management
# --------------------------------------------------------------------------
# Ownership of the helper process is recorded by _helper_proc alone: it is
# non-None exactly when we launched the helper ourselves and are therefore
# responsible for shutting it down.  There is deliberately no separate
# "we launched it" flag -- Live creates one control surface instance per
# control-surface slot and they all share this module's globals, so a
# second instance probing the port would otherwise clear the ownership
# recorded by the instance that actually spawned the process, leaking the
# helper past Live's exit.
#
# _active_instances counts live control surface instances so the helper is
# only shut down once the last one disconnects.
_helper_proc = None
_active_instances = 0

# _helper_lock guards _helper_proc and _active_instances and nothing else.
# It is never held across a blocking call -- Live drives connect/disconnect
# on its control surface callback thread, so a lock held across Popen() or a
# multi-second teardown stalls Live's UI behind it.
_helper_lock = threading.Lock()

# _helper_transition serialises a whole start or stop sequence instead, so
# the two can never interleave.  Held for seconds at a time by design.
_helper_transition = threading.Lock()

# Set when our own helper exited but its listening socket had not closed
# yet.  A start that probes the port during that window would otherwise
# read "port busy" as "somebody else's helper is running", record no
# ownership, and never launch one -- silence for the rest of the session.
_helper_port_lingering = [False]

_HELPER_HOST = "127.0.0.1"
_HELPER_PORT = 8765


def _helper_is_running():
    """Probe TCP port 8765 to check if a helper process is already listening."""
    # try/finally, not a bare close() on the success path: this is called up
    # to 20 times per start and 10 per stop, and a failed connect() would
    # otherwise drop an unclosed socket for the GC to find.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(0.2)
        s.connect((_HELPER_HOST, _HELPER_PORT))
        return True
    except OSError:
        return False
    finally:
        try:
            s.close()
        except OSError:
            pass


def _start_helper():
    """Register a control surface instance, launching the helper if needed.

    Detects the platform and launches the appropriate helper:
        Windows: sr_helper.exe (hidden window)
        macOS:   sr_helper_mac

    Called once per control surface instance.  The helper is launched only
    for the first instance that finds no helper already running; later
    instances just increment the refcount and share it.  If a helper is
    already listening on port 8765 (e.g. started manually via
    start_helper.bat/.sh) we leave _helper_proc as None, which is what
    tells _stop_helper() not to kill it.
    """
    global _helper_proc, _active_instances

    # Bookkeeping only -- released immediately, before anything blocking.
    with _helper_lock:
        _active_instances += 1
        existing = _helper_proc
        instance_count = _active_instances

    if existing is not None:
        logger.info(
            "Move_SR_Bridge: Sharing helper we already launched "
            "(PID %d); %d control surface instance(s) now active",
            existing.pid,
            instance_count,
        )
        return

    # Everything below can block for seconds. _helper_transition (not
    # _helper_lock) keeps it from interleaving with a concurrent teardown.
    with _helper_transition:
        with _helper_lock:
            if _helper_proc is not None:
                return          # another slot launched one while we waited

        # Read outside _helper_lock: this flag is guarded by
        # _helper_transition (which both this function and
        # _shutdown_owned_helper hold while touching it), and _helper_lock
        # deliberately guards _helper_proc and _active_instances and
        # nothing else.  Taking it here implied a second discipline that
        # the write side never followed.
        lingering = _helper_port_lingering[0]
        _helper_port_lingering[0] = False

        if _helper_is_running():
            # A busy port immediately after we tore down our own helper is
            # far more likely to be that helper's socket still closing than
            # a manually-started one. Give it a moment before concluding
            # the helper is somebody else's and leaving it alone.
            if lingering:
                for _ in range(20):  # up to ~2s
                    time.sleep(0.1)
                    if not _helper_is_running():
                        break
            if _helper_is_running():
                logger.info(
                    "Move_SR_Bridge: Helper already running on port %d, "
                    "not launching a new one (will leave it running on "
                    "disconnect)",
                    _HELPER_PORT,
                )
                return

        if sys.platform == "darwin":
            exe_path = os.path.join(_SCRIPT_DIR, "sr_helper_mac")
            helper_name = "sr_helper_mac"
        else:
            exe_path = os.path.join(_SCRIPT_DIR, "sr_helper.exe")
            helper_name = "sr_helper.exe"

        if not os.path.exists(exe_path):
            logger.warning(
                "Move_SR_Bridge: %s not found at %s -- "
                "speech will not work unless the helper is started manually",
                helper_name,
                exe_path,
            )
            return

        try:
            if sys.platform == "darwin":
                proc = subprocess.Popen(
                    [exe_path],
                    cwd=_SCRIPT_DIR,
                )
            else:
                CREATE_NO_WINDOW = 0x08000000
                proc = subprocess.Popen(
                    [exe_path],
                    cwd=_SCRIPT_DIR,
                    creationflags=CREATE_NO_WINDOW,
                )
            logger.info(
                "Move_SR_Bridge: Helper process started (PID %d)", proc.pid
            )

            # Verify it actually stayed alive and started listening before
            # declaring success -- Popen() succeeding only means the OS could
            # launch it, not that it didn't crash immediately afterward.
            listening = False
            for _ in range(10):  # poll for up to ~1s
                if proc.poll() is not None:
                    break
                if _helper_is_running():
                    listening = True
                    break
                time.sleep(0.1)

            if proc.poll() is not None:
                logger.error(
                    "Move_SR_Bridge: Helper process exited immediately "
                    "(exit code %s) -- speech will not work; check %s "
                    "for details",
                    proc.poll(),
                    _LOG_PATH,
                )
                return
            if not listening:
                logger.warning(
                    "Move_SR_Bridge: Helper process (PID %d) did not start "
                    "listening on port %d within 1s -- speech may be delayed "
                    "or unavailable",
                    proc.pid,
                    _HELPER_PORT,
                )
            with _helper_lock:
                _helper_proc = proc
        except Exception as e:
            logger.error("Move_SR_Bridge: Failed to start helper: %s", e)


def _stop_helper():
    """Deregister a control surface instance, stopping the helper if last.

    Only the last instance to disconnect tears anything down -- while any
    other control surface slot is still using Move_SR_Bridge, the helper
    and its socket stay up.  The helper is killed only if we launched it
    (_helper_proc is not None); a manually-started one is left running.
    """
    global _helper_proc, _active_instances

    with _helper_lock:
        if _active_instances > 0:
            _active_instances -= 1
        if _active_instances > 0:
            logger.info(
                "Move_SR_Bridge: %d control surface instance(s) still "
                "active, leaving helper running",
                _active_instances,
            )
            return
        # Last instance out: take ownership of the process handle (if any)
        # and release the lock before doing the blocking shutdown waits.
        proc = _helper_proc
        _helper_proc = None

    if proc is None:
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

    # We launched the helper -- send quit and clean up the process.
    # _helper_transition (not _helper_lock) is held for the whole teardown,
    # so a concurrent _start_helper() cannot probe port 8765 while this
    # helper's socket is still closing and mistake it for an external one.
    with _helper_transition:
        _shutdown_owned_helper(proc)


def _shutdown_owned_helper(proc):
    """Stop a helper we launched. Caller holds _helper_transition."""
    try:
        from . import sr_bridge

        sr_bridge.disconnect()  # sends quit + closes socket
    except Exception:
        pass

    # Give it a moment, then terminate if still alive
    try:
        proc.wait(timeout=1)
        logger.info("Move_SR_Bridge: Helper process exited cleanly")
    except subprocess.TimeoutExpired:
        try:
            proc.terminate()
            proc.wait(timeout=1)
            logger.info("Move_SR_Bridge: Helper process terminated")
        except Exception as e:
            # SIGTERM did not take either -- the helper can be blocked in a
            # subprocess.run() call to osascript, which ignores it. Without
            # this last step the process outlives Live entirely, keeping
            # port 8765 and blocking the next session's helper.
            logger.warning(
                "Move_SR_Bridge: Could not terminate helper (%s), killing", e
            )
            try:
                proc.kill()
                proc.wait(timeout=1)
                logger.info("Move_SR_Bridge: Helper process killed")
            except Exception as e2:
                logger.warning(
                    "Move_SR_Bridge: Could not kill helper: %s", e2
                )
    except Exception:
        pass

    # Positively confirm the helper's listening socket is actually closed
    # (not just that the process handle exited) before returning. A
    # subsequent _start_helper() call uses _helper_is_running() as its
    # source of truth for whether a new helper needs to be spawned, and
    # sr_helper.py's accept loop can take up to ~1s after shutdown to
    # actually close its listening socket.
    still_listening = True
    for _ in range(10):  # poll for up to ~1s
        if not _helper_is_running():
            still_listening = False
            break
        time.sleep(0.1)

    # Hand the fact forward rather than losing it: if the socket outlived
    # our patience, the next _start_helper() must not read it as somebody
    # else's helper.
    _helper_port_lingering[0] = still_listening
    if still_listening:
        logger.debug(
            "Move_SR_Bridge: Helper socket on port %d still closing",
            _HELPER_PORT,
        )


# --------------------------------------------------------------------------
# Making display text speakable
# --------------------------------------------------------------------------
# Live draws an "this parameter is automated" indicator by prefixing the
# parameter name with U+E044, a Private Use Area codepoint from the Move's
# icon font (Move/display_util.py: AUTOMATION_CHAR, used by
# display.py: parameter_view).  Forwarded as-is a screen reader says
# nothing for it, or "unknown character" -- either way the automation
# state, which is plainly visible on the OLED, is lost entirely.
_AUTOMATION_CHAR = u"\ue044"
_AUTOMATION_SPOKEN = "automated"

# Labels Live abbreviates to fit the 128px display.  Speech has no width
# limit, and a screen reader pronounces the abbreviation as gibberish.
# Only expand things genuinely unreadable when spoken -- conventional
# audio shorthand ("Freq", "LFO", "Env") is left alone because it matches
# what Live's own UI says elsewhere.
_ABBREVIATIONS = (
    ("Autmtn.", "Automation"),
)

# Screens that must not wait behind the debounce.  Live drives its
# shutdown prompt from firmware state we cannot read from here, so this
# one is matched on text; if Live ever rewords it the only consequence is
# that it gets debounced like anything else.
_URGENT_TEXTS = frozenset([
    "Press wheel to shut down",
])


def _is_private_use(ch):
    """True for Basic Multilingual Plane Private Use Area codepoints."""
    return u"\ue000" <= ch <= u"\uf8ff"


def _clean_line(line):
    """Normalise one display line for speech.

    Expands display-width abbreviations and drops icon-font glyphs that
    have no spoken form.  _AUTOMATION_CHAR is deliberately preserved here
    -- it carries real meaning and is turned into a word later, once we
    know whether it sits on a name we may need to match against Live's
    own narration.
    """
    text = str(line)
    for abbrev, expansion in _ABBREVIATIONS:
        if abbrev in text:
            text = text.replace(abbrev, expansion)
    if any(_is_private_use(ch) and ch != _AUTOMATION_CHAR for ch in text):
        text = u"".join(
            ch for ch in text
            if not _is_private_use(ch) or ch == _AUTOMATION_CHAR
        )
    return text.strip()


def _spoken(text):
    """Final pass: turn the automation glyph into a word, then flatten.

    The whitespace collapse is unconditional, and that matters.  Move
    builds its `NotificationView` with `supports_new_line=True`, so
    `NotificationView.render` deliberately does NOT flatten the newline in
    a notification template -- `'Notes\\ndeleted'` arrives as a single
    `lines` entry containing a real newline, which Live's `break_line`
    splits into two drawn rows at draw time.  Collapsing only when the
    automation glyph happened to be present (which is what this used to
    do) let that newline through to the screen reader and the braille
    display on every notification.  The sighted user sees one two-row
    phrase, so "Notes deleted" is also the parity-correct reading.
    """
    if _AUTOMATION_CHAR in text:
        text = text.replace(_AUTOMATION_CHAR, _AUTOMATION_SPOKEN + " ")
    return " ".join(text.split())


# The only multi-line sentence Live authors anywhere in the Move view
# tree, established by reading every Content(...) construction in
# Move/display.py against 12.4.5b11: main_view's shutdown prompt.  Every
# other multi-line content is a distinct name/value pair or a list, and
# wants a comma.
#
# This MUST join to a member of _URGENT_TEXTS -- the shutdown prompt only
# bypasses the debounce because the joined string matches there.  The two
# constants are coupled, and tests/test_format_content.py asserts it.
_CONTINUATION_PAIRS = frozenset([
    ("Press wheel to", "shut down"),
])


def _join_lines(lines):
    """Join display lines, keeping the one wrapped sentence readable.

    Lines are usually distinct fields ("Cutoff", "800 Hz"), where a comma
    is right.  Live also authors exactly one sentence split across two
    lines ("Press wheel to" / "shut down"), where a comma inserts a
    spurious pause mid-sentence.

    This used to be guessed from the next line starting lowercase.  That
    served the one screen above while mis-joining every genuinely distinct
    field that happens to start lowercase -- a lowercase track, device,
    bank or menu-item name read as "1-Audio bass" instead of
    "1-Audio, bass".  Naming the single real case removes the guess.

    If Live ever rewords the prompt the result is a spurious comma, which
    is cosmetic -- the same trade _URGENT_TEXTS already accepts.
    """
    joined = previous = lines[0]
    for line in lines[1:]:
        separator = " " if (previous, line) in _CONTINUATION_PAIRS else ", "
        joined += separator + line
        previous = line
    return joined


# Live marks a menu item that opens a submenu with '>' and a leaf with
# '-' (Move/menu.py: MenuItem.cursor_char defaults to '-', and
# __post_init__ sets '>' whenever the item has sub-items).  That char is
# passed straight to the OLED --
# DisplayElement._do_display -> draw_vertical_list(lines, list_cursor_char,
# list_index) -- so it is genuinely on the glass beside the cursor, and
# announcing it is parity rather than embellishment.
#
# It distinguishes "the wheel opens a list you can browse" from "the wheel
# does it right now", and Settings' `Standalone` (which switches the
# device out of Live's control) is a leaf.  Both plain ASCII, no Private
# Use Area involvement.
_SUBMENU_CURSOR_CHAR = ">"
_SUBMENU_SPOKEN = "submenu"


def _submenu_marker(content):
    """"submenu" when Live drew '>' beside the selected item, else "".

    getattr with a default because only VerticalListContent carries this
    attribute -- Content, HorizontalListContent and NotificationContent do
    not, and this runs on every display update.
    """
    return (
        _SUBMENU_SPOKEN
        if getattr(content, "list_cursor_char", None) == _SUBMENU_CURSOR_CHAR
        else ""
    )


# What _format_content() reports about one display update.
#   text            -- the full announcement, and the change-detection key
#   name            -- name half of a name/value pair, glyph-free, or None;
#                      compared against Live's selected track/scene
#   value           -- value half, spoken alone when `name` is redundant
#   is_notification -- transient overlay rather than a main screen
#   is_automated    -- the name carried Live's automation glyph.  Needed
#                      because the glyph rides on the name and `name` is
#                      the match key, so the caller cannot recover it
#                      from either half once the name has been dropped.
_Announcement = collections.namedtuple(
    "_Announcement", "text name value is_notification is_automated"
)
_Announcement.__new__.__defaults__ = (False,)


# --------------------------------------------------------------------------
# Display content formatting
# --------------------------------------------------------------------------
def _format_content(content, active_parameter=None):
    """Describe one display update for speech.

    Returns an _Announcement, or None when there is nothing to say.

    `active_parameter` is the parameter an encoder is touching, when one
    is (see `_get_active_parameter`).  It is needed because Live's
    parameter overlay does not always write the value to the screen as
    text -- see the master-volume case below.

    `text` is the full announcement and doubles as the change-detection
    key, so e.g. "1-MIDI: No Device" and "2-MIDI: No Device" are never
    treated as the same update even though they sound identical once the
    redundant name is stripped.

    For a name/value pair, `name` and `value` are reported separately so
    the caller can speak the value alone when Live's own narration has
    just said the name -- no substring arithmetic on `text` required.
    """
    lines = getattr(content, "lines", None)
    if not lines:
        return None

    # Two views of the same lines:
    #   aligned_lines keeps one entry per entry of content.lines, so an
    #     index Live hands us still refers to the line Live meant;
    #   text_lines drops the empties, for anything that just reads the
    #     screen top to bottom.
    # Collapsing to text_lines first and then indexing it announced the
    # WRONG list item whenever an earlier line was blank or was a pure
    # icon-font glyph (_clean_line reduces those to "").
    aligned_lines = [_clean_line(line) if line else "" for line in lines]
    text_lines = [line for line in aligned_lines if line]
    if not text_lines:
        return None

    # Live's parameter overlay can name a control without ever writing its
    # value as text.  Touching the master volume encoder renders
    # `Content(lines=['Volume', '', ''], value=<0-1 float>, ...)` --
    # the level exists only as the bar graphic driven by `value`, so a
    # screen reader user heard "Volume" and never learned the level.
    # Recover it from the parameter itself.  Only when the overlay gave us
    # a single line: every other branch of `parameter_view` already puts a
    # value string in `lines`, and appending there would just double it.
    #
    # `aligned_lines` is deliberately left alone -- it exists to keep
    # `list_index` pointing at the line Live meant, and the parameter
    # overlay is never a list content in the first place.
    if active_parameter is not None and len(text_lines) == 1:
        value_text = _parameter_value_text(active_parameter)
        if value_text:
            text_lines = [text_lines[0], value_text]

    # Vertical list menus -- announce selected item
    if "vertical" in _content_types and isinstance(
        content, _content_types["vertical"]
    ):
        list_index = getattr(content, "list_index", None)
        if (
            list_index is not None
            and 0 <= list_index < len(aligned_lines)
            and aligned_lines[list_index]
        ):
            text = _spoken(aligned_lines[list_index])
            # `list_cursor_char` describes the SELECTED row only -- Live
            # sends one char for the whole content -- so it belongs here
            # and nowhere else.
            marker = _submenu_marker(content)
            if marker:
                text += ", " + marker
            return _Announcement(text, None, None, False)
        # No marker on the whole-list fallback: we reach it precisely when
        # we could not identify which row is selected, and the char
        # describes that row alone.
        return _Announcement(_spoken(_join_lines(text_lines)), None, None, False)

    # Horizontal list (name + value)
    if "horizontal" in _content_types and isinstance(
        content, _content_types["horizontal"]
    ):
        if len(text_lines) == 2:
            name, value = text_lines
            # The automation glyph rides on the name, but `name` is also
            # what we match against Live's selected track/scene -- so keep
            # the marker in the spoken text and out of the match key, and
            # report it separately so dropping the name cannot drop it too.
            return _Announcement(
                _spoken(name + ": " + value),
                _spoken(name.replace(_AUTOMATION_CHAR, "")).strip(),
                _spoken(value),
                False,
                _AUTOMATION_CHAR in name,
            )
        return _Announcement(_spoken(_join_lines(text_lines)), None, None, False)

    # Notifications
    if "notification" in _content_types and isinstance(
        content, _content_types["notification"]
    ):
        # This join is a no-op on Move: notifications always arrive as a
        # single `lines` entry, and their multi-line-ness lives INSIDE it
        # as a real newline ('Notes\ndeleted') which Live's break_line
        # splits at draw time.  _spoken() is what actually flattens it.
        # Kept for any producer that does pass several lines.
        return _Announcement(_spoken(" ".join(text_lines)), None, None, True)

    return _Announcement(_spoken(_join_lines(text_lines)), None, None, False)


# Live's own name for the component that tracks which parameter an encoder
# is currently touching (ableton/v3/control_surface/component_map.py, and
# Move/mappings.py wires it in).  `Move/display.py: parameter_view` reads
# exactly this to decide whether to paint the parameter overlay at all, so
# reading it here is the same signal rather than a guess about the text.
_ACTIVE_PARAMETER_COMPONENT = "Active_Parameter"


def _get_active_parameter(control_surface):
    """The parameter an encoder is touching right now, or None.

    `ControlSurfaceMappingMixin.__init__` sets `self.component_map`, and
    Live's `parameter_view` is driven by `state.active_parameter.parameter`
    -- the same component this looks up.  Defensive: runs on every display
    update and must never raise, and the attribute is absent entirely
    outside Live.
    """
    try:
        component_map = getattr(control_surface, "component_map", None)
        if component_map is None:
            return None
        if isinstance(component_map, dict):
            # Read straight through dict, NOT component_map[key]. Live's
            # ComponentMap subclasses dict and its __getitem__ lazily
            # *constructs* an absent component (with is_enabled=False) and
            # caches it -- a side effect on Live's control surface, from a
            # function that runs on every display update. Move's mappings
            # always create Active_Parameter during setup, so in practice
            # this is a plain hit; going through dict makes "in practice"
            # into "by construction". An uncreated entry is still the
            # factory, which has no `parameter`, so it reads as None.
            component = dict.get(component_map, _ACTIVE_PARAMETER_COMPONENT)
        else:
            component = component_map[_ACTIVE_PARAMETER_COMPONENT]
        return getattr(component, "parameter", None)
    except Exception:
        return None


def _parameter_value_text(parameter):
    """Human-readable value of a device parameter, or None.

    Live's own `parameter_view` renders this with
    `parameter_value_string()`, which is not importable from here.  That
    function is, verbatim from Move/display_util.py:

        value_string = str(parameter)
        if ' dB' in value_string:
            return '{} dB'.format(round(float(value_string.replace(' dB', '')), 1))
        return value_string

    so it is `str()` plus one decimal of rounding on dB values.  Mirror it
    rather than using bare `str()`: otherwise the master-volume recovery
    announces more precision than Live ever draws for that parameter
    anywhere, which is a number the user cannot check against the screen.
    """
    try:
        text = str(parameter).strip()
    except Exception:
        return None
    if not text:
        return None
    if " dB" in text:
        try:
            text = "{} dB".format(round(float(text.replace(" dB", "")), 1))
        except (TypeError, ValueError):
            # Not a plain number (Live also renders "-inf dB" and similar).
            # Say whatever str() gave us rather than nothing.
            pass
    return text


# --------------------------------------------------------------------------
# Step-sequencer buttons: reading the lights
# --------------------------------------------------------------------------
# The 16 buttons along the bottom row (Step_Buttons, MIDI notes 16-31) show
# whether each step holds a note, through their LEDs, and nothing else on
# the device reports it -- there is no notification for a single step being
# added or removed, and main_view never mentions step state.  The 32 pads
# (Pads, notes 68-99, a separate 4x8 element) are deliberately out of scope.
#
# Live's own NoteEditorComponent._get_color_for_step() returns the skin name
# that drives the LED, so it is the source of truth.  Anything outside these
# two sets -- StepDisabled, NoClip, the transient StepTied/StepPartiallyTied
# from the hold-to-inspect gesture, Playhead, or a name Ableton adds later --
# means we do not know, and we say nothing.
#
# Two frozensets rather than "off is anything that is not on": with a
# default, a future skin name would be announced as a confident "off".
_STEP_LIGHT_ON = frozenset([
    "NoteEditor.StepFilled",
    # A muted step still holds a note.  Reported as "on" deliberately --
    # StepMuted is a distinct LED, but on/off is the chosen vocabulary.
    "NoteEditor.StepMuted",
])
_STEP_LIGHT_OFF = frozenset([
    "NoteEditor.StepEmpty",
])

_STEP_SEQUENCE_COMPONENT = "Step_Sequence"
_STEP_RELEASE_METHOD = "_on_release_step"
_STEP_HOOK_MARKER = "_move_sr_bridge_step_hooks"
# Step_Buttons is a 4x4 matrix in the script and a row of 16 on the device;
# either way the flat index is what the user's hand is on.  Only a fallback:
# NoteEditorComponent.width is a property and is read live.
_DEFAULT_STEP_WIDTH = 4


def _step_toggle_text(index, is_on):
    """"Step 5 on" / "Step 5 off".

    1-based, and within the current page: the 16 buttons always show one
    page, so no paginator read is needed and none is made.
    """
    return "Step %d %s" % (index + 1, "on" if is_on else "off")


def _step_index(step, note_editor):
    """Flat 0-based index of a step button, or None if it cannot be trusted.

    `StepButtonControl.State` derives `x = coordinate[1]` and
    `y = coordinate[0]`, and Move's own code computes the flat index as
    `step.y * 4 + step.x` -- row-major.  `width` comes from the live
    property (`matrix.width or DEFAULT_WIDTH`) rather than a constant, but
    a bare `note_editor.width` would raise straight into the caller's
    catch-all and kill the feature silently for the session, so it falls
    back instead.

    Returns None rather than a guess whenever anything looks wrong:
    announcing "Step 137 on" is worse than saying nothing.
    """
    x = getattr(step, "x", None)
    y = getattr(step, "y", None)
    if not isinstance(x, int) or not isinstance(y, int):
        return None
    width = getattr(note_editor, "width", None)
    if not isinstance(width, int) or width <= 0:
        width = _DEFAULT_STEP_WIDTH
    index = y * width + x
    if index < 0:
        return None
    count = getattr(note_editor, "step_count", None)
    if isinstance(count, int) and count > 0 and index >= count:
        return None
    return index


def _step_light(note_editor, index):
    """True (lit), False (unlit) or None (unknown) for one step button.

    Reads exactly what Live uses to colour the LED.  Both calls are pure
    reads with no side effects -- `_visible_steps()` builds a fresh dict
    and `filter_notes` filters a list; no Live API call, no mutation --
    so this is cheap enough to call on a button press and must not be
    cached.

    Note the value is only as fresh as `note_editor._clip_notes`, which is
    a cache refreshed asynchronously by the editor's own `notes` listener.
    See _install_step_hooks for why that dictates when this is called.
    """
    try:
        name = note_editor._get_color_for_step(index, note_editor._visible_steps())
    except Exception:
        return None
    if name in _STEP_LIGHT_ON:
        return True
    if name in _STEP_LIGHT_OFF:
        return False
    return None


def _get_note_editor(control_surface):
    """Live's note editor component, or None.

    Same defensive shape as _get_active_parameter, and the same rule about
    `dict.get` over the subscript -- but here it is not merely hygiene.
    `Step_Sequence` genuinely is one of ComponentMap's lazily-constructed
    keys, and `ComponentMap.__getitem__` constructs the component and
    writes it back into the dict.  Subscripting would build the entire step
    sequencer as a side effect of our lookup.

    In practice `Move.setup()` already resolves
    `component_map['Step_Sequence'].note_editor` during construction, well
    before on_identified(), so the instance is there.  If that ever stops
    being true, `dict.get` returns the factory, which has no `note_editor`,
    and the feature degrades to off with no side effect on Live.
    """
    try:
        component_map = getattr(control_surface, "component_map", None)
        if component_map is None:
            return None
        if isinstance(component_map, dict):
            component = dict.get(component_map, _STEP_SEQUENCE_COMPONENT)
        else:
            component = component_map[_STEP_SEQUENCE_COMPONENT]
        if component is None:
            return None
        return getattr(component, "note_editor", None)
    except Exception:
        return None


def _install_step_hooks(note_editor, announce):
    """Announce step toggles by reading the button's light.

    Returns a zero-argument callable that undoes everything installed, or
    None if nothing was installed.

    The tap decides WHEN and WHICH step; the light decides WHAT state to
    report.  Reading the lights alone would mean diffing all 16 on every
    `clip_notes`, which also fires for Live-UI edits, undo and every note
    captured while recording -- far too chatty.  Inferring the state from
    which internal method ran would never consult the light at all.

    The two reads must straddle Live's cache refresh:

        tap release
          |- prologue: remember the step and its light BEFORE the toggle
          |- original _on_release_step(...)   -> clip modified
        ...Live fires the clip's `notes` listener, sync or deferred...
          |- __on_clip_notes_changed refreshes _clip_notes, then notifies
             |- our listener: read the light again and diff

    Consequences of that shape, each load-bearing:

    * The diff is self-validating.  A gesture that toggles nothing (a
      velocity edit, a duration hold, no clip) leaves the light unchanged
      and says nothing -- so none of _on_release_step's short-circuits is
      mirrored, and _add_note_in_step/_delete_notes_in_step need no wrapper.
    * Coalescing is free.  _add_note_in_step fires once per pitch, so a
      chord fires `clip_notes` once per pitch; consuming the record BEFORE
      announcing means the first event wins.
    * It works whether Live's LOM listener is synchronous or deferred.  The
      prologue arms the record before the original runs, so a listener
      firing inside clip.add_new_notes() already sees it; and there is
      deliberately NO `finally` clearing it, so a deferred listener finds
      it too.  Adding one is the obvious tidy-up and it silently disables
      the feature wherever Live defers.
    * Never read the light synchronously after the original: `_clip_notes`
      has not been refreshed yet, so the answer would be the old state --
      confidently backwards.
    """
    if note_editor is None:
        return None

    if getattr(note_editor, _STEP_HOOK_MARKER, None) is not None:
        logger.warning(
            "Move_SR_Bridge: Step hooks already installed on this note "
            "editor, not installing again"
        )
        return None

    original_release = getattr(note_editor, _STEP_RELEASE_METHOD, None)
    add_listener = getattr(note_editor, "add_clip_notes_listener", None)
    remove_listener = getattr(note_editor, "remove_clip_notes_listener", None)
    has_listener = getattr(note_editor, "clip_notes_has_listener", None)
    # Resolve everything before mutating anything.  A partial install is
    # the worst outcome: a wrapper left on the instance with no unwrap
    # callable able to remove it.
    if not callable(original_release) or not callable(add_listener):
        logger.warning(
            "Move_SR_Bridge: Note editor is missing %s or "
            "add_clip_notes_listener, step toggles not announced",
            _STEP_RELEASE_METHOD,
        )
        return None

    pending = [None]

    def _wrapped_on_release_step(step, can_add_or_remove=False):
        try:
            index = _step_index(step, note_editor)
            if index is None:
                pending[0] = None
            else:
                before = _step_light(note_editor, index)
                # An unreadable light gives nothing to compare against, so
                # do not arm -- otherwise the first readable frame would
                # announce a change nobody observed.
                pending[0] = (
                    None if before is None
                    else {"index": index, "before": before}
                )
        except Exception as e:
            _log_failure("Step release wrapper", e)
            pending[0] = None
        # Last statement, and unguarded: nothing of ours can skip Live's
        # own work, its exception propagates untouched, and its return
        # value passes through.
        return original_release(step, can_add_or_remove)

    def _on_clip_notes():
        try:
            record = pending[0]
            if record is None:
                # No armed gesture: recording, undo, or an edit made in
                # Live's own UI.  Not ours to announce.
                return
            pending[0] = None  # consume exactly once, before announcing
            after = _step_light(note_editor, record["index"])
            # `after is not None` first: None != True is True, so without
            # it an unreadable light would be announced as "off".
            if after is not None and after != record["before"]:
                announce(record["index"], after)
        except Exception as e:
            _log_failure("Step notes listener", e)

    def _unwrap():
        # Listener first -- it is the one that can still speak.
        try:
            if not callable(has_listener) or has_listener(_on_clip_notes):
                if callable(remove_listener):
                    remove_listener(_on_clip_notes)
        except Exception as e:
            _log_failure("Step hook teardown", e)
        try:
            if getattr(note_editor, _STEP_RELEASE_METHOD, None) is (
                _wrapped_on_release_step
            ):
                # delattr, never setattr(original): `original_release` is a
                # BOUND method holding a strong reference to note_editor.
                # Writing it into the instance __dict__ is not a restore --
                # it shadows the class method permanently and makes any
                # later class-level patch invisible.  (And never patch the
                # class itself: that would outlive every instance.)
                delattr(note_editor, _STEP_RELEASE_METHOD)
            else:
                logger.warning(
                    "Move_SR_Bridge: %s was replaced by something else, "
                    "leaving it alone",
                    _STEP_RELEASE_METHOD,
                )
        except Exception as e:
            _log_failure("Step hook teardown", e)
        try:
            delattr(note_editor, _STEP_HOOK_MARKER)
        except AttributeError:
            pass

    setattr(note_editor, _STEP_RELEASE_METHOD, _wrapped_on_release_step)
    add_listener(_on_clip_notes)
    setattr(note_editor, _STEP_HOOK_MARKER, _unwrap)
    return _unwrap


def _dialog_is_open():
    """True while Live has a modal dialog open.

    Live's own Move script drives its "needs your attention" screen from
    Application.open_dialog_count (Move/dialog.py), so read the same
    signal rather than pattern-matching the English message off the OLED.
    Defensive: runs on every display update and must never raise.
    """
    if _Live is None:
        return False
    try:
        return _Live.Application.get_application().open_dialog_count > 0
    except Exception:
        return False


def _get_dialog_message():
    """The text of Live's currently open dialog, or None.

    `Application.current_dialog_message` is "Text of the last dialog that
    appeared; Empty if all dialogs just disappeared".  Far better than the
    Move's own screen, which says only the generic "Live is showing a
    dialog that needs your attention." -- this gives the user the actual
    question they are being asked.

    Read defensively and treated as optional: if a Live version does not
    expose it, the caller falls back to the OLED text.

    Logs why it came back empty.  "Live has no such property", "Live
    reported an empty string" and "reading it raised" are three different
    situations that all fall back to the OLED text, and telling them apart
    from the log is otherwise impossible.  Cheap: this runs once per
    dialog, not per display update.
    """
    if _Live is None:
        return None
    try:
        app = _Live.Application.get_application()
    except Exception as e:
        logger.debug("Move_SR_Bridge: no Application object (%s)", e)
        return None
    # getattr with a sentinel inside the try, never hasattr(): hasattr
    # swallows only AttributeError, so a property that raises anything else
    # escapes it -- and this function's whole contract is that it cannot
    # raise, because it runs while a modal dialog has Live's UI blocked.
    _missing = object()
    try:
        message = getattr(app, "current_dialog_message", _missing)
    except Exception as e:
        logger.debug(
            "Move_SR_Bridge: current_dialog_message raised (%s)", e
        )
        return None
    if message is _missing:
        logger.debug(
            "Move_SR_Bridge: this Live has no Application."
            "current_dialog_message -- using the Move's own screen text"
        )
        return None
    try:
        message = str(message).strip()
    except Exception as e:
        logger.debug(
            "Move_SR_Bridge: current_dialog_message not stringable (%s)", e
        )
        return None
    if not message:
        # Live populates this for its own message boxes (the ones
        # press_current_dialog_button drives).  A native macOS sheet -- the
        # "Save changes before closing?" panel, say -- may leave it empty,
        # in which case the Move's generic screen really is all there is.
        logger.debug(
            "Move_SR_Bridge: current_dialog_message is empty -- Live did "
            "not report text for this dialog"
        )
        return None
    return message


def _is_urgent(announcement, dialog_open=None):
    """Should this bypass the debounce and be spoken immediately?

    A modal dialog blocks Live entirely, and the shutdown prompt is
    waiting on a button press -- neither should sit behind a delay
    intended to smooth out encoder chatter.

    `dialog_open` lets a caller that has already asked pass the answer in.
    This runs on Live's display callback, which fires several times a
    second, and the dialog branch above goes to some length to keep Live
    API reads off that path -- re-reading the same property here would
    have quietly put one back.
    """
    if announcement.text in _URGENT_TEXTS:
        return True
    if dialog_open is None:
        dialog_open = _dialog_is_open()
    return dialog_open


def _get_live_selected_names(control_surface):
    """Names Live's own UI focus is currently on (selected track/scene).

    Used to avoid repeating a name Live's own native narration is
    expected to have just announced.  Defensive: must never raise, since
    it runs on every display update.
    """
    names = set()
    try:
        track = control_surface.song.view.selected_track
        if track is not None and getattr(track, "name", None):
            names.add(track.name)
    except Exception:
        pass
    try:
        scene = control_surface.song.view.selected_scene
        if scene is not None and getattr(scene, "name", None):
            names.add(scene.name)
    except Exception:
        pass
    return names


# --------------------------------------------------------------------------
# Display hook installation
# --------------------------------------------------------------------------
def _install_display_hook(control_surface):
    """Monkey-patch Display.display() to intercept content for screen reader.

    Returns a zero-argument callable that cancels any pending debounced
    announcement, or None if the hook could not be installed.  The caller
    is expected to keep the callable and invoke it during disconnect().
    """
    from . import sr_bridge

    display = control_surface.display
    if display is None:
        logger.warning(
            "Move_SR_Bridge: No display object found, cannot install hook"
        )
        return None

    original_display_method = getattr(display, "display", None)
    if not callable(original_display_method):
        logger.warning(
            "Move_SR_Bridge: display.display is not callable, cannot install hook"
        )
        return None

    last_announced = [None]   # last text actually spoken, of any kind
    last_main = [None]        # last main screen -- overlays excluded (see below)
    # {"screens": set, "spoken": set} for the dialog currently open, or
    # None when none is.  See the dialog branch below.
    dialog_screens = [None]
    try:
        debounce_enabled = _cfg.getboolean("debounce", "enabled")
    except ValueError:
        logger.warning(
            "Move_SR_Bridge: Invalid 'enabled' value in config.ini, "
            "using default (true)"
        )
        debounce_enabled = True
    try:
        debounce_delay = _cfg.getint("debounce", "delay_ms") / 1000.0
    except ValueError:
        logger.warning(
            "Move_SR_Bridge: Invalid 'delay_ms' value in config.ini, "
            "using default (300)"
        )
        debounce_delay = 0.3
    # fallback= is load-bearing, and is a rule for every future key here.
    # config.py only writes _DEFAULT_CONFIG when the file does not exist, so
    # everyone upgrading keeps a config.ini with no [speech] section.
    # _DEFAULTS/read_dict covers that in practice, but NoSectionError is a
    # configparser.Error, NOT a ValueError -- a bare read would escape this
    # handler, escape _install_display_hook, be caught by _try_install_hook
    # and cost the user the display hook entirely.
    try:
        step_toggles_enabled = _cfg.getboolean(
            "speech", "step_toggles", fallback=True
        )
    except ValueError:
        logger.warning(
            "Move_SR_Bridge: Invalid 'step_toggles' value in config.ini, "
            "using default (true)"
        )
        step_toggles_enabled = True
    _step_unwrap = [None]
    _debounce_timer = [None]
    _pending_text = [None]
    # Bumped every time an announcement is queued or dropped. A timer only
    # speaks if the mailbox still belongs to the generation it was started
    # for -- see _do_announce().
    _debounce_gen = [0]
    _debounce_lock = threading.Lock()

    def _do_announce(generation):
        """Called by a debounce timer when it fires.

        `generation` identifies the queued announcement this timer was
        started for.  cancel() cannot stop a timer that has already begun
        running, so without this check a timer firing at the same moment a
        newer update is queued would take that newer text out of the
        mailbox and speak it immediately -- collapsing the debounce window
        the newer timer exists to enforce, and leaving that timer with
        nothing to say when it fires.
        """
        try:
            with _debounce_lock:
                if generation != _debounce_gen[0]:
                    return
                text = _pending_text[0]
                _pending_text[0] = None
            if text is not None:
                sr_bridge.speak(text)
                sr_bridge.braille(text)
        except Exception as e:
            # Runs on the timer thread. An exception escaping here kills
            # that thread silently: inside Live's interpreter stderr goes
            # nowhere, so the failure would never reach the log at all.
            _log_failure("Announcement", e)

    def _cancel_pending(wait=False):
        """Drop any announcement still waiting on the debounce timer.

        Bumping the generation is the part that always matters: it
        invalidates a timer that has already started running and is
        therefore past cancel()'s reach, so such a timer finds the
        mailbox is no longer its own and says nothing.

        `wait` additionally *joins* that timer, and is for teardown only.
        Waiting turns "stale text lands after the farewell" into "stale
        text lands before the farewell", and lets the timer stop holding
        this closure -- and the control surface with it -- alive past
        disconnect().

        It is deliberately off by default, because the redraw path calls
        this from Live's own display callback, ahead of Live's rendering
        (see _intercepted_display).  A join there can stall the OLED for
        up to a second while a timer finishes a socket write -- worst
        during a modal dialog, which is also the path that calls this per
        distinct screen.  On that path the generation bump alone is
        already enough to keep the stale timer quiet.
        """
        with _debounce_lock:
            _debounce_gen[0] += 1
            timer = _debounce_timer[0]
            _debounce_timer[0] = None
            _pending_text[0] = None
            if timer is not None:
                timer.cancel()
        # Joined outside the lock -- _do_announce() takes _debounce_lock
        # itself, so joining while holding it would deadlock.  A timer
        # cancelled before firing returns from join() immediately.
        if wait and timer is not None:
            timer.join(timeout=1.0)

    def _speak_now(text):
        """Say it immediately, dropping anything queued behind it."""
        _cancel_pending()
        sr_bridge.speak(text)
        sr_bridge.braille(text)

    def _trace(decision, text):
        """Record what the hook did with a screen, including nothing.

        Only spoken text used to reach the log, so every suppression path
        was invisible -- and suppression is most of what this function
        does.  "Move_SR_Bridge did not react to that screen" and
        "Move_SR_Bridge never saw that screen" are completely different
        bugs and looked identical from the log.
        """
        logger.debug("Move_SR_Bridge: screen [%s] %s", decision, text)

    def _announce_step(index, is_on):
        """Speak one step-button toggle, preempting anything queued.

        Deliberately not _trace(): that stream is documented as every
        display update the hook saw, and a step toggle is not one -- it
        gets its own line so the two are never confused in the log.

        Deliberately does not touch last_announced[0] either: a step
        toggle is not a screen, and feeding it into screen change
        detection could suppress a genuine later screen.

        _speak_now cancels the pending announcement, which is the point.
        Pressing a step button already pushes a "Velocity" parameter
        overlay through the display hook, so a quick tap would otherwise
        say "Step 5 on" and then "Velocity: 100" a moment later.  Its
        _cancel_pending() does not join, which matters here: this runs on
        Live's MIDI callback thread.
        """
        try:
            text = _step_toggle_text(index, is_on)
            logger.debug("Move_SR_Bridge: step %s", text)
            _speak_now(text)
        except Exception as e:
            _log_failure("Step toggle announcement", e)

    def _consider_announcing(content):
        active_parameter = _get_active_parameter(control_surface)
        announcement = _format_content(content, active_parameter)
        if announcement is None or not announcement.text:
            _trace("empty", getattr(content, "lines", None))
            return

        # --- modal dialog ------------------------------------------------
        # While Live has a dialog open it keeps re-rendering (~5 screens a
        # second), and the Move's own `any_dialog_open` is a cached flag
        # updated by a listener on `open_dialog_count`, so it briefly lags
        # behind.  Live's `main_view` therefore flaps between "Live is
        # showing a dialog..." and the view underneath -- observed in the
        # log as message, "No Device", message again, all while the dialog
        # was still up.
        #
        # So announce each DISTINCT screen once per episode.  Not "the first
        # screen only": the flap can present the stale main view first, and
        # that would spend the episode's one announcement on the wrong
        # screen and never say there is a dialog at all.  Losing the dialog
        # message is far worse than an extra "No Device" ahead of it.
        dialog_open = _dialog_is_open()
        if dialog_open:
            state = dialog_screens[0]
            if state is None:
                # "screens" dedupes what Live rendered, "spoken" dedupes
                # what we said.  Both are needed: several different screens
                # can resolve to the same dialog text, and announcing that
                # text once per screen would be the very repetition this
                # branch exists to stop.
                state = {"screens": set(), "spoken": set()}
                dialog_screens[0] = state

            if announcement.text in state["screens"]:
                # Cheap exit for the flood -- and, importantly, this is what
                # keeps _get_dialog_message() off the redraw path. Resolving
                # it per redraw meant a Live API read ~5x a second for the
                # whole time a dialog was open, on Live's own callback
                # thread. Per distinct screen it is one or two reads total.
                _trace("dialog-repeat", announcement.text)
                return
            state["screens"].add(announcement.text)

            # Prefer the dialog's real text over the Move's generic screen:
            # "Save changes to Untitled before closing?" is the question the
            # user has to answer; "Live is showing a dialog that needs your
            # attention." is not.  Live leaves this empty for some dialogs
            # (native OS panels), hence the fallback.
            dialog_text = _get_dialog_message() or announcement.text
            if dialog_text in state["spoken"]:
                _trace("dialog-repeat", dialog_text)
                return
            state["spoken"].add(dialog_text)

            last_announced[0] = dialog_text
            _trace("dialog", dialog_text)
            # Not speak(): the helper drops this while Live is frontmost,
            # because VoiceOver announces the dialog itself.
            _cancel_pending()
            sr_bridge.dialog(dialog_text)
            return
        if dialog_screens[0] is not None:
            _trace("dialog-closed", announcement.text)
        dialog_screens[0] = None

        # --- overlays ----------------------------------------------------
        # Live paints some screens *over* the main view and then takes them
        # away again, leaving the main view unchanged underneath.  Those must
        # not become `last_main`, or the screen underneath gets announced a
        # second time the moment the overlay clears -- which is what made
        # touching an encoder say "Volume" and then "No Device" again.
        #
        # This is Live's own taxonomy, not ours: `Move/display.py`
        # `in_critical_display_state()` is
        #     active_parameter.parameter is not None
        #     or firmware.shut_down_state != none
        #     or dialog.any_dialog_open
        # The dialog arm is handled above; the other two are here.  (The
        # shutdown prompt is matched on text because Live drives it from
        # firmware state this process cannot reach.)
        is_overlay = (
            active_parameter is not None
            or announcement.text in _URGENT_TEXTS
        )

        if announcement.is_notification or is_overlay:
            changed = announcement.text != last_announced[0]
        else:
            # Compare a main screen against the last *main* screen, not
            # against the last thing spoken.  A notification temporarily
            # replaces the main view, and when it clears the unchanged
            # screen underneath would otherwise be announced all over
            # again -- roughly doubling speech, since Live raises
            # notifications constantly.
            changed = announcement.text != last_main[0]
            last_main[0] = announcement.text

        if not changed:
            _trace(
                "unchanged/overlay" if is_overlay else "unchanged",
                announcement.text,
            )
            return

        _trace(
            "overlay" if is_overlay
            else ("notification" if announcement.is_notification else "main"),
            announcement.text,
        )
        last_announced[0] = announcement.text
        spoken_text = announcement.text
        if announcement.name:
            live_selected_names = _get_live_selected_names(control_surface)
            if announcement.name in live_selected_names:
                # Live is expected to have just narrated the name itself,
                # so say only the value -- but the automation marker rides
                # on the name, and dropping it would undo the whole point
                # of _AUTOMATION_CHAR handling: an automated parameter on
                # the selected track would read as a bare "0 dB", with no
                # way for the user to tell it is automated.
                spoken_text = announcement.value
                if announcement.is_automated:
                    spoken_text = _AUTOMATION_SPOKEN + ", " + spoken_text

        # Reaching here means the dialog branch above did not return, so
        # `dialog_open` is False -- pass it rather than asking Live again.
        if _is_urgent(announcement, dialog_open):
            _speak_now(spoken_text)
        elif debounce_enabled and debounce_delay > 0:
            with _debounce_lock:
                if _debounce_timer[0] is not None:
                    _debounce_timer[0].cancel()
                _debounce_gen[0] += 1
                _pending_text[0] = spoken_text
                t = threading.Timer(
                    debounce_delay,
                    _do_announce,
                    args=(_debounce_gen[0],),
                )
                t.daemon = True
                t.start()
                _debounce_timer[0] = t
        else:
            sr_bridge.speak(spoken_text)
            sr_bridge.braille(spoken_text)

    def _intercepted_display(content):
        try:
            _consider_announcing(content)
        except Exception as e:
            _log_failure("Display hook", e)
        # Outside the try, and never behind an early return: Live's own
        # rendering must happen whatever we decide about speech.
        original_display_method(content)

    def _teardown():
        """Undo everything this function installed.

        Restoring `display.display` is not cosmetic.  While the patch is
        in place, any frame Live renders after disconnect() re-enters
        _consider_announcing, which can start a *fresh* timer and speak
        after "Move disconnected" -- exactly what cancelling the pending
        announcement is meant to prevent.  The patch also keeps this
        closure, and through it the control surface, reachable for as
        long as Live's display object lives.

        Restore before cancelling, so no frame arriving mid-teardown can
        queue anything behind us.

        The step hooks come off first: their `clip_notes` listener is the
        one remaining thing that could still speak, and it is guarded so a
        failure there cannot skip the display restore below, which is the
        part that absolutely must happen.
        """
        if _step_unwrap[0] is not None:
            try:
                _step_unwrap[0]()
            except Exception as e:
                _log_failure("Step hook teardown", e)
            _step_unwrap[0] = None

        if display.display is _intercepted_display:
            display.display = original_display_method
        else:
            # Somebody else patched over us; unpicking their patch would
            # be worse than leaving it, but the user should know why the
            # bridge may keep talking.
            logger.warning(
                "Move_SR_Bridge: Display method was replaced by something "
                "else, leaving it alone"
            )
        _cancel_pending(wait=True)

    # The display hook lands first and unconditionally: nothing below may
    # cost the user the thing that already works.
    display.display = _intercepted_display

    # Gated at install time, not announce time.  A disabled feature must
    # wrap nothing at all -- wrapping and then checking would still hold
    # this closure, and through it the control surface, alive all session.
    step_toggles_status = "disabled by config"
    if step_toggles_enabled:
        try:
            _step_unwrap[0] = _install_step_hooks(
                _get_note_editor(control_surface), _announce_step
            )
            step_toggles_status = (
                "on" if _step_unwrap[0] is not None else "no note editor"
            )
        except Exception as e:
            _log_failure("Step hook install", e)
            step_toggles_status = "failed"

    # Report what actually happened, not what was configured: this line is
    # the project's primary support artefact and must not describe work it
    # skipped.
    logger.info(
        "Move_SR_Bridge: Display hook installed (debounce=%s, delay=%dms, "
        "step_toggles=%s)",
        debounce_enabled,
        int(debounce_delay * 1000),
        step_toggles_status,
    )

    sr_bridge.speak("Move connected")
    sr_bridge.braille("Move connected")
    return _teardown


# --------------------------------------------------------------------------
# Move subclass with screen reader hooks
# --------------------------------------------------------------------------
class Move(_OriginalMove):
    _sr_hook_installed = False
    # Set by _try_install_hook() to the teardown callable returned by
    # _install_display_hook(); called during disconnect() to restore
    # Live's own display method and stop a pending debounced announcement
    # from firing after teardown.
    _sr_teardown_hook = None
    # True once this instance owns the _start_helper() registration made
    # on its behalf by create_instance().  Cleared by the first
    # disconnect() so a second one cannot release it again: the refcount
    # tracks instance lifetime, not the number of disconnect() calls, and
    # over-decrementing would tear down a helper another control surface
    # slot is still using.
    _sr_registered = False

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        # Reaching here means construction succeeded, so this instance is
        # the owner of the registration create_instance() already made.
        self._sr_registered = True

    # Live-side focus/selection listeners: (owner attribute on song(), or
    # None for song() itself; LOM property; handler method name).  These
    # log Live's own focus/selection state at DEBUG, independent of the
    # display hook, to help diagnose double-speech against Live's native
    # VoiceOver narration (which follows Live's UI focus, not the Move's
    # OLED).
    _LIVE_LISTENERS = (
        ("view", "selected_track", "_on_selected_track_changed"),
        ("view", "selected_scene", "_on_selected_scene_changed"),
        (None, "tracks", "_on_track_list_changed"),
        (None, "scenes", "_on_scene_list_changed"),
    )

    def _on_selected_track_changed(self):
        track = self.song.view.selected_track
        name = track.name if track else "(none)"
        logger.debug("Move_SR_Bridge: Live selected track changed -> %s", name)

    def _on_selected_scene_changed(self):
        scene = self.song.view.selected_scene
        name = scene.name if scene else "(none)"
        logger.debug("Move_SR_Bridge: Live selected scene changed -> %s", name)

    def _on_track_list_changed(self):
        logger.debug(
            "Move_SR_Bridge: Live track list changed (now %d tracks)",
            len(self.song.tracks),
        )

    def _on_scene_list_changed(self):
        logger.debug(
            "Move_SR_Bridge: Live scene list changed (now %d scenes)",
            len(self.song.scenes),
        )

    def _install_live_listeners(self):
        # Everything in here must be defensive: an uncaught exception
        # would propagate out of on_identified() and can leave Live
        # thinking hardware identification didn't complete cleanly,
        # breaking normal display updates even though our own hook
        # already installed successfully.
        try:
            song = self.song
            for owner_attr, prop, handler_name in self._LIVE_LISTENERS:
                try:
                    owner = getattr(song, owner_attr) if owner_attr else song
                    handler = getattr(self, handler_name)
                    if not getattr(owner, "%s_has_listener" % prop)(handler):
                        getattr(owner, "add_%s_listener" % prop)(handler)
                except Exception as e:
                    logger.error(
                        "Move_SR_Bridge: Failed to install %s listener: %s", prop, e
                    )
        except Exception as e:
            logger.error("Move_SR_Bridge: Failed to access song() for listeners: %s", e)

    def _remove_live_listeners(self):
        # Same defensiveness as _install_live_listeners -- must never
        # raise, since this runs first thing in disconnect() and would
        # otherwise abort cleanup (super().disconnect(), _stop_helper()).
        try:
            song = self.song
            for owner_attr, prop, handler_name in self._LIVE_LISTENERS:
                try:
                    owner = getattr(song, owner_attr) if owner_attr else song
                    handler = getattr(self, handler_name)
                    if getattr(owner, "%s_has_listener" % prop)(handler):
                        getattr(owner, "remove_%s_listener" % prop)(handler)
                except Exception:
                    pass
        except Exception:
            pass

    def _try_install_hook(self):
        if self._sr_hook_installed:
            return
        if self.display is not None:
            try:
                teardown = _install_display_hook(self)
                if teardown is not None:
                    self._sr_teardown_hook = teardown
                    self._sr_hook_installed = True
            except Exception as e:
                logger.error(
                    "Move_SR_Bridge: Failed to install display hook: %s", e
                )

    def on_identified(self, response_bytes):
        super().on_identified(response_bytes)
        # Live fires this more than once per connection, so only claim to
        # be installing the hook when we actually are -- this log is the
        # primary support artefact and should not describe work it skips.
        if self._sr_hook_installed:
            logger.debug(
                "Move_SR_Bridge: Move re-identified, display hook already "
                "installed"
            )
        else:
            logger.info(
                "Move_SR_Bridge: Move identified, installing display hook..."
            )
        self._try_install_hook()
        self._install_live_listeners()

    def disconnect(self):
        # Live may call disconnect() more than once for the same instance.
        # Everything we own must happen exactly once -- announcing the
        # farewell twice is merely annoying, but releasing the helper
        # registration twice would kill a helper another control surface
        # slot is still using.
        first_disconnect = self._sr_registered
        self._sr_registered = False

        if first_disconnect:
            self._remove_live_listeners()
            # Unhook Live's display method and drop any queued announcement
            # before we speak the farewell: a stale display update must not
            # land after "Move disconnected", and while the hook is still
            # in place a later frame could queue a fresh one behind us.
            if self._sr_teardown_hook is not None:
                try:
                    self._sr_teardown_hook()
                except Exception as e:
                    logger.warning(
                        "Move_SR_Bridge: Error tearing down display hook: %s", e
                    )
                self._sr_teardown_hook = None
            if self._sr_hook_installed:
                try:
                    from . import sr_bridge

                    sr_bridge.speak("Move disconnected")
                    sr_bridge.braille("Move disconnected")
                except Exception:
                    pass
            # Cleared last, so the farewell above still knows the hook ran,
            # and so a reconnected instance installs a fresh hook instead of
            # believing one it no longer owns is still in place.
            self._sr_hook_installed = False
            logger.info("Move_SR_Bridge: Script unloading")

        # Live's own teardown must not be able to strand our registration.
        # If it raises and this is left unguarded, _stop_helper() below never
        # runs, _active_instances stays incremented forever, and no later
        # instance can ever shut the helper down -- so it outlives Live.
        # The exception would also escape into a lifecycle hook Live is
        # actively calling, which is what _remove_live_listeners() above
        # already goes out of its way to avoid.
        try:
            super().disconnect()
        except Exception as e:
            logger.warning(
                "Move_SR_Bridge: Error in Live's disconnect(): %s", e
            )
        finally:
            if first_disconnect:
                _stop_helper()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def create_instance(c_instance):
    logger.info("Move_SR_Bridge: Creating control surface instance")
    # Registered before the surface exists so the helper is already up by
    # the time the display hook wants it.
    _start_helper()
    try:
        return Move(specification=_OriginalSpecification, c_instance=c_instance)
    except Exception:
        # No instance will exist to release the registration above, and an
        # orphaned one keeps the refcount permanently non-zero -- meaning
        # no later instance could ever shut the helper down either.
        logger.error(
            "Move_SR_Bridge: Control surface construction failed, "
            "releasing helper registration"
        )
        _stop_helper()
        raise


logger.info("Move_SR_Bridge: Script loaded successfully")
