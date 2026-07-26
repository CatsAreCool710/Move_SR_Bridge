# smoke_helper.py - End-to-end check that a frozen helper reads config.ini
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
Run a built sr_helper binary and assert it honours ~/.move_sr_bridge/config.ini.

    python scripts/smoke_helper.py Move_SR_Bridge/sr_helper_mac

The unit suite cannot catch this class of bug: it tests the *source*, and
the defect lives in what PyInstaller collects.  `sr_helper.py` imports
config.py at runtime from its install directory -- deliberately, so both
processes share one config module -- which makes that import invisible to
PyInstaller's static analysis.  configparser was therefore never bundled,
`import config` raised ImportError, and the helper silently fell back to
built-in defaults.  Speech still worked, so nothing looked broken; the
only symptom was `level = DEBUG` doing nothing and every `Speaking:` line
missing from the log, i.e. the project's documented diagnostic workflow
quietly not working in any release build.

This runs the real binary with a real config and fails if the config did
not take effect.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

HOST = "127.0.0.1"
PORT = 8765

CONFIG = """\
[debounce]
enabled = true
delay_ms = 300

[logging]
level = DEBUG
"""


def fail(message, log_text=""):
    print("FAIL: %s" % message)
    if log_text:
        print("--- helper log ---")
        print(log_text)
    sys.exit(1)


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    helper = os.path.abspath(sys.argv[1])
    if not os.path.exists(helper):
        fail("%s does not exist -- build it first" % helper)

    # A throwaway HOME so the check never reads or writes the real one.
    home = tempfile.mkdtemp(prefix="msb-smoke-")
    state_dir = os.path.join(home, ".move_sr_bridge")
    os.makedirs(state_dir)
    with open(os.path.join(state_dir, "config.ini"), "w") as f:
        f.write(CONFIG)
    log_path = os.path.join(state_dir, "Move_SR_Bridge.log")

    env = dict(os.environ)
    env["HOME"] = home
    env["USERPROFILE"] = home        # expanduser("~") on Windows
    env["HOMEDRIVE"] = ""
    env["HOMEPATH"] = ""

    print("Helper: %s" % helper)
    print("HOME:   %s" % home)

    # Refuse to run against a port somebody else owns.  Without this check
    # a maintainer with their own helper up gets the worst of both worlds:
    # the binary under test fails to bind and exits, this script connects to
    # *their* helper, sends it `quit`, kills it, and then reports a
    # packaging failure that never happened.
    try:
        socket.create_connection((HOST, PORT), timeout=0.5).close()
    except OSError:
        pass
    else:
        fail(
            "something is already listening on port %d -- stop it first, or "
            "this check would test that process instead of %s"
            % (PORT, os.path.basename(helper))
        )

    try:
        proc = subprocess.Popen([helper], cwd=os.path.dirname(helper), env=env)
    except OSError as e:
        # Most likely someone pointed this at sr_helper.py rather than at a
        # built binary.  Say so, instead of a traceback.
        fail(
            "could not execute %s (%s) -- this check runs a BUILT helper "
            "(sr_helper.exe / sr_helper_mac), not the .py source"
            % (helper, e)
        )

    listening = False
    try:
        # Wait for it to start listening.
        for _ in range(50):
            time.sleep(0.2)
            if proc.poll() is not None:
                break
            try:
                s = socket.create_connection((HOST, PORT), timeout=0.5)
            except OSError:
                continue
            listening = True
            break

        if listening:
            s.sendall(
                (json.dumps({"cmd": "speak", "text": "smoke test"}) + "\n")
                .encode()
            )
            time.sleep(1.0)
            s.sendall((json.dumps({"cmd": "quit"}) + "\n").encode())
            s.close()

            for _ in range(25):
                if proc.poll() is not None:
                    break
                time.sleep(0.2)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    log_text = _read(log_path)
    if not log_text:
        fail("helper wrote no log at %s" % log_path)

    # Config assertions first, and deliberately BEFORE the "did it listen"
    # check.  Reading the config happens at import time, well before the
    # backend loads or the socket binds, so it is still testable when the
    # helper died later -- and if it is broken, that is the finding worth
    # reporting.  Diagnosing "never listened" first would bury it.

    # 1. The config was actually read.  The helper reports this itself.
    if "(config: ok)" not in log_text:
        fail(
            "the frozen helper could not use config.py, so config.ini was "
            "ignored -- check PyInstaller collected everything config.py "
            "imports (--hidden-import)",
            log_text,
        )

    # 2. level = DEBUG took effect.
    if "Log level: DEBUG" not in log_text:
        fail("config.ini set level = DEBUG but the helper did not apply it",
             log_text)

    if not listening:
        fail(
            "config.ini was honoured, but the helper never listened on port "
            "%d -- the screen reader backend or the socket bind failed, not "
            "the packaging" % PORT,
            log_text,
        )

    # 3. And the DEBUG trace really reaches the log.
    if "Speaking: smoke test" not in log_text:
        fail(
            "no 'Speaking:' line -- the DEBUG trace that shows speech "
            "working never reached the log",
            log_text,
        )

    # 4. It really is a frozen build.  Without this the whole check passes
    #    identically against `python sr_helper.py`, which is precisely the
    #    thing it cannot test -- every assertion above is about what
    #    PyInstaller did or did not collect.
    if "[frozen]" not in log_text:
        fail(
            "the helper did not report [frozen] -- this check only means "
            "anything against a PyInstaller build, and every assertion "
            "above passes trivially when run against the source",
            log_text,
        )

    # 5. version.py survived freezing.  sr_helper.py imports it at runtime
    #    from the install directory, which PyInstaller cannot see -- the
    #    same blind spot that lost configparser.  A build that reports
    #    "version unknown" would otherwise sail through, and the version in
    #    the log is what every bug report is triaged against.
    expected = _expected_version()
    if expected and ("(version %s)" % expected) not in log_text:
        fail(
            "helper did not report version %s -- version.py did not survive "
            "freezing, so the log cannot identify which build produced it"
            % expected,
            log_text,
        )

    # Only on success: a failing run exits above via fail(), which leaves
    # the throwaway HOME in place so the log can still be inspected.
    shutil.rmtree(home, ignore_errors=True)

    print(
        "OK: frozen, version %s, config.ini honoured, level = DEBUG applied, "
        "Speaking: logged" % (expected or "?")
    )


def _expected_version():
    """Read __version__ straight from the source tree, if we can find it."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(os.path.dirname(here), "Move_SR_Bridge", "version.py")
    try:
        with open(path, "r") as f:
            for line in f:
                if line.startswith("__version__"):
                    return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return None


def _read(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except OSError:
        return ""


if __name__ == "__main__":
    main()
