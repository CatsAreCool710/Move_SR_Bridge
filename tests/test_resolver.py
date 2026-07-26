# test_resolver.py - Install-location resolution contract
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
Tests for scripts/lib/resolve_install_dir.sh.

Three implementations of one algorithm ship in this repo -- this shell
one, scripts/lib/ResolveInstallDir.ps1, and the resolver functions inside
"Install Move-SR-Bridge.js".  CLAUDE.md "Install Location Resolution"
states the tie-breaks all three must agree on, and until now none of them
had a single automated test: two divergences (a trailing slash surviving
in the middle of a path, and a JXA mtime sort that was silently a no-op)
both shipped and were only caught by running the three side by side.

Only the shell resolver is exercised here, because it is the only one of
the three that runs on the Linux box CI uses.  Its expected outputs are
the ones the other two were confirmed to match by hand -- so a change
that breaks the contract fails here first, rather than at install time on
somebody's machine.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RESOLVER = os.path.join(_REPO, "scripts", "lib", "resolve_install_dir.sh")

# Two <LibraryProject> entries inside <UserLibrary> plus a decoy outside
# it.  The first entry wins, the decoy is never seen, and the trailing
# slash on ProjectPath must not survive into the joined path.
_MULTI_CFG = """\
<?xml version="1.0" encoding="UTF-8"?>
<Ableton>
\t<UserLibrary>
\t\t<LibraryProject Id="0">
\t\t\t<ProjectLocation Value="" />
\t\t\t<ProjectName Value="User Library" />
\t\t\t<ProjectPath Value="/FIRST/path/" />
\t\t</LibraryProject>
\t\t<LibraryProject Id="1">
\t\t\t<ProjectName Value="Second Library" />
\t\t\t<ProjectPath Value="/SECOND/path" />
\t\t</LibraryProject>
\t</UserLibrary>
\t<OtherBlock>
\t\t<LibraryProject Id="9">
\t\t\t<ProjectName Value="Decoy" />
\t\t\t<ProjectPath Value="/DECOY/path" />
\t\t</LibraryProject>
\t</OtherBlock>
</Ableton>
"""

_SINGLE_CFG = """\
<?xml version="1.0" encoding="UTF-8"?>
<Ableton>
\t<UserLibrary>
\t\t<LibraryProject Id="0">
\t\t\t<ProjectName Value="%(name)s" />
\t\t\t<ProjectPath Value="%(path)s" />
\t\t</LibraryProject>
\t</UserLibrary>
</Ableton>
"""


@unittest.skipUnless(
    shutil.which("bash") and os.path.isfile(_RESOLVER),
    "needs bash and scripts/lib/resolve_install_dir.sh",
)
class ResolverShellTest(unittest.TestCase):
    """Drive the sourced shell functions directly."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="msb-resolver-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _run(self, body, env=None):
        """Source the resolver, run `body`, return its stdout."""
        script = ". %s\n%s" % (_shquote(_RESOLVER), body)
        full_env = dict(os.environ)
        # Never let the developer's own override leak into a test.
        full_env.pop("MOVE_SR_USER_LIBRARY", None)
        full_env["HOME"] = self.tmp
        if env:
            full_env.update(env)
        proc = subprocess.run(
            ["bash", "-c", script],
            env=full_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(
            proc.returncode, 0,
            "resolver script failed: %s" % proc.stderr.decode("utf-8", "replace"),
        )
        return proc.stdout.decode("utf-8")

    def _cfg(self, text):
        """Write a Library.cfg fixture and return a stub override for it."""
        path = os.path.join(self.tmp, "Library.cfg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        # Replacing the finder rather than laying out a fake
        # ~/Library/Preferences/Ableton tree keeps this test about parsing.
        return 'msb_newest_library_cfg() { printf "%%s\\n" %s; }\n' % _shquote(path)

    # -- parsing ---------------------------------------------------------

    def test_first_library_project_wins(self):
        # Lazy-vs-greedy: a plain `sed 's|.*<ProjectPath...|'` swallows up
        # to the LAST match, which disagreed with the PowerShell and JXA
        # resolvers on any cfg carrying more than one entry.
        out = self._run(self._cfg(_MULTI_CFG) + "msb_user_library_from_config")
        self.assertEqual(out.strip(), "/FIRST/path/User Library")

    def test_library_project_outside_user_library_is_ignored(self):
        self.assertNotIn(
            "DECOY",
            self._run(self._cfg(_MULTI_CFG) + "msb_user_library_from_config"),
        )

    def test_trailing_slash_on_project_path_is_stripped(self):
        # ProjectPath is Live-controlled data. Without the strip the join
        # produced "/lib//User Library", which works as a filesystem path
        # but is not byte-identical to what the other two resolvers build
        # -- and the sweep's "is this the copy I just installed?" test is
        # a string comparison.
        cfg = _SINGLE_CFG % {"name": "User Library", "path": "/some/lib///"}
        out = self._run(self._cfg(cfg) + "msb_user_library_from_config")
        self.assertEqual(out.strip(), "/some/lib/User Library")

    def test_missing_project_name_defaults(self):
        cfg = """\
