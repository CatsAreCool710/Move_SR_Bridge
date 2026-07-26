# Move-SR-Bridge -- Agent Instructions

This file provides context for AI coding agents (GitHub Copilot, Cursor, etc.) working on this project.

## Project Overview

Move-SR-Bridge adds screen reader support to the Ableton Move hardware controller when used with Ableton Live. It intercepts text rendered to the Move's OLED display and routes it to the active screen reader.

## Architecture

This is a **two-process** system. The reason is that Ableton Live's embedded Python 3.11 does not include `ctypes` (the `_ctypes` native module is not compiled in), so DLLs cannot be loaded from within the MIDI Remote Script.

### Process 1: MIDI Remote Script (runs inside Live)

- **Location:** `Move_SR_Bridge/` (deployed to the Ableton User Library's `Remote Scripts/` on both platforms -- see Key Paths)
- **Entry point:** `__init__.py` -- subclasses the stock `Move` control surface
- **Display hook:** monkey-patches `Display.display()` after `on_identified()` to intercept OLED content
- **TCP client:** `sr_bridge.py` sends JSON commands over TCP to `127.0.0.1:8765`
- **Constraint:** Only `socket`, `subprocess`, `json`, and other pure-Python/statically-linked modules are available. **No `ctypes`, no `pip` packages.**
- **Python version:** Must be compatible with Python 3.11 (Live's embedded interpreter). No 3.12+ features.

### Process 2: Helper (runs via system Python or compiled binary)

- **Source:** `sr_helper.py` (cross-platform)
- **Compiled:** `sr_helper.exe` (Windows) or `sr_helper_mac` (macOS)
- **Role:** TCP server on port 8765. Receives JSON commands, forwards speech/braille to screen readers.
- **Platform backends:**
  - **Windows:** Loads `Tolk.dll` via `ctypes.cdll` (cdecl calling convention). Dependencies: `Tolk.dll` + `nvdaControllerClient64.dll`.
  - **macOS (Tahoe 26+):** Speaks via VoiceOver AppleScript (`osascript`). Braille handled automatically by VoiceOver. Requires "Allow VoiceOver to be controlled with AppleScript" enabled in VoiceOver Utility.

### Communication Protocol

Newline-delimited JSON over TCP to `127.0.0.1:8765`:

```json
{"cmd": "speak", "text": "..."}
{"cmd": "braille", "text": "..."}
{"cmd": "dialog", "text": "..."}
{"cmd": "cancel"}
{"cmd": "quit"}
```

## File Structure

```
Move_SR_Bridge/                  MIDI Remote Script package
  __init__.py                    Entry point, Move subclass, display hook
  config.py                      Config loader + STATE_DIR/CONFIG_FILE/LOG_PATH
  version.py                     __version__ -- single source, asserted against the tag by CI
  sr_bridge.py                   TCP socket client (runs in Live)
  sr_helper.py                   TCP server + screen reader bridge (cross-platform)
  sr_helper.exe                  Windows: compiled helper (PyInstaller onefile)
  sr_helper_mac                  macOS: compiled helper (PyInstaller onefile)
  Tolk.dll                       Windows: screen reader abstraction (64-bit, cdecl)
  nvdaControllerClient64.dll     Windows: NVDA companion DLL (loaded by Tolk)

scripts/                         Build and deployment scripts
  build.py                       PyInstaller build script (Windows)
  build_mac.py                   PyInstaller build script (macOS)
  smoke_helper.py                Runs a BUILT helper against a real config.ini
  install.bat                    Windows: deploy to Live (pre-built, with .exe)
  install_from_source.bat        Windows: deploy to Live (source only, no .exe)
  uninstall.bat                  Windows: uninstall from Live
  start_helper.bat               Windows: manual helper launcher (visible console)
  install_mac.sh                 macOS: deploy to Live (User Library)
  uninstall_mac.sh               macOS: uninstall from Live
  start_helper_mac.sh            macOS: manual helper launcher
  release_mac.sh                 macOS: local release builder
  lib/resolve_install_dir.sh     Install-location resolver (macOS, sourced)
  lib/ResolveInstallDir.ps1      Install-location resolver (Windows, invoked)
  installer/mac/                 JXA graphical installer sources

tests/                           Unit tests -- stdlib unittest, no deps
  stubs.py                       Fake Move package so the real package imports
  test_helper_lifecycle.py       Helper ownership refcount, kill escalation,
                                  Live selection listeners
  test_format_content.py         Display-content formatting branches
  test_protocol.py               JSON line protocol over a socketpair,
                                  AppleScript escaping
  test_display_hook.py           What the installed hook actually announces
  test_concurrency.py            Helper start/stop races, debounce scheduling
  test_resolver.py               Install-location resolution contract (shell)
  test_config.py                 A bad config.ini must not kill the surface
  test_sr_bridge.py              The socket client, incl. macOS braille skip

tools/                           Manual diagnostics -- not installed, not
  speech_history_logger.py        started by the helper, macOS only. Polls
                                  VoiceOver for every phrase it speaks,
                                  including Live's own narration, which
                                  Move_SR_Bridge cannot see.
```

## Speech Normalisation Rules

`_format_content(content, active_parameter=None)` returns an `_Announcement(text, name, value, is_notification, is_automated)` namedtuple or `None`. Never reconstruct `value` by slicing `text` -- that contract was removed on purpose. `active_parameter` is optional and only used for rule 5c; the function is otherwise **pure**, and must stay that way: it never reads Live's state. The double-speech comparison (rule 10) lives in `_consider_announcing`, not here.

1. **U+E044 (`_AUTOMATION_CHAR`)** is Live's "parameter is automated" icon. It becomes the word "automated" in `text` and is kept out of `name` (which is matched against Live's selected track/scene). Never forward it to speech. Because it rides on the name, `is_automated` reports it separately -- the caller can drop the name and must not lose the marker with it.
2. **Any other Private Use Area codepoint** is an icon glyph -- strip it. BMP block `U+E000`-`U+F8FF` only.
3. **`_ABBREVIATIONS`** expands only abbreviations that are unreadable aloud. Do NOT add `Freq`, `LFO`, `Env` etc.; those match Live's own UI naming and expanding them would diverge from what a user hears elsewhere in Live.
4. **`_join_lines()`** uses `", "` unless the next line starts lowercase (Live wrapping one sentence across lines).
5. **Overlays** must not reset main-screen change detection -- the hook keeps `last_main` separate from `last_announced`, or every transient overlay re-announces the screen underneath when it clears. An overlay is a notification, a touched encoder, or the shutdown prompt: this is Live's own `in_critical_display_state()` taxonomy, not ours. Read the active parameter with `dict.get(component_map, 'Active_Parameter')`, **never** `component_map[...]` -- Live's `ComponentMap.__getitem__` lazily constructs and caches an absent component, which is a side effect on Live's control surface from a function that runs every frame.

5b. **A modal dialog is an episode, not a screen.** Live's cached `any_dialog_open` lags `open_dialog_count`, so `main_view` flaps between the dialog message and the view underneath. Announce each *distinct* screen once per episode, leaving `last_main` untouched throughout. Not "the first screen only" -- the flap can put the stale main view first, and that would spend the announcement on the wrong screen and never tell the user a dialog is up.

5c. **`Content.value` is sometimes the only value.** `parameter_view`'s master-track branch is `Content(lines=['Volume', '', ''], value=<0-1 float>)` -- the level is only the bar graphic. When the parameter overlay yields one text line, append `str(parameter)`. Never for multi-line overlays; those already carry a value string.

5d. **Say the real dialog text, and only when Live is in the background.** Prefer `Application.current_dialog_message` over the Move's generic "Live is showing a dialog..." screen. Send it with `cmd: "dialog"`, not `speak`: on macOS the helper drops it while Live is frontmost, because VoiceOver announces the dialog itself and preempts us anyway (measured -- our output was issued 1ms in and lost to VoiceOver's focus announcement 261ms later; `output` has no queue or priority parameter). Frontmost detection is `lsappinfo front` (no Accessibility permission needed), Live is `com.ableton.live`, and it fails open. Windows stays unconditional -- untested there.
6. **Urgent screens** (modal dialog via `Live.Application.get_application().open_dialog_count`, and the shutdown prompt) bypass the debounce and cancel anything queued.
7. **`list_index` indexes the position-aligned line list**, never the filtered one. Live's index refers to `content.lines`; indexing a list with empties removed shifts every later entry and announces the wrong menu item.
8. **Every debounce timer carries a generation**; it speaks only if `_debounce_gen` still matches. `cancel()` cannot stop a timer that has already started running. `_cancel_pending()` **joins** the timer only when `wait=True`, which only teardown passes: the redraw path runs on Live's display callback ahead of Live's own rendering, so a join there can stall the OLED for a second.
9. **The catch-alls must swallow, log, and be readable at INFO.** `_do_announce()` (timer thread) and `_intercepted_display()` (Live's callback) both report via `_log_failure()`: first occurrence per site at ERROR, the rest at DEBUG. Logging them all at DEBUG -- which is what they did -- meant a hook throwing every frame was silent at the default level. Logging them all at ERROR buries the log, since Live redraws several times a second.
10. **Strip the redundant track/scene name in `_consider_announcing`, not `_format_content`.** Live narrates the selected track itself, so when `announcement.name` matches, speak only the value -- but re-prepend "automated" when `is_automated`, or an automated parameter on the selected track reads as a bare "0 dB".
11. **Live's own `display.display` must always be called**, outside the try and never behind an early return, and must be **restored on disconnect**. While the patch is in place a frame arriving after teardown can queue a fresh announcement and speak after "Move disconnected".
12. **`_get_dialog_message()` uses `getattr(app, name, sentinel)` inside a `try`, never `hasattr`.** `hasattr` swallows only `AttributeError`, so a property raising anything else escapes it -- and this runs while a modal dialog has Live's UI blocked.
13. **Braille sends are skipped on macOS**, hardcoded in `sr_bridge.py`, because VoiceOver brailles whatever it speaks. That decision belongs to `sr_bridge`, not to the display hook.
14. **`config.ini` failures must never reach Live.** The read happens at module import; anything escaping removes Move_SR_Bridge from the Control Surface dropdown. `UnicodeDecodeError` is **not** a `configparser.Error`, and `getattr(logging, level_name)` can return a non-int -- check with `isinstance`, and reject `NOTSET`.
15. **Teardown escalates `quit` -> `terminate()` -> `kill()`.** A helper blocked in `subprocess.run(osascript)` ignores SIGTERM and would otherwise outlive Live holding port 8765.

Live ships the Move scripts as `.pyc` only (Python 3.11). To inspect them: `uv python install 3.11`, then `marshal.load()` past the 16-byte header and `dis.dis()`. See CLAUDE.md for the full command.

## Freezing the helper

`sr_helper.py` imports `config.py` at **runtime** from its install directory (`sys.path.insert(0, _script_dir)`), deliberately, so both processes share one config module instead of two copies that drift. PyInstaller's static analysis cannot see that import, so nothing `config.py` needs is collected automatically -- and the failure is **silent**. `configparser` was missing from every frozen release: `import config` raised, the helper fell back to built-in defaults, `config.ini` was ignored entirely, and the only symptom was `level = DEBUG` doing nothing and every `Speaking:` line missing while speech kept working.

- Both build scripts pass `--hidden-import configparser`. Any new runtime-only import needs the same.
- The helper reports `Log level: <LEVEL> (config: ok|<why not>) [frozen]` at startup. Read that line first when the log looks empty.
- `scripts/smoke_helper.py <built binary>` runs the real binary against a real `config.ini` and fails if it did not take effect. Both build jobs run it; the unit suite cannot catch this class of bug because it tests the source, not what got packaged.

## Release Process

1. Bump `__version__` in `Move_SR_Bridge/version.py`.
2. Commit, then tag `v<__version__>` and push the tag.
3. `.github/workflows/build.yml` runs **only on `v*` tags** (deliberately -- no
   build or check runs on push/PR). Two jobs gate both platform builds:
   `verify-version` fails the release if the tag and `version.py` disagree, and
   `test` runs the unit suite plus `compileall` **on Python 3.11**, matching
   Live's embedded interpreter so 3.12+ syntax cannot slip through.

## Critical Rules

1. **Never use `ctypes` in `__init__.py` or `sr_bridge.py`** -- these run inside Live's Python which does not have it.
2. **Everything in `Move_SR_Bridge/` must be valid Python 3.11** (Live's embedded interpreter). No 3.12+ syntax: no PEP 695 generics (`def f[T](...)`), no `type` statement. Everything up to and including 3.11 is fine -- f-string `=` debug syntax is 3.8+ and is *not* a problem, despite what an earlier version of this file claimed.
3. **Tolk uses cdecl** (`ctypes.cdll`), not stdcall (`ctypes.windll`). String params are `c_wchar_p`.
4. **All Python files must have GPLv3 license headers.** Copyright holder: Jeremiah Ticket.
5. **The package folder name must be a valid Python identifier** -- `Move_SR_Bridge` with underscores, not hyphens.
6. **Log prefix:** All logger calls use `Move_SR_Bridge:` as the prefix.
7. **Log file:** `~/.move_sr_bridge/Move_SR_Bridge.log`. `config.py` owns `STATE_DIR` / `CONFIG_FILE` / `LOG_PATH`; `__init__.py` and `sr_helper.py` import those constants rather than deriving their own paths. Installers must never write their own `config.ini`.
8. **Helper auto-detection:** The remote script probes TCP port 8765 before launching the helper. If a helper is already running (manual launch), it connects without spawning a new one. On disconnect, it only sends `quit` if it launched the helper. **`_helper_lock` guards bookkeeping only and is never held across a blocking call**; `_helper_transition` serialises whole start/stop sequences. A port still busy right after our own teardown is our socket closing, not an external helper -- see `_helper_port_lingering`.
9. **macOS VoiceOver:** The helper uses `osascript` to call `tell application "VoiceOver" to output "..."`. The verb is `output`, **not** `speak`. Text must be escaped for AppleScript strings (escape `\` and `"`) -- see `_escape_applescript()` in `sr_helper.py`.

## Build Commands

### Windows
- **Build exe:** `python scripts/build.py` (requires `pip install pyinstaller`)
- **Deploy to Live:** `scripts\install.bat`
- **Deploy source only:** `scripts\install_from_source.bat`
- **Manual helper:** `scripts\start_helper.bat`

### macOS
- **Build binary:** `python scripts/build_mac.py` (requires `pip install pyinstaller`)
- **Deploy to Live:** `scripts/install_mac.sh`
- **Uninstall:** `scripts/uninstall_mac.sh`
- **Manual helper:** `scripts/start_helper_mac.sh`

## Key Paths

Both platforms install into the **Ableton User Library**'s `Remote Scripts/` folder. It needs no elevation, one copy serves every Live installation, and it survives Live updates.

### Windows
- **Default install location:** `%USERPROFILE%\Documents\Ableton\User Library\Remote Scripts\Move_SR_Bridge\`
- **Legacy location** (swept by the installers/uninstaller, and the last-resort target): `C:\ProgramData\Ableton\Live *\Resources\MIDI Remote Scripts\Move_SR_Bridge`
- **Live log:** `C:\Users\<user>\AppData\Roaming\Ableton\Live 12.x.x\Preferences\Log.txt`

### macOS
- **Default install location:** `~/Music/Ableton/User Library/Remote Scripts/Move_SR_Bridge/`
- **Legacy location** (swept by the installers/uninstaller, and the last-resort target): `/Applications/Ableton Live*.app/Contents/App-Resources/MIDI Remote Scripts/Move_SR_Bridge`
  (that bundle is code-signed with a hardened runtime, needs admin rights, and is wiped by every Live update)

### Resolving the actual location
Those are defaults only. The real path comes from Live's own `Library.cfg` (newest **by mtime** -- Live never deletes old preference folders, and version-number order is not "most recently used"), falling back to the platform default, then to creating it, then to Live itself. `MOVE_SR_USER_LIBRARY` overrides everything.

Three implementations that **must be kept in step** -- `scripts/lib/resolve_install_dir.sh`, `scripts/lib/ResolveInstallDir.ps1`, and the resolver functions in `Install Move-SR-Bridge.js`. See CLAUDE.md "Install Location Resolution" for the full contract, including the tie-break table they must all agree on. `tests/test_resolver.py` pins the shell one (the only of the three that runs on CI's Linux box); the other two still need checking by hand when the contract changes.

Two traps that produced silent divergences here: strip trailing slashes **before** joining rather than from the joined result, and in JXA split `doShellScript()` output on `\r` -- AppleScript translates newlines to carriage returns, so `split("\n")` yields one run-together element.

`ResolveInstallDir.ps1` is not optional tooling: every `.bat` invokes it and refuses to run without it, so it must stay in the Windows release zip's copy list in `build.yml`.

### Both platforms
- **Settings:** `~/.move_sr_bridge/config.ini`
- **Helper log:** `~/.move_sr_bridge/Move_SR_Bridge.log`

## Testing

`tests/` is a stdlib-`unittest` suite that runs without Live, hardware, or any dependency:

```
python3 -m unittest discover -s tests -v
```

See the `tests/` block under File Structure for what each file covers. `tests/stubs.py` fakes the `Move` package (including `display_util` -- without it `_content_types` stays empty and the formatting tests silently go vacuous) and redirects `HOME` to a temp directory, before the "already imported?" early return so a pre-imported package still gets the redirect. Nothing binds a real port.

**Check that a new test can actually fail**, by mutating the rule it claims to pin and confirming it goes red. Two tests in this suite were merged unable to fail at all -- one asserted `assertIn(x, (True, False))` on a boolean, the other exercised a `kill()` escalation through a fake object with no `kill()` method -- and a third had a fixture that made the wrong sort order pass.

Hardware behaviour still needs manual testing:

1. Deploy with `scripts/install_mac.sh` (macOS) or `scripts\install.bat` (Windows)
2. Open Live, select `Move_SR_Bridge` as Control Surface
3. Connect Move via USB
4. Verify speech and braille output with your screen reader
5. Check `~/.move_sr_bridge/Move_SR_Bridge.log` and Live's `Log.txt` for errors

## Supported Screen Readers

- **Windows (via Tolk):** NVDA, JAWS, Window-Eyes, ZoomText, System Access. Tolk auto-detects which one is running.
- **macOS (Tahoe 26+):** VoiceOver via AppleScript. Braille handled automatically by VoiceOver when active.
