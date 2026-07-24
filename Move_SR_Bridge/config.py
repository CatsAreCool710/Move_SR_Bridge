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
exist, it is created with documented defaults on first load.

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

_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".move_sr_bridge")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "config.ini")

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


def load_config():
    """Load configuration from ~/.move_sr_bridge/config.ini.

    Creates the config file with documented defaults if it does not exist.
    Returns a configparser.ConfigParser with values already loaded.
    """
    if not os.path.isfile(_CONFIG_FILE):
        try:
            os.makedirs(_CONFIG_DIR, exist_ok=True)
            with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
                f.write(_DEFAULT_CONFIG)
            logger.info(
                "Move_SR_Bridge: Created default config at %s", _CONFIG_FILE
            )
        except OSError as e:
            logger.warning(
                "Move_SR_Bridge: Could not create config file %s: %s",
                _CONFIG_FILE,
                e,
            )

    config = configparser.ConfigParser()
    config.read_dict(_DEFAULTS)
    if os.path.isfile(_CONFIG_FILE):
        try:
            config.read(_CONFIG_FILE, encoding="utf-8")
        except configparser.Error as e:
            logger.warning(
                "Move_SR_Bridge: Malformed config file %s, using defaults: %s",
                _CONFIG_FILE,
                e,
            )
            config = configparser.ConfigParser()
            config.read_dict(_DEFAULTS)
    return config