<Ableton><UserLibrary><LibraryProject Id="0">
<ProjectPath Value="/some/lib" />
</LibraryProject></UserLibrary></Ableton>
"""
        out = self._run(self._cfg(cfg) + "msb_user_library_from_config")
        self.assertEqual(out.strip(), "/some/lib/User Library")

    def test_project_name_with_spaces_survives(self):
        cfg = _SINGLE_CFG % {"name": "My User Library", "path": "/some/lib"}
        out = self._run(self._cfg(cfg) + "msb_user_library_from_config")
        self.assertEqual(out.strip(), "/some/lib/My User Library")

    def test_unparseable_config_reports_failure(self):
        cfg = "<Ableton><NothingUseful /></Ableton>\n"
        out = self._run(
            self._cfg(cfg)
            + 'msb_user_library_from_config || echo "NOCONFIG"'
        )
        self.assertEqual(out.strip(), "NOCONFIG")

    # -- the MOVE_SR_USER_LIBRARY override -------------------------------

    def test_override_wins_over_library_cfg(self):
        lib = os.path.join(self.tmp, "Elsewhere")
        os.makedirs(os.path.join(lib, "Remote Scripts"))
        out = self._run(
            self._cfg(_MULTI_CFG)
            + 'msb_resolve_remote_scripts >/dev/null; printf "%s\\n" "$MSB_REMOTE_SCRIPTS"',
            env={"MOVE_SR_USER_LIBRARY": lib},
        )
        self.assertEqual(out.strip(), os.path.join(lib, "Remote Scripts"))

    def test_override_trailing_slash_is_stripped(self):
        # The same normalisation the Library.cfg path gets. All three
        # implementations must produce the same bytes here, because the
        # post-install sweep decides "is this the copy I just installed?"
        # by string comparison.
        #
        # Each of the three shipped this broken in its own way: the shell
        # never normalised the override at all, the JXA stripped after
        # joining rather than before, and PowerShell relied on Join-Path,
        # which absorbs one trailing separator but not two.
        lib = os.path.join(self.tmp, "Elsewhere")
        os.makedirs(os.path.join(lib, "Remote Scripts"))
        out = self._run(
            'msb_resolve_remote_scripts >/dev/null; printf "%s\\n" "$MSB_REMOTE_SCRIPTS"',
            env={"MOVE_SR_USER_LIBRARY": lib + "///"},
        )
        self.assertEqual(out.strip(), os.path.join(lib, "Remote Scripts"))

    def test_candidate_list_matches_the_resolved_path(self):
        # These two must agree exactly: install_mac.sh sweeps every
        # candidate and skips the one it just installed to by string
        # comparison. A mismatch would delete the fresh install.
        lib = os.path.join(self.tmp, "Elsewhere")
        os.makedirs(os.path.join(lib, "Remote Scripts", "Move_SR_Bridge"))
        out = self._run(
            'msb_resolve_remote_scripts >/dev/null\n'
            'printf "%s/Move_SR_Bridge\\n" "$MSB_REMOTE_SCRIPTS"\n'
            'msb_installed_dirs\n',
            env={"MOVE_SR_USER_LIBRARY": lib + "/"},
        )
        lines = [l for l in out.splitlines() if l.strip()]
        self.assertEqual(
            lines[0], lines[1],
            "the resolved install path and the candidate list must match "
            "byte for byte, or the post-install sweep deletes the copy it "
            "just made",
        )

    def test_unusable_override_is_an_error_not_a_fallback(self):
        # An override that cannot be used must fail loudly rather than
        # quietly installing somewhere the user did not ask for.
        os.makedirs(os.path.join(self.tmp, "Music", "Ableton", "User Library",
                                 "Remote Scripts"))
        out = self._run(
            'msb_resolve_remote_scripts || echo "REFUSED"',
            env={"MOVE_SR_USER_LIBRARY": "/nonexistent/nowhere"},
        )
        self.assertEqual(out.strip(), "REFUSED")

    # -- the default location --------------------------------------------

    def test_default_user_library_is_used_when_it_exists(self):
        default = os.path.join(self.tmp, "Music", "Ableton", "User Library")
        os.makedirs(os.path.join(default, "Remote Scripts"))
        out = self._run(
            'msb_resolve_remote_scripts >/dev/null\n'
            'printf "%s\\n%s\\n" "$MSB_REMOTE_SCRIPTS" "$MSB_SOURCE"'
        )
        lines = out.splitlines()
        self.assertEqual(lines[0], os.path.join(default, "Remote Scripts"))
        self.assertEqual(lines[1], "default User Library location")

    def test_create_makes_the_default_user_library(self):
        # Step 3b: far preferable to landing inside Live's app bundle.
        default = os.path.join(self.tmp, "Music", "Ableton", "User Library")
        out = self._run(
            'msb_resolve_remote_scripts create >/dev/null\n'
            'printf "%s\\n%s\\n" "$MSB_REMOTE_SCRIPTS" "$MSB_SOURCE"'
        )
        lines = out.splitlines()
        self.assertEqual(lines[0], os.path.join(default, "Remote Scripts"))
        self.assertEqual(lines[1], "newly created default User Library")
        self.assertTrue(os.path.isdir(lines[0]))

    def test_lookup_without_create_makes_no_directories(self):
        # uninstall and the helper launcher resolve without "create"; they
        # must never bring a Remote Scripts folder into existence.
        self._run('msb_resolve_remote_scripts >/dev/null 2>&1 || true')
        self.assertFalse(
            os.path.exists(os.path.join(self.tmp, "Music")),
            "resolving without 'create' must not create anything",
        )


class MtimeTieBreakTest(unittest.TestCase):
    """The "newest by mtime, never by name" rules, actually exercised.

    Both were previously asserted only in comments: the parsing tests stub
    msb_newest_library_cfg() out entirely, so nothing ran the `ls -t`
    that these rules live in.  That matters because this exact sort has
    already shipped as a silent no-op once -- in the JXA, where splitting
    do-shell-script output on "\\n" instead of "\\r" collapsed the list to
    one element and left the ordering alphabetical, which is precisely what
    the sort exists to avoid.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="msb-mtime-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _run(self, body, env=None):
        script = ". %s\n%s" % (_shquote(_RESOLVER), body)
        full_env = dict(os.environ)
        full_env.pop("MOVE_SR_USER_LIBRARY", None)
        full_env["HOME"] = self.tmp
        if env:
            full_env.update(env)
        proc = subprocess.run(
            ["bash", "-c", script],
            env=full_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(
            proc.returncode, 0,
            "resolver script failed: %s" % proc.stderr.decode("utf-8", "replace"),
        )
        return proc.stdout.decode("utf-8")

    def _make_cfg(self, live_version, project_path, mtime):
        """Create ~/Library/Preferences/Ableton/<ver>/Library.cfg."""
        d = os.path.join(
            self.tmp, "Library", "Preferences", "Ableton", live_version
        )
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "Library.cfg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "<?xml version=\"1.0\"?>\n<Ableton><UserLibrary>"
                "<LibraryProject Id=\"0\">"
                "<ProjectName Value=\"User Library\" />"
                "<ProjectPath Value=\"%s\" />"
                "</LibraryProject></UserLibrary></Ableton>\n" % project_path
            )
        os.utime(path, (mtime, mtime))
        return path

    def test_newest_library_cfg_wins_regardless_of_version_number(self):
        # The case the rule exists for: Live leaves old preference folders
        # behind forever, and the version number says nothing about which
        # one is in use -- only the mtime does.
        #
        # Asserted in BOTH directions on purpose. With only one fixture
        # pair, whichever way round it is chosen, a name sort agrees with
        # the mtime sort half the time -- so a single case can pass against
        # a resolver that lost its `-t` entirely. (It did: an earlier draft
        # of this test failed to notice exactly that mutation.)
        for newer, older, expected in (
            ("Live 12.4.5b8", "Live 12.4.3", "/RUNNING_THE_BETA"),
            ("Live 12.4.3", "Live 12.4.5b8", "/RUNNING_THE_STABLE"),
        ):
            with self.subTest(newest=newer):
                shutil.rmtree(
                    os.path.join(self.tmp, "Library"), ignore_errors=True
                )
                self._make_cfg(newer, expected, mtime=2_000_000_000)
                self._make_cfg(older, "/STALE", mtime=1_000_000_000)

                out = self._run("msb_user_library_from_config")

                self.assertEqual(
                    out.strip(), expected + "/User Library",
                    "must pick the most recently written Library.cfg (%s), "
                    "not whichever version string sorts first" % newer,
                )

    def test_windows_style_preferences_subdir_is_also_searched(self):
        # Older layouts kept Library.cfg one level up; both are scanned.
        d = os.path.join(
            self.tmp, "Library", "Preferences", "Ableton", "Live 12.4.3",
            "Preferences",
        )
        os.makedirs(d)
        path = os.path.join(d, "Library.cfg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "<Ableton><UserLibrary><LibraryProject Id=\"0\">"
                "<ProjectName Value=\"User Library\" />"
                "<ProjectPath Value=\"/DEEPER\" />"
                "</LibraryProject></UserLibrary></Ableton>\n"
            )
        os.utime(path, (2_000_000_000, 2_000_000_000))

        out = self._run("msb_user_library_from_config")
        self.assertEqual(out.strip(), "/DEEPER/User Library")

    def test_paths_with_spaces_survive_the_mtime_sort(self):
        # `ls -t | head -1` rather than a for-loop over command
        # substitution, because every real path here has a space in it
        # ("Live 12.4.3", "User Library") and word-splitting would shred it.
        self._make_cfg(
            "Live 12 Suite Beta", "/Users/me/My Music Stuff",
            mtime=2_000_000_000,
        )
        out = self._run("msb_newest_library_cfg")
        self.assertTrue(
            out.strip().endswith("Live 12 Suite Beta/Library.cfg"),
            "a path containing spaces must come back intact, got %r" % out,
        )

    def test_no_library_cfg_at_all_is_not_an_error(self):
        out = self._run("msb_newest_library_cfg; echo rc=$?")
        self.assertIn("rc=0", out)

    def test_live_apps_are_listed_newest_first_not_alphabetically(self):
        # "Ableton Live 9 Trial" sorts after "Ableton Live 11" as a string.
        apps = os.path.join(self.tmp, "Applications")
        os.makedirs(apps)
        for name, mtime in (
            ("Ableton Live 11.app", 2_000_000_000),
            ("Ableton Live 9 Trial.app", 1_000_000_000),
        ):
            d = os.path.join(apps, name)
            os.makedirs(d)
            os.utime(d, (mtime, mtime))

        # The helper hardcodes /Applications, so point the glob at ours.
        out = self._run(
            'msb_live_apps_newest_first() { ls -td %s/*.app 2>/dev/null; }\n'
            "msb_live_apps_newest_first" % _shquote(apps)
        )
        order = [os.path.basename(p) for p in out.strip().splitlines()]
        self.assertEqual(
            order,
            ["Ableton Live 11.app", "Ableton Live 9 Trial.app"],
            "newest by mtime first; alphabetical order would invert this",
        )

    def test_candidate_dirs_use_the_same_app_ordering(self):
        # msb_all_candidate_dirs used a bare glob (alphabetical) while the
        # resolver used mtime, so the two disagreed about which Live came
        # first on the same machine.
        apps = os.path.join(self.tmp, "Applications")
        first = os.path.join(apps, "Ableton Live Z.app")   # alphabetically last
        second = os.path.join(apps, "Ableton Live A.app")  # alphabetically first
        os.makedirs(first)
        os.makedirs(second)

        out = self._run(
            'msb_live_apps_newest_first() { printf "%%s\\n" %s %s; }\n'
            "msb_all_candidate_dirs" % (_shquote(first), _shquote(second))
        )
        app_lines = [l for l in out.splitlines() if l.startswith(apps)]
        self.assertEqual(
            app_lines,
            [
                first + "/Contents/App-Resources/MIDI Remote Scripts/Move_SR_Bridge",
                second + "/Contents/App-Resources/MIDI Remote Scripts/Move_SR_Bridge",
            ],
            "the candidate list must preserve msb_live_apps_newest_first's "
            "order rather than re-globbing alphabetically",
        )

    def test_recorded_user_library_is_a_candidate(self):
        # The graphical installer's "choose a folder" branch writes this.
        # Without it that copy is invisible to every uninstaller and to the
        # next install's stale sweep, so it shadows the new package forever.
        os.makedirs(os.path.join(self.tmp, ".move_sr_bridge"))
        with open(
            os.path.join(self.tmp, ".move_sr_bridge", "install_location"),
            "w", encoding="utf-8",
        ) as f:
            f.write("/Volumes/Audio/My Library//\n")

        out = self._run("msb_all_candidate_dirs")

        self.assertIn(
            "/Volumes/Audio/My Library/Remote Scripts/Move_SR_Bridge",
            out.splitlines(),
            "a hand-picked install location must be swept like any other",
        )


def _shquote(s):
    return "'" + s.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    unittest.main()
