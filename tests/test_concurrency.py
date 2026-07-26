# test_concurrency.py - Races in helper lifecycle and debounce scheduling
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
Regression tests for three timing bugs that the main suite cannot reach.

test_helper_lifecycle.py's fakes flip _helper_is_running() to False the
instant terminate() is called, which is exactly the assumption these tests
have to break: a real helper's listening socket outlives its process by up
to ~1s, and sr_helper.py's own accept loop is why.

Nothing here sleeps waiting for a race to happen by luck.  The helper tests
drive a fake whose "socket" closes on an explicit call, and the debounce
test replaces threading.Timer so the callbacks fire in a chosen order.
"""

import configparser
import os
import sys
import types
import unittest

try:
    from unittest import mock
except ImportError:  # pragma: no cover
    import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stubs


class LingeringSocketProc(object):
    """A helper process whose port stays busy after the process exits.

    Models the real shutdown ordering that sr_helper.py's accept loop
    produces: the process handle reports exited while the OS still has the
    listening socket open, for a short but non-zero time.  `linger_probes`
    is how many port checks happen before the socket finally closes.
    """

    def __init__(self, pid, linger_probes=3):
        self.pid = pid
        self.exited = False
        self.port_open = True
        self.killed = False
        self._linger_probes = linger_probes

    def poll(self):
        return 0 if self.exited else None

    def wait(self, timeout=None):
        # Exits promptly on `quit`, but the port lingers.
        self.exited = True
        return 0

    def terminate(self):
        self.exited = True

    def kill(self):
        self.exited = True
        self.killed = True

    def probe_port(self):
        """One 'is the port busy?' check, ageing the lingering socket."""
        if self.exited and self.port_open:
            self._linger_probes -= 1
            if self._linger_probes <= 0:
                self.port_open = False
        return self.port_open


class HelperShutdownRaceTest(unittest.TestCase):
    """A start landing during a teardown must not lose the helper."""

    def setUp(self):
        self.m = stubs.import_bridge()
        self.m._helper_proc = None
        self.m._active_instances = 0
        self.launched = []
        self._pid = [2000]

        real_exists = os.path.exists

        def fake_exists(path):
            if str(path).endswith(("sr_helper_mac", "sr_helper.exe")):
                return True
            return real_exists(path)

        def fake_popen(argv, **kwargs):
            self._pid[0] += 1
            proc = LingeringSocketProc(self._pid[0])
            self.launched.append(proc)
            return proc

        def fake_is_running():
            # True while ANY launched helper still holds the port, even if
            # its process has already exited. Each call ages the lingering
            # socket, so a caller that retries eventually sees it close --
            # exactly what a real OS does.
            return any([p.probe_port() for p in self.launched])

        fake_bridge = types.SimpleNamespace(
            speak=lambda t: None, braille=lambda t: None, dialog=lambda t: None,
            close_socket=lambda: None, disconnect=lambda: None,
        )

        self._patchers = [
            mock.patch.object(self.m.subprocess, "Popen", fake_popen),
            mock.patch.object(os.path, "exists", fake_exists),
            mock.patch.object(self.m, "_helper_is_running", fake_is_running),
            mock.patch.object(self.m.time, "sleep", lambda s: None),
            mock.patch.object(self.m, "sr_bridge", fake_bridge, create=True),
            mock.patch.dict(
                sys.modules, {"Move_SR_Bridge.sr_bridge": fake_bridge}
            ),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in reversed(self._patchers):
            p.stop()
        self.m._helper_proc = None
        self.m._active_instances = 0

    def test_restart_after_shutdown_gets_a_live_helper(self):
        # Toggle the control surface off and straight back on -- Live does
        # this whenever the user reselects it in Preferences.
        # The teardown poll is capped, so the socket is still lingering
        # when the restart begins; it closes a moment later.
        self.m._start_helper()
        first = self.launched[0]
        first._linger_probes = 14      # outlasts _stop_helper's 10 polls

        self.m._stop_helper()          # process exits; port still busy
        self.assertTrue(first.exited, "first helper should have been stopped")
        self.assertTrue(
            first.port_open,
            "test setup: the socket must still be lingering at this point",
        )

        self.m._start_helper()         # user re-enables the control surface

        live = [p for p in self.launched if not p.exited]
        self.assertTrue(
            live,
            "after a stop/start cycle there must be a running helper; a "
            "start that probed the dying helper's socket would record no "
            "ownership and never relaunch, silencing speech for the rest "
            "of the session",
        )
        self.assertIsNotNone(
            self.m._helper_proc,
            "the new helper must be owned, or nothing will ever stop it",
        )

    def test_stop_does_not_hold_the_bookkeeping_lock_while_waiting(self):
        # _helper_lock must guard only _helper_proc/_active_instances.
        # If it is held across the multi-second teardown, Live's control
        # surface callback thread stalls behind it.
        self.m._start_helper()

        held_during_teardown = []
        real_wait = LingeringSocketProc.wait

        def probing_wait(proc_self, timeout=None):
            acquired = self.m._helper_lock.acquire(False)
            held_during_teardown.append(not acquired)
            if acquired:
                self.m._helper_lock.release()
            return real_wait(proc_self, timeout)

        with mock.patch.object(LingeringSocketProc, "wait", probing_wait):
            self.m._stop_helper()

        self.assertTrue(held_during_teardown, "teardown never waited")
        self.assertFalse(
            any(held_during_teardown),
            "_helper_lock must not be held across the blocking shutdown "
            "waits -- _stop_helper's own comment says it releases first",
        )

    def test_start_does_not_hold_the_bookkeeping_lock_while_launching(self):
        # Same requirement on the way up: Popen plus the up-to-1s
        # "did it start listening" poll must not block other instances.
        held = []

        real_popen = self.m.subprocess.Popen

        def probing_popen(argv, **kwargs):
            acquired = self.m._helper_lock.acquire(False)
            held.append(not acquired)
            if acquired:
                self.m._helper_lock.release()
            return real_popen(argv, **kwargs)

        with mock.patch.object(self.m.subprocess, "Popen", probing_popen):
            self.m._start_helper()

        self.assertTrue(held, "nothing was launched")
        self.assertFalse(
            any(held),
            "_helper_lock must not be held across subprocess.Popen() and "
            "the startup poll -- a second control surface slot connecting "
            "meanwhile stalls Live's UI",
        )


class RecordingTimer(object):
    """threading.Timer stand-in that fires only when told to."""

    instances = []

    def __init__(self, interval, function, args=None, kwargs=None):
        self.interval = interval
        self.function = function
        self.args = args or ()
        self.kwargs = kwargs or {}
        self.cancelled = False
        self.daemon = False
        RecordingTimer.instances.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    def join(self, timeout=None):
        pass

    def fire(self):
        """Run the callback exactly as the timer thread would."""
        self.function(*self.args, **self.kwargs)


class DebounceSchedulingTest(unittest.TestCase):
    """A fired timer must not consume a newer update's pending text."""

    def setUp(self):
        RecordingTimer.instances = []
        self.m = stubs.import_bridge()
        self.spoken = []
        self.display = types.SimpleNamespace(display=lambda content: None)
        self.surface = types.SimpleNamespace(display=self.display, song=None)

        fake_bridge = types.SimpleNamespace(
            speak=self.spoken.append, braille=lambda text: None,
            dialog=self.spoken.append,
        )
        cfg = configparser.ConfigParser()
        cfg.read_dict({
            "debounce": {"enabled": "true", "delay_ms": "300"},
            "logging": {"level": "INFO"},
        })

        patchers = [
            mock.patch.object(self.m, "sr_bridge", fake_bridge, create=True),
            mock.patch.dict(
                sys.modules, {"Move_SR_Bridge.sr_bridge": fake_bridge}
            ),
            mock.patch.object(self.m, "_cfg", cfg),
            mock.patch.object(self.m, "_dialog_is_open", lambda: False),
            mock.patch.object(self.m.threading, "Timer", RecordingTimer),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

        self.assertIsNotNone(
            self.m._install_display_hook(self.surface), "hook should install"
        )
        del self.spoken[:]
        RecordingTimer.instances = []

    def test_stale_timer_does_not_speak_the_next_update(self):
        self.display.display(
            stubs.HorizontalListContent(lines=["Cutoff", "800 Hz"])
        )
        self.display.display(
            stubs.HorizontalListContent(lines=["Cutoff", "900 Hz"])
        )

        self.assertEqual(len(RecordingTimer.instances), 2)
        timer_a, timer_b = RecordingTimer.instances
        self.assertTrue(timer_a.cancelled, "the first timer should be cancelled")

        # Timer A had already fired before it could be cancelled -- it is
        # now running its callback, after B was queued.
        timer_a.fire()
        self.assertEqual(
            self.spoken,
            [],
            "a superseded timer must not speak; it would announce the "
            "NEWER text immediately, collapsing the debounce window that "
            "the newer timer exists to enforce",
        )

        # B's own timer must still have something to say when it fires.
        timer_b.fire()
        self.assertEqual(
            self.spoken,
            ["Cutoff: 900 Hz"],
            "the newest update must still be announced by its own timer",
        )

    def test_announcement_error_does_not_kill_the_timer_thread(self):
        # _do_announce runs on the timer thread. An escaping exception
        # kills it silently -- inside Live, stderr goes nowhere, so the
        # failure would never reach Move_SR_Bridge.log at all.
        def boom(text):
            raise RuntimeError("screen reader went away")

        with mock.patch.object(self.m.sr_bridge, "speak", boom):
            self.display.display(
                stubs.HorizontalListContent(lines=["Cutoff", "800 Hz"])
            )
            self.assertEqual(len(RecordingTimer.instances), 1)
            try:
                RecordingTimer.instances[0].fire()
            except Exception as e:
                self.fail(
                    "the announcement callback must swallow and log "
                    "errors, not let them kill the timer thread: %r" % (e,)
                )


if __name__ == "__main__":
    unittest.main()
