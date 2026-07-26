# test_helper_lifecycle.py - Helper process ownership / refcount tests
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
Tests for _start_helper() / _stop_helper() ownership tracking.

Regression cover for the bug where a second control surface slot probing
port 8765 cleared the ownership recorded by the slot that actually
launched the helper, leaking the process past Live's exit.

Nothing here spawns a process or touches a socket: Popen, os.path.exists,
_helper_is_running and the sr_bridge module are all replaced.
"""

import configparser
import os
import sys
import threading
import time
import types
import unittest

try:
    from unittest import mock
except ImportError:  # pragma: no cover
    import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stubs


class FakeProc(object):
    """Stands in for subprocess.Popen's return value.

    Exits when terminated, so the escalation stops at terminate() -- the
    ordinary case.  FakeStubbornProc below refuses to, which is what drives
    the kill() arm.
    """

    def __init__(self, pid):
        self.pid = pid
        self.terminated = False
        self.killed = False
        self.waited_cleanly = False

    def poll(self):
        return None  # always "still running" until terminated

    def wait(self, timeout=None):
        # Never exits on its own, so _stop_helper() falls through to
        # terminate() -- the path we want to assert on.
        if self.terminated:
            return 0
        raise stubs.import_bridge().subprocess.TimeoutExpired("helper", timeout)

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class FakeStubbornProc(FakeProc):
    """A helper that ignores SIGTERM, like one blocked in osascript.

    This is the case the kill() escalation exists for: without it such a
    helper outlives Live and holds port 8765 against the next session.  The
    original FakeProc had no kill() at all, so _shutdown_owned_helper()
    reached proc.kill(), raised AttributeError, and had it swallowed by the
    catch-all -- the escalation was never actually exercised.
    """

    def wait(self, timeout=None):
        if self.killed:
            return -9
        raise stubs.import_bridge().subprocess.TimeoutExpired("helper", timeout)


class HelperLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.m = stubs.import_bridge()
        self.launched = []
        self._pid = [1000]
        # Swapped by individual tests to change how the fake helper behaves.
        self.proc_factory = FakeProc

        # Reset module-global ownership state between tests.
        self.m._helper_proc = None
        self.m._active_instances = 0
        # Also a module global, and one no test used to reset. Left True by
        # an earlier test it sends the next _start_helper() into a 2s wait
        # -- invisible here only because time.sleep is patched out.
        self.m._helper_port_lingering[0] = False

        real_exists = os.path.exists

        def fake_exists(path):
            if str(path).endswith(("sr_helper_mac", "sr_helper.exe")):
                return True
            return real_exists(path)

        def fake_popen(argv, **kwargs):
            self._pid[0] += 1
            proc = self.proc_factory(self._pid[0])
            self.launched.append(proc)
            return proc

        def fake_is_running():
            # "Something is listening" iff a helper we know about is alive.
            return any(not p.terminated for p in self.launched)

        self.fake_sr_bridge = types.SimpleNamespace(
            speak=lambda text: None,
            dialog=lambda text: None,
            braille=lambda text: None,
            close_socket=lambda: None,
            disconnect=lambda: None,
        )

        self._patchers = [
            mock.patch.object(self.m.subprocess, "Popen", fake_popen),
            mock.patch.object(os.path, "exists", fake_exists),
            mock.patch.object(self.m, "_helper_is_running", fake_is_running),
            mock.patch.object(self.m.time, "sleep", lambda s: None),
            mock.patch.dict(
                sys.modules,
                {"Move_SR_Bridge.sr_bridge": self.fake_sr_bridge},
            ),
            mock.patch.object(self.m, "sr_bridge", self.fake_sr_bridge, create=True),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in reversed(self._patchers):
            p.stop()
        self.m._helper_proc = None
        self.m._active_instances = 0
        self.m._helper_port_lingering[0] = False

    # -- single slot --------------------------------------------------
    def test_single_instance_launches_and_terminates(self):
        self.m._start_helper()
        self.assertEqual(len(self.launched), 1, "should launch exactly one helper")
        self.assertIsNotNone(self.m._helper_proc, "should record ownership")

        self.m._stop_helper()
        self.assertTrue(self.launched[0].terminated, "should stop the helper it owns")
        self.assertFalse(
            self.launched[0].killed,
            "a helper that responds to terminate() must not also be killed",
        )
        self.assertIsNone(self.m._helper_proc)
        # Internal bookkeeping checked last, so a behavioural regression
        # surfaces as a behavioural failure rather than a counter mismatch.
        self.assertEqual(self.m._active_instances, 0)

    def test_helper_ignoring_sigterm_is_killed(self):
        # The last rung of quit -> terminate -> kill. A helper blocked in
        # subprocess.run(osascript) ignores SIGTERM; without kill() it
        # outlives Live and holds port 8765 against the next session.
        self.proc_factory = FakeStubbornProc
        self.m._start_helper()
        proc = self.launched[0]

        self.m._stop_helper()

        self.assertTrue(proc.terminated, "should try terminate() first")
        self.assertTrue(proc.killed, "must escalate to kill() when SIGTERM is ignored")
        self.assertIsNone(self.m._helper_proc)

    # -- two slots: the regression ------------------------------------
    def test_second_instance_does_not_clobber_ownership(self):
        self.m._start_helper()          # slot 1 launches
        proc = self.launched[0]
        self.m._start_helper()          # slot 2 finds the port busy

        self.assertEqual(len(self.launched), 1, "second slot must not launch another")
        self.assertIs(
            self.m._helper_proc, proc,
            "second slot must not clear the first slot's ownership",
        )
        self.assertEqual(self.m._active_instances, 2)  # bookkeeping, checked last

    def test_helper_survives_until_last_instance_disconnects(self):
        self.m._start_helper()
        self.m._start_helper()
        proc = self.launched[0]

        self.m._stop_helper()           # slot 1 leaves
        self.assertFalse(
            proc.terminated,
            "helper must stay up while another slot is still using it",
        )
        self.assertIs(self.m._helper_proc, proc)

        self.m._stop_helper()           # slot 2 leaves -- last one out
        self.assertTrue(
            proc.terminated,
            "helper must be stopped once the last slot disconnects -- "
            "this is the leak the ownership refcount fixes",
        )
        self.assertIsNone(self.m._helper_proc)
        # Internal bookkeeping checked last, so the leak above surfaces as a
        # behavioural failure rather than a counter mismatch.
        self.assertEqual(self.m._active_instances, 0)

    # -- externally started helper ------------------------------------
    def test_external_helper_is_left_running(self):
        external = FakeProc(999)
        self.launched.append(external)  # pretend it already holds the port

        self.m._start_helper()
        self.assertEqual(len(self.launched), 1, "must not launch alongside one")
        self.assertIsNone(
            self.m._helper_proc, "must not claim ownership of a helper we found"
        )

        self.m._stop_helper()
        self.assertFalse(
            external.terminated, "a manually-started helper must be left alone"
        )

    def test_refcount_does_not_go_negative(self):
        # Defensive: an unbalanced stop must not leave the counter negative,
        # which would make the next start/stop pair skip teardown.
        self.m._stop_helper()
        self.assertEqual(self.m._active_instances, 0)
        self.m._start_helper()
        self.m._stop_helper()
        self.assertTrue(self.launched[0].terminated)

    # -- registration must survive a failed construction ----------------
    def test_failed_construction_releases_registration(self):
        # create_instance() registers before building the surface. If the
        # constructor raises, no instance will ever exist to release it,
        # and an orphaned registration keeps the refcount permanently
        # non-zero -- so no later instance could shut the helper down.
        boom = RuntimeError("constructor blew up")

        with mock.patch.object(self.m, "Move", side_effect=boom):
            self.assertRaises(
                RuntimeError, self.m.create_instance, object()
            )

        self.assertEqual(
            self.m._active_instances,
            0,
            "a failed construction must not orphan its registration",
        )

        # A later, successful instance must still be able to tear down.
        self.m._start_helper()
        self.m._stop_helper()
        self.assertTrue(
            self.launched[-1].terminated,
            "orphaned registration would block all future teardown",
        )


class DisconnectIdempotenceTest(unittest.TestCase):
    """Live can call disconnect() more than once on the same instance."""

    def setUp(self):
        self.m = stubs.import_bridge()
        self.m._helper_proc = None
        self.m._active_instances = 0
        self.stopped = []
        self._patcher = mock.patch.object(
            self.m, "_stop_helper", lambda: self.stopped.append(True)
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self.m._helper_proc = None
        self.m._active_instances = 0

    def _make_instance(self):
        surface = self.m.Move.__new__(self.m.Move)
        surface._sr_registered = True     # as set by a successful __init__
        surface._sr_hook_installed = False
        surface._sr_teardown_hook = None
        return surface

    def test_double_disconnect_releases_registration_once(self):
        surface = self._make_instance()
        surface.disconnect()
        surface.disconnect()
        self.assertEqual(
            len(self.stopped),
            1,
            "a second disconnect must not release the registration again -- "
            "over-decrementing kills a helper another slot is still using",
        )

    def test_teardown_hook_invoked_once(self):
        calls = []
        surface = self._make_instance()
        surface._sr_teardown_hook = lambda: calls.append(True)
        surface.disconnect()
        surface.disconnect()
        self.assertEqual(len(calls), 1)

    def test_disconnect_survives_a_raising_teardown_hook(self):
        # The hook teardown runs before Live's own disconnect() and before
        # the helper registration is released. If it can abort disconnect(),
        # _stop_helper() never runs, the refcount stays non-zero forever,
        # and no later instance can shut the helper down.
        def boom():
            raise RuntimeError("display object went away")

        surface = self._make_instance()
        surface._sr_teardown_hook = boom
        surface.disconnect()
        self.assertEqual(
            len(self.stopped),
            1,
            "a raising teardown hook must not strand the registration",
        )


class DebounceCancelTest(unittest.TestCase):
    """_cancel_pending() must not let a fired timer speak afterwards."""

    # The one test in the suite that uses real timers, so the delay it
    # depends on is pinned here rather than inherited from whatever
    # config.py happens to write into the temp HOME. Left implicit, a
    # change to the default delay_ms would make this test either vacuous
    # (delay 0: the timer fires before we can cancel) or slow.
    DELAY_MS = 300
    SPEAK_SECONDS = 0.2

    def setUp(self):
        self.m = stubs.import_bridge()
        cfg = configparser.ConfigParser()
        cfg.read_dict({
            "debounce": {"enabled": "true", "delay_ms": str(self.DELAY_MS)},
            "logging": {"level": "INFO"},
        })
        p = mock.patch.object(self.m, "_cfg", cfg)
        p.start()
        self.addCleanup(p.stop)

    def test_cancel_waits_for_an_already_fired_announcement(self):
        # _do_announce() releases the debounce lock before it speaks, so a
        # timer that has already fired is past the point cancel() can stop
        # it. _cancel_pending() must join it, or the stale text lands after
        # the caller's own announcement ("Move disconnected").
        #
        # Timing: debounce fires at 300ms; speak() then takes 200ms. Cancel
        # is called at ~400ms, i.e. while the announcement is mid-flight.
        # The speak is deliberately bounded -- blocking it indefinitely
        # would just exhaust _cancel_pending()'s join timeout and let the
        # race through regardless of the fix.
        events = []
        speaking = threading.Event()

        display = types.SimpleNamespace(display=lambda content: None)
        surface = types.SimpleNamespace(display=display, song=None)

        def slow_speak(text):
            events.append("announce:" + text)
            speaking.set()
            time.sleep(self.SPEAK_SECONDS)
            events.append("announce-done:" + text)

        fake_bridge = types.SimpleNamespace(
            speak=slow_speak, braille=lambda text: None
        )

        # `from . import sr_bridge` inside _install_display_hook resolves the
        # attribute already set on the package, so patching sys.modules alone
        # is ignored and the real socket client gets used -- which made an
        # earlier version of this test silently vacuous.
        with mock.patch.object(
            self.m, "sr_bridge", fake_bridge, create=True
        ), mock.patch.dict(
            sys.modules, {"Move_SR_Bridge.sr_bridge": fake_bridge}
        ):
            cancel = self.m._install_display_hook(surface)
            self.assertIsNotNone(cancel, "hook should install")

            del events[:]        # drop the "Move connected" announcement
            speaking.clear()

            display.display(stubs.Content(lines=["Cutoff", "800 Hz"]))
            # The event is set from inside slow_speak(), so returning from
            # this wait already proves the timer fired and is mid-flight --
            # no sleep needed to "probably" be inside speak() by now.
            self.assertTrue(
                speaking.wait(5), "debounced announcement never fired"
            )

            cancel()             # what disconnect() does...
            events.append("farewell")   # ...immediately before speaking

        self.assertIn("announce-done:Cutoff, 800 Hz", events)
        self.assertLess(
            events.index("announce-done:Cutoff, 800 Hz"),
            events.index("farewell"),
            "a stale announcement must finish before the farewell, not "
            "after it; got %r" % (events,),
        )


class LiveListenerTest(unittest.TestCase):
    """Installing and removing Live's selection listeners must never raise.

    Two shipped regressions live here: `self.song()` called as a method
    when it is a property, and an uncaught exception escaping install into
    on_identified(), which left Live thinking hardware identification had
    not completed and broke normal display updates.  Both were invisible to
    the suite because this code had no tests at all.
    """

    def setUp(self):
        self.m = stubs.import_bridge()

    def _surface(self, song):
        surface = self.m.Move.__new__(self.m.Move)
        surface.song = song
        return surface

    def _fake_song(self):
        installed = []

        class Prop(object):
            def __init__(self, name):
                self.name = name

            def has_listener(self, h):
                return (self.name, h) in installed

            def add_listener(self, h):
                installed.append((self.name, h))

            def remove_listener(self, h):
                installed.remove((self.name, h))

        props = {}

        def make(owner, name):
            p = Prop(name)
            props[name] = p
            setattr(owner, "%s_has_listener" % name, p.has_listener)
            setattr(owner, "add_%s_listener" % name, p.add_listener)
            setattr(owner, "remove_%s_listener" % name, p.remove_listener)

        view = types.SimpleNamespace()
        make(view, "selected_track")
        make(view, "selected_scene")
        song = types.SimpleNamespace(view=view, tracks=[], scenes=[])
        make(song, "tracks")
        make(song, "scenes")
        return song, installed

    def test_listeners_install_and_remove_cleanly(self):
        song, installed = self._fake_song()
        surface = self._surface(song)

        surface._install_live_listeners()
        self.assertEqual(
            sorted(n for n, _ in installed),
            ["scenes", "selected_scene", "selected_track", "tracks"],
            "all four listeners should be installed",
        )

        surface._remove_live_listeners()
        self.assertEqual(installed, [], "all four should be removed again")

    def test_installing_twice_does_not_double_register(self):
        song, installed = self._fake_song()
        surface = self._surface(song)

        # Live fires on_identified() more than once per connection.
        surface._install_live_listeners()
        surface._install_live_listeners()

        self.assertEqual(len(installed), 4, "must not register twice")

    def test_song_is_a_property_not_a_method(self):
        # `self.song()` raised TypeError on every install, silently, because
        # the per-listener except swallowed it -- so the listeners simply
        # never worked and nothing said so.
        song, installed = self._fake_song()
        surface = self._surface(song)
        surface._install_live_listeners()
        self.assertEqual(
            len(installed),
            4,
            "song must be accessed as a property; treating it as callable "
            "makes every listener silently fail to install",
        )

    def test_install_survives_a_song_that_raises(self):
        # Runs inside on_identified(). An escaping exception can leave Live
        # believing identification did not complete, which breaks the
        # ordinary display updates as well as ours.
        class Boom(object):
            @property
            def view(self):
                raise RuntimeError("no song yet")

        surface = self._surface(Boom())
        surface._install_live_listeners()      # must not raise
        surface._remove_live_listeners()       # nor this

    def test_remove_survives_a_missing_song(self):
        # Runs first thing in disconnect(); raising here would abort the
        # rest of teardown, including _stop_helper().
        surface = self.m.Move.__new__(self.m.Move)

        class NoSong(object):
            @property
            def song(self):
                raise RuntimeError("song is gone")

        surface.__class__ = type(
            "MoveWithNoSong", (self.m.Move,), {"song": NoSong.song}
        )
        surface._remove_live_listeners()       # must not raise


if __name__ == "__main__":
    unittest.main()
