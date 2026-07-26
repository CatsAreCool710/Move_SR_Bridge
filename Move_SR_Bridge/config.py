# config.py - Configuration loader for Move-SR-Bridge
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
Configuration loader for Move-SR-Bridge.

Reads settings from ~/.move_sr_bridge/config.ini.  If the file does not
exist, it is created with documented defaults on first load.  This
module is also the single source of truth for the per-user state
directory (STATE_DIR / CONFIG_FILE / LOG_PATH) shared by the remote
script and sr_helper.

Sections:
    [debounce]  -- Display-update debounce / flood control
        enabled   = true|false   (default: true)
        delay_ms  = <int>        (default: 300)
    [logging]   -- Logging verbosity for Move_SR_Bridge.log
        level     = DEBUG|INFO|WARNING|ERROR   (default: INFO)
"""

import configparser
import logging
import os

logger = logging.getLogger(__name__)

# Per-user state directory.  This is the single source of truth for where
# Move-SR-Bridge keeps everything it writes at runtime -- both processes
# (the remote script inside Live and sr_helper) import these constants
# rather than deriving their own paths.  It lives under the user's home
# so it is always writable, unlike the install directory (Live's .app
# bundle on macOS, C:\ProgramData on Windows).
STATE_DIR = os.path.join(os.path.expanduser("~"), ".move_sr_bridge")
CONFIG_FILE = os.path.join(STATE_DIR, "config.ini")
LOG_PATH = os.path.join(STATE_DIR, "Move_SR_Bridge.log")

_DEFAULT_CONFIG = """\
[debounce]
# Enable debounce for display updates.  When enabled, speech is delayed
# until no display updates occur for 'delay_ms' milliseconds.
# This prevents rapid-fire speech during encoder turns.
enabled = true

# Milliseconds to wait after the last display update before speaking.
# Lower values feel more responsive; higher values reduce chatter.
# Set to 0 to effectively disable debounce even if enabled = true.
delay_ms = 300

[logging]
# Logging verbosity written to Move_SR_Bridge.log.  Diagnostic-only
# messages (every text sent to be spoken, and Live-side track/scene
# selection changes) are logged at DEBUG and hidden by default.  Set
# to DEBUG when diagnosing double-speech or other issues.
# Valid values: DEBUG, INFO, WARNING, ERROR
level = INFO
"""

_DEFAULTS = {
    "debounce": {
        "enabled": "true",
        "delay_ms": "300",
    },
    "logging": {
        "level": "INFO",
    },
}


def ensure_state_dir():
    """Create the per-user state directory.  Returns True on success.

    Callable before logging is configured -- the logging bootstrap in
    __init__.py and sr_helper.py needs the directory to exist before it
    can open LOG_PATH.
    """
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        return True
    except OSError:
        return False


def load_config():
    """Load configuration from ~/.move_sr_bridge/config.ini.

    Creates the config file with documented defaults if it does not exist.
    This is the only place the default config is written -- installers
    must not write their own copy, or the two will drift apart.

    Returns a configparser.ConfigParser with values already loaded.
    """
    if not os.path.isfile(CONFIG_FILE):
        try:
            ensure_state_dir()
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                f.write(_DEFAULT_CONFIG)
            logger.info(
                "Move_SR_Bridge: Created default config at %s", CONFIG_FILE
            )
        except OSError as e:
            logger.warning(
                "Move_SR_Bridge: Could not create config file %s: %s",
                CONFIG_FILE,
                e,
            )

    config = configparser.ConfigParser()
    config.read_dict(_DEFAULTS)
    if os.path.isfile(CONFIG_FILE):
        try:
            config.read(CONFIG_FILE, encoding="utf-8")
        except configparser.Error as e:
            logger.warning(
                "Move_SR_Bridge: Malformed config file %s, using defaults: %s",
                CONFIG_FILE,
                e,
            )
            config = configparser.ConfigParser()
            config.read_dict(_DEFAULTS)
    return config
