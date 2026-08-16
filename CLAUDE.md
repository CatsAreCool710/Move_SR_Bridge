# Move-SR-Bridge

Screen reader support for Ableton Move. GPLv3, Copyright 2026 Jeremiah Ticket.

## Architecture

Two-process design forced by Ableton Live's embedded Python lacking `ctypes`:

1. **`Move_SR_Bridge/`** -- MIDI Remote Script package. Subclasses the stock `Move` control surface, monkey-patches `Display.display()` to intercept OLED text, sends it over TCP to the helper. Installed to the Ableton User Library's `Remote Scripts/` on both platforms (see Install Locations).
2. **`sr_helper.py`** -- Standalone process listening on `127.0.0.1:8765`. Cross-platform with two backends:
   - **Windows:** Loads `Tolk.dll` via `ctypes.cdll` to speak/braille via NVDA, JAWS, ZoomText, Window-Eyes, or System Access.
   - **macOS (Tahoe 26+):** Speaks via VoiceOver AppleScript (`osascript`). Braille handled automatically by VoiceOver.

The bridge module (`sr_bridge.py`) is the TCP socket client running inside Live. It uses only `socket` and `json` -- no `ctypes`.

## Key Constraints

- **Live's Python 3.11 has no `ctypes`** (`_ctypes` not compiled in). This is the fundamental reason for the two-process architecture. Do not try to call DLLs from `__init__.py` or `sr_bridge.py`.
- **Live's Python DOES have `socket`, `subprocess`, `json`** -- these are safe to use in the remote script.
- **Everything in `Move_SR_Bridge/` must stay compatible with Python 3.11** (Live's embedded interpreter). No 3.12+ syntax: no PEP 695 generics, no `type` statement. Anything valid in 3.11 is fine -- note f-string `=` debug syntax landed in 3.8 and is safe, contrary to an earlier note here.
- **Tolk uses cdecl** (`ctypes.cdll`), not stdcall (`ctypes.windll`). All string parameters are `c_wchar_p` (wide strings).
- **Tolk needs companion DLLs** alongside it: `nvdaControllerClient64.dll` for NVDA. JAWS/ZoomText use COM (no extra DLLs).
- **macOS requires VoiceOver AppleScript** to be enabled in VoiceOver Utility > General.
- **The package folder name** (`Move_SR_Bridge`) must be a valid Python identifier (no hyphens). This is what appears in Live's Control Surface dropdown.
- **GPLv3 license headers** required on all Python source files. Copyright holder: Jeremiah Ticket.
- **Braille TCP sends are skipped on macOS** -- VoiceOver handles braille automatically when it speaks. This is hardcoded in `sr_bridge.py`, not configurable.

## Configuration

User-editable settings live in `~/.move_sr_bridge/config.ini` (auto-created on first launch):

```ini
[debounce]
enabled = true      # Debounce display updates before speaking
delay_ms = 300      # Ms to wait after last update before speaking

[logging]
level = INFO        # DEBUG, INFO, WARNING, or ERROR

[speech]
step_toggles = true # Announce the step buttons as they are tapped
```

- `enabled`: When true, speech is delayed until no display updates occur for `delay_ms` milliseconds. Prevents rapid-fire speech during encoder turns.
- `delay_ms`: Lower values feel more responsive; higher values reduce chatter. Set to 0 to effectively disable.
- `level`: Verbosity written to `~/.move_sr_bridge/Move_SR_Bridge.log`, read by both the remote script and `sr_helper.py` from the same file. Diagnostic-only messages (every text sent to be spoken; Live-side track/scene selection changes) log at DEBUG and are hidden at the default INFO level. Set to DEBUG when diagnosing double-speech (see Diagnostics below).
- `step_toggles`: Announce the 16 step-sequencer buttons on tap (`"Step 5 on"` / `"Step 5 off"`), read from the button's own LED. See "Reading the lights".

**The submenu marker deliberately has no key, and that asymmetry is a decision, not an oversight.** It only enriches an announcement that already happens, by one word, on a screen the user is deliberately navigating. `step_toggles` gets a key because it is a new *class* of announcement on the device's busiest control. Do not "harmonise" the two.

### A bad config.ini must never cost the user the control surface

`__init__.py` reads this file at **module import**, inside Live, so anything that escapes makes Live skip the script and Move_SR_Bridge stops appearing in the Control Surface dropdown -- with no clue as to why. The whole read is therefore wrapped in `except Exception`, and both processes report the outcome as `_config_status`.

Three ways in, none of which `config.py`'s own `except configparser.Error` catches, and all of which shipped:

- **`UnicodeDecodeError` is not a `configparser.Error`.** It is a `ValueError`. Saving `config.ini` from Notepad in its default ANSI encoding with any accented character in it -- in a comment is enough -- makes `read(encoding="utf-8")` raise it straight through the handler.
- **`getattr(logging, name)` finds any module attribute.** `level = BASIC_FORMAT` returns a format *string*, and `setLevel()` raises `ValueError` on it. So the check is `isinstance(level, int)`, not a `None` test. `NOTSET` is rejected too: `setLevel(0)` means "inherit", which silently drops everything below WARNING -- the same invisible outcome by a different route.

- **`NoSectionError` on a key added after the user's `config.ini` was written.** `config.py` writes `_DEFAULT_CONFIG` **only when the file does not exist**, so everyone upgrading keeps a file with no `[speech]` section. `_DEFAULTS`/`read_dict` covers that in practice, but a bare `_cfg.getboolean("speech", ...)` raises `NoSectionError`, which is a `configparser.Error` and **not** a `ValueError` -- so it escapes the `except ValueError` beside it, escapes `_install_display_hook`, is caught by `_try_install_hook`, and costs the user the whole display hook. **Rule: every config read uses `fallback=`.** The existing `[debounce]` reads still do not and would break the same way if their section went missing; retrofitting them is a separate change.

`tests/test_config.py` covers the first two, each in its own interpreter, since the config is read once at import and cached. `tests/test_display_hook.py` covers the third by installing the hook against a config with no `[speech]` section at all.

## File Layout

```
Move_SR_Bridge/          The MIDI Remote Script package (deployed to Live)
  __init__.py            Entry point -- subclasses Move, hooks Display.display()
  config.py              Config loader + STATE_DIR/CONFIG_FILE/LOG_PATH
  version.py             __version__ -- single source, asserted against the tag by CI
  sr_bridge.py           TCP client (socket+json only, runs in Live's Python)
  sr_helper.py           TCP server + screen reader bridge (cross-platform)
  sr_helper.exe          Windows: PyInstaller build (Tolk backend)
  sr_helper_mac          macOS: PyInstaller build (VoiceOver backend)
  Tolk.dll               Windows: screen reader abstraction (64-bit, cdecl)
  nvdaControllerClient64.dll  Windows: NVDA companion DLL (loaded by Tolk)

scripts/
  build.py               PyInstaller build script (Windows)
  build_mac.py           PyInstaller build script (macOS)
  bump_version.py        Reads/bumps version.py -- the only writer of the
                          version string.  --show/--set/--dev/--release.
  smoke_helper.py        Runs a BUILT helper against a real config.ini;
                          both release build jobs and release_mac.sh
                          gate on it. Asserts [frozen] and the version
                          too, so it cannot pass against the .py source
                          -- the packaging is the whole subject.
  install.bat            Batch installer for Windows
  install_from_source.bat  Windows: installs without .exe
  uninstall.bat          Batch uninstaller (Windows)
  start_helper.bat       Manual helper launcher (Windows)
  install_mac.sh         Shell installer for macOS (User Library)
  uninstall_mac.sh       Shell uninstaller for macOS
  start_helper_mac.sh    Manual helper launcher (macOS)
  release_mac.sh         Local macOS release builder (helper + .app + zip)
  lib/
    resolve_install_dir.sh   Install-location resolver, sourced by the
                              macOS shell scripts
    ResolveInstallDir.ps1    Install-location resolver, invoked by every
                              .bat (batch cannot parse XML). Ships in the
                              Windows release zip -- the .bat files refuse
                              to run without it.
  installer/
    mac/
      Install Move-SR-Bridge.js  JXA graphical installer (osacompile)
      build.sh                   Builds the .app installer bundle; embeds
                                  the package + LICENSE inside
                                  Contents/Resources/ (requires
                                  sr_helper_mac already built)

tools/
  speech_history_logger.py  macOS-only debug tool (opt-in, manual): polls
                             VoiceOver's "content of the last phrase" via
                             AppleScript to log every utterance VoiceOver
                             speaks -- including Live's own native
                             announcements, which Move_SR_Bridge cannot
                             see. Not installed to Live, not started by
                             sr_helper.py, not gated by config.ini.
```

## Build & Deploy

### Windows
- Build exe: `python scripts/build.py` (requires `pip install pyinstaller`)
- Deploy to Live: `scripts\install.bat` (resolves the User Library, no version prompt -- one install serves every Live)
- Uninstall: `scripts\uninstall.bat` (sweeps every location, including legacy `C:\ProgramData` copies)
- Install path: the User Library's `Remote Scripts\` (see Install Locations)
- Live log: `C:\Users\<you>\AppData\Roaming\Ableton\Live 12.x.x\Preferences\Log.txt`

### macOS (Tahoe 26+)
- Build binary: `python scripts/build_mac.py` (requires `pip install pyinstaller`). Produces a single-arch binary matching the local machine.
- Build the self-contained installer: `scripts/installer/mac/build.sh` (requires `sr_helper_mac` already built). Runs `osacompile`, then copies the whole `Move_SR_Bridge/` directory (minus `__pycache__`, `.DS_Store`, `*.exe`, `*.dll`) and `LICENSE` into `Install Move-SR-Bridge.app/Contents/Resources/` -- the `.app` needs no sibling folder and is the only file in the release zip. It copies the directory rather than naming members **on purpose**: this was the last hand-maintained file list in the repo, and a hand-maintained list is how a new module ships missing and fails as an `ImportError` inside Live with nothing wrong on the installer side. A post-copy check asserts the six files Live actually needs are present, and the build refuses to run when `sr_helper_mac` is older than `version.py` (the frozen binary bakes in its own copy, so a stale one makes the two processes report different versions into the same log).
- Deploy to Live (GUI, recommended): double-click `Install Move-SR-Bridge.app` -- it has both Install and Uninstall built in.
- Deploy to Live (shell, from source): `scripts/install_mac.sh`
- Uninstall (shell, from source): `scripts/uninstall_mac.sh`
- Official releases (`.github/workflows/build.yml`) build `sr_helper_mac` as a universal2 (arm64 + x86_64) binary: install a universal2 python.org interpreter, build once under `arch -arm64` and once under `arch -x86_64`, then `lipo -create` the two into one fat binary before running `build.sh`.
- The release `.app` is **not signed or notarized** (no Apple Developer ID). Gatekeeper blocks it on first launch; the README documents both the `xattr -d com.apple.quarantine` and the System Settings > Privacy & Security route. Deliberate won't-fix.
- VoiceOver setup: Enable "Allow VoiceOver to be controlled with AppleScript" in VoiceOver Utility > General

## Install Locations

**Both platforms install to the Ableton User Library's `Remote Scripts/`.** Defaults only -- the actual path is resolved, see below.

| What | Windows | macOS |
|------|---------|-------|
| Package | `%USERPROFILE%\Documents\Ableton\User Library\Remote Scripts\Move_SR_Bridge\` | `~/Music/Ableton/User Library/Remote Scripts/Move_SR_Bridge/` |
| Settings | `%USERPROFILE%\.move_sr_bridge\config.ini` | `~/.move_sr_bridge/config.ini` |
| Helper log | `%USERPROFILE%\.move_sr_bridge\Move_SR_Bridge.log` | `~/.move_sr_bridge/Move_SR_Bridge.log` |

The User Library needs no elevation, one copy serves every Live installation, and it survives Live updates. The alternatives are all three of the opposite: macOS app bundles are code-signed with a hardened runtime (`flags=0x10000`), so writing into one breaks the signature seal; `C:\ProgramData\Ableton\Live *\Resources\MIDI Remote Scripts` needs Administrator and is per-Live-version.

### Install Location Resolution

Three implementations, one algorithm -- **keep them in step**:

| Where | Used by |
|-------|---------|
| `scripts/lib/resolve_install_dir.sh` | `install_mac.sh`, `uninstall_mac.sh`, `start_helper_mac.sh` (sourced) |
| `scripts/lib/ResolveInstallDir.ps1` | all four `.bat` files (invoked; batch cannot parse XML) |
| `resolveRemoteScriptsDir()` etc. in `Install Move-SR-Bridge.js` | the JXA graphical installer |

Order:

1. **`MOVE_SR_USER_LIBRARY`** -- wins outright. An override that cannot be used is a hard error, never a reason to fall through.
2. **Live's `Library.cfg`** -- plain XML at `~/Library/Preferences/Ableton/Live <ver>/Library.cfg` (macOS) or `%APPDATA%\Ableton\Live <ver>\Preferences\Library.cfg` (Windows; note the extra `Preferences\` level). The library is `<ProjectPath>/<ProjectName>` inside the `<UserLibrary>` block. Schema confirmed identical across 12.3.6 and 12.4.3.
3. **The platform-default User Library.** Windows uses `[Environment]::GetFolderPath('MyDocuments')`, *not* `%USERPROFILE%\Documents` -- OneDrive Known Folder redirection is common and would otherwise point at an empty stub. This is why `Library.cfg` matters more on Windows than on macOS.
4. **Create the default User Library** if none exists. Live picks it up on next start.
5. **Inside Live itself** -- last resort, warned about loudly in all three implementations. macOS: the app bundle. Windows: `C:\ProgramData\Ableton\Live *\Resources\MIDI Remote Scripts`.

This is Ableton's documented method, not a workaround: per [Installing third-party remote scripts](https://help.ableton.com/hc/en-us/articles/209072009-Installing-third-party-remote-scripts), the User Library `Remote Scripts` folder is supported since **Live 10.1.13**, on both platforms, and scripts there survive Live upgrades. `<prefs>/User Remote Scripts/` is the older per-Live-version location that this superseded.

### Tie-breaks the three implementations must agree on

Divergences here are invisible until someone hits the edge case, so each is written down:

| Rule | Why |
|------|-----|
| Newest `Library.cfg` **by mtime**, never by version number | Live never deletes old preference folders, and `12.4.5b8` sorts above the `12.4.3` that is actually running. |
| **First** `<LibraryProject>` in `<UserLibrary>`, not last | PowerShell/JXA use lazy regex (first); shell `sed 's|.*<Tag...|'` is greedy and returned the **last**. sed has no lazy quantifier, so the shell puts one tag per line and takes `head -1`. |
| Newest Live app/program-data dir **by mtime**, never alphabetical | `"Ableton Live 9 Trial"` sorts *after* `"Ableton Live 11"` as a string. The JXA installer used to sort by name and pick the last entry, so it chose a different Live than the shell installer on the same machine. |
| Strip trailing slashes **before** joining, on `MOVE_SR_USER_LIBRARY` as well as on `ProjectPath` | Both are outside-controlled data that may carry one. Stripping the *joined* result instead leaves the slash in the middle (`/lib//User Library`) -- that resolves fine as a path but is not byte-identical to what the other two build, and the "is this the copy I just installed?" test is a string comparison. All three shipped this broken, each in its own way: the JXA stripped after joining, the shell never normalised the override at all, and PowerShell leaned on `Join-Path`, which absorbs *one* trailing separator but leaves a doubled one in place. PowerShell needs its own `Remove-TrailingSeparators` -- `Join-Path` is not sufficient. |
| Flatten line breaks on **`[\r\n]`**, not `\r?\n` | A lone CR is a line break too. The shell's `tr -d '\n\r'` always handled it; the PowerShell and JXA regexes did not, so a CR-only file left the whole document on one "line" for two of the three parsers. |
| Last resort must verify the `MIDI Remote Scripts` subfolder exists, not just the app/dir | Otherwise the installer `mkdir -p`s a path Live may never scan, or aborts on a permission error with no friendly message. |
| The Live-app matcher is `Ableton Live*.app` -- no space, no required suffix | The JXA used `/^Ableton Live .+\.app$/`, which needs a space and a suffix after "Live". A plain `Ableton Live.app` was therefore a candidate for the shell installer and invisible to the graphical one, so a copy installed by one could never be swept or uninstalled by the other. |

In shell, always `ls -t ... | head -1` -- never a `for` loop over command substitution, since these paths contain spaces and get word-split. This applies to the *candidate list* as much as the resolver: `msb_all_candidate_dirs` used a bare glob (alphabetical) while `msb_resolve_remote_scripts` used mtime, so one file disagreed with itself about which Live came first.

**`~/.move_sr_bridge/install_location`** is a sixth candidate, read by all three. Only the graphical installer can produce it: its "choose a folder" branch (reached when the default User Library cannot be created) can put the package somewhere no resolver would ever derive. Unrecorded, that copy is invisible to every uninstaller and to the next install's sweep, so it sits on Live's search path shadowing the new package indefinitely.

**In JXA, split `doShellScript()` output on `\r`, not `\n`.** AppleScript's `do shell script` translates every newline in its result to a carriage return, so `split("\n")` returns *one* element containing every line run together. This is silent: `liveAppsNewestFirst()` looked correct and returned a single bogus path, every `indexOf()` in `detectLiveApps()` scored `-1`, the comparator returned 0 for every pair, and the mtime sort became a no-op that left exactly the alphabetical order it exists to replace. Use `split(/[\r\n]+/)`. Single-line output is safe either way, since `.trim()` removes a trailing `\r`.

`tests/test_resolver.py` pins the parsing and normalisation rules above against the shell implementation -- the only one of the three that runs on CI's Linux box. It is not a substitute for checking the other two by hand when this contract changes.

After installing, all three **sweep every other candidate location**, since two same-named packages on Live's search path is ambiguous and the stale one keeps shadowing the new one. The uninstallers use the same candidate list.

### Installs are staged, never in place

`install_mac.sh` and the JXA installer both copy to a sibling `.new.$$`, then swap: move the old copy aside, move the new one in, and only then delete the old. Both used to be `rm -rf "$dest" && cp -R ...`, which on the last-resort path (inside Live's root-owned app bundle) could delete a working install and then fail to replace it. The shell version also had no `sudo` fallback on the install itself -- only on the sweep 30 lines later -- so it aborted under `set -e` on a bare "Permission denied" having already removed the old copy.

`<prefs>/User Remote Scripts/` is also a documented Control Surface location, but it is per-Live-version so it does not survive updates the way the User Library does. Deliberately not in the chain.

**`config.py` owns `STATE_DIR` / `CONFIG_FILE` / `LOG_PATH`** and is the only place the default config is written. `__init__.py` and `sr_helper.py` both import those constants rather than deriving their own paths, and each carries a fallback copy used *only* when `config.py` cannot be imported at all. Installers must never write their own `config.ini` -- an installer-side copy drifted out of sync once already (missing the whole `[logging]` section).

## Protocol

Newline-delimited JSON over TCP to `127.0.0.1:8765`:

```json
{"cmd": "speak", "text": "..."}
{"cmd": "braille", "text": "..."}
{"cmd": "dialog", "text": "..."}
{"cmd": "cancel"}
{"cmd": "quit"}
```

`dialog` is `speak` plus a platform policy, and exists as its own command because that policy needs OS-level focus state the remote script must not go looking for. See "Modal dialogs".

## Diagnostics

Ableton Live has its own native VoiceOver narration (e.g. on track/scene
selection change) that is completely independent of Move_SR_Bridge's OLED
interception, and can overlap/double up with it. To diagnose this:

1. Set `level = DEBUG` in `~/.move_sr_bridge/config.ini`. This surfaces
   three event streams in `Move_SR_Bridge.log`:
   - `screen [<decision>] <text>` -- **every** display update the hook saw
     and what it did with it: `main`, `overlay`, `notification`, `dialog`,
     `unchanged`, `unchanged/overlay`, `dialog-repeat`, `dialog-closed`,
     `empty`. Suppression is most of what the hook does, so without this
     "Move_SR_Bridge ignored that screen" and "Move_SR_Bridge never saw
     that screen" were indistinguishable.
   - `step Step 5 on` -- a step-button toggle. It does **not** also produce
     a `screen [...]` line: it never went through `_consider_announcing`,
     because a step toggle is not a display update. Same trap as the
     `dialog` line below, and recorded for the same reason. The install
     line also reports the outcome:
     `Display hook installed (debounce=..., step_toggles=on|disabled by
     config|no note editor|failed)`.
   - `Speaking: ...` -- every text the helper was asked to speak.
   - `dialog announced, frontmost app is ...` / `dialog suppressed, Live is
     frontmost ...` -- the helper's decision for a `cmd: "dialog"`. Note a
     dialog does **not** also produce a `Speaking:` line: `sr_dialog()`
     calls `sr_speak()` directly rather than going through the `speak`
     command handler, so these two lines are the whole record for it.
   - `current_dialog_message is empty` / `... has no Application.
     current_dialog_message` / `... raised` -- why the announcement fell
     back to the Move's generic screen text.
   - `Live selected track/scene changed -> ...` / `Live track/scene list
     changed` -- Live's own focus state, independent of the display hook.
2. On macOS, run `python3 tools/speech_history_logger.py` alongside the
   helper. It produces `tools/speech_history.log` -- everything VoiceOver
   actually spoke, whether triggered by Move_SR_Bridge or by Live itself.

There is no automatic correlation or source tagging across these logs --
compare timestamps by eye.

`_log_failure` site strings, so they are greppable: `Display hook`,
`Announcement`, `Step hook install`, `Step release wrapper`,
`Step notes listener`, `Step toggle announcement`, `Step hook teardown`.

**Check `Log level:` first.** The helper logs
`Log level: DEBUG (config: ok) [frozen]` at startup. If it says
`config: config.py unavailable (...)` then `config.ini` was never read and
every `[DEBUG]` line is missing -- which looks exactly like "the hook is
not running", because speech keeps working while the whole trace vanishes.
That shipped: `sr_helper.py` imports `config.py` at runtime from its
install directory (deliberately -- one config module, not two copies),
which is invisible to PyInstaller's static analysis, so `configparser` was
never bundled and **every frozen release silently ignored `config.ini`**.
Both build scripts now pass `--hidden-import configparser`, and
`scripts/smoke_helper.py` runs the built binary against a real config in
CI and fails the release if it does not take effect. Any future import
that only happens at runtime needs the same treatment.

### Double-speech mitigation

Confirmed via the above: Live's own native narration and Move_SR_Bridge's
OLED-driven speech both announce the track/scene name on selection change,
about `delay_ms` apart. To reduce this, **`_consider_announcing()`** in
`__init__.py` checks the `name` half of the announcement (e.g. the
`"2-MIDI"` of `"2-MIDI: No Device"`) against Live's currently selected
track/scene name (read live via `_get_live_selected_names()`, not the
diagnostic listeners above) and speaks only the value (`"No Device"`) when
the name matches -- Live is expected to have just said the name itself.

**Not in `_format_content()`**, which never reads Live's state and must
stay that way: its purity is what lets the formatting tests call it with a
content object alone (see Speech Normalisation below). It only *reports*
the `name`/`value` split; the comparison is the caller's.

The automation marker survives this. `_AUTOMATION_CHAR` rides on the name,
so dropping the name would drop it too, and an automated parameter on the
selected track would read as a bare `"0 dB"` -- undoing the entire point of
handling the glyph. `_Announcement.is_automated` carries the fact across,
and the value is spoken as `"automated, 0 dB"`.

This is a heuristic, not a guarantee: it can't confirm Live's narration
actually fired, and a device/parameter name that happens to match the
current track/scene name would also get stripped.

## Speech Normalisation

`_format_content(content, active_parameter=None)` returns an `_Announcement(text, name, value, is_notification)` namedtuple, or `None`. `text` is the full announcement and the change-detection key; `name`/`value` are the halves of a name/value pair reported separately so the caller never slices `text` (an earlier version used `text[len(name)+2:]`, which broke the moment anything was prefixed to the name).

`active_parameter` is optional and exists solely for the master-volume case below -- the function is otherwise pure, which is what keeps the formatting tests able to call it with a content object alone.

Three normalisation steps sit between Live's OLED text and speech, all derived from reading Live's own `Move/display_util.py` and `Move/display.py`:

- **`_AUTOMATION_CHAR` (U+E044)** -- Live prefixes an automated parameter's name with this Private Use Area glyph from the Move's icon font. Screen readers have no pronunciation for it, so the automation state was lost entirely. It becomes the word "automated" in `text`, and is kept *out* of `name` so the double-speech track/scene match still works.
- **Other PUA codepoints** are stripped (`_is_private_use`). They are always icon-font glyphs with no spoken form. Scope is the BMP block `U+E000`–`U+F8FF` only, not the plane 15/16 supplementary areas -- Move's icon font lives in the BMP block, and widening it has no known case behind it.
- **`_ABBREVIATIONS`** expands display-width abbreviations that are unreadable aloud. Currently one entry (`Autmtn.` → `Automation`) -- the only genuine case across all 46 stock Move modules. Do **not** add conventional audio shorthand (`Freq`, `LFO`, `Env`): expanding those would diverge from what Live's own UI calls the same control.

**`_spoken()` collapses whitespace unconditionally, and that is load-bearing.** Move builds its `NotificationView` with `supports_new_line=True`, so `NotificationView.render` deliberately does *not* flatten the `\n` in a notification template -- `'Notes\ndeleted'` arrives as a **single `lines` entry containing a real newline**, which Live's `break_line` splits into two drawn rows at draw time. The newline is intrinsic to the vocabulary, not an edge case: `display_util.on_off_to_title_case` exists purely to rewrite `'\non'` → `'\nOn'`. Collapsing only when the automation glyph happened to be present -- which shipped -- sent a raw newline to the screen reader and the braille display on **every** notification. It does not crash (AppleScript accepts a literal newline in a `-e` string), which is why it went unnoticed. Note the notification branch's `" ".join(text_lines)` is a **no-op on Move**: notifications are always one element, and `_spoken()` is what actually flattens them.

**`_join_lines()` names the one real continuation instead of guessing it.** It joins with `", "` unless the pair is in `_CONTINUATION_PAIRS`, which holds exactly one entry: `("Press wheel to", "shut down")`. Reading every `Content(...)` construction in `Move/display.py` shows that is the *only* sentence Live authors across two lines -- everything else that arrives as two lines is a name/value pair or a list. The previous rule (next line starts lowercase) served that one screen while mis-joining every genuinely distinct field starting lowercase, so a lowercase track, device, bank or menu name read as `"1-Audio bass"` instead of `"1-Audio, bass"`.

**`_CONTINUATION_PAIRS` and `_URGENT_TEXTS` are coupled**: the pair must join to exactly the urgent string, or the shutdown prompt silently stops bypassing the debounce. `tests/test_format_content.py` asserts the join result is a member of `_URGENT_TEXTS` rather than leaving it to a comment.

**`_parameter_value_text()` mirrors Live's own rounding.** `display_util.parameter_value_string` is `str(parameter)` plus `'{} dB'.format(round(float(...), 1))` for dB values, so bare `str()` announced more precision than Live ever draws for that parameter anywhere.

**The submenu marker.** Live sets `MenuItem.cursor_char` to `'>'` when an item has sub-items and `'-'` otherwise (`__post_init__`), and `_do_display` passes it to `draw_vertical_list(lines, list_cursor_char, list_index)` -- so it is genuinely drawn beside the cursor, and announcing it is parity rather than embellishment. It describes the **selected row only** (Live sends one char per content), so it is appended on the selected-item arm and nowhere else -- never on the whole-list fallback, which fires precisely when the selected row is unknown. Every Move menu is a real mix: Settings has `Brightness` (`>`, opening the LED/pad brightness levels) beside `Standalone` (`-`, which fires `switch_to_standalone` immediately). `>` covers both a nested list and a `simple_content` value picker, deliberately -- Live draws one glyph for both.

**`list_index` indexes the position-aligned line list, never the filtered one.** `_format_content()` builds two views: `aligned_lines` keeps one entry per entry of `content.lines` (empties preserved), and `text_lines` drops the empties for whole-screen reads. Live's `list_index` refers to `content.lines`, so indexing the filtered list shifted every entry after a blank or icon-only line and announced the **wrong menu item** -- confidently, which is worse than silence for a screen-reader user.

## Helper Process Lifecycle

Two locks, deliberately separate:

- **`_helper_lock`** guards `_helper_proc` and `_active_instances` and nothing else. It is **never held across a blocking call** -- Live drives connect/disconnect on its control surface callback thread, so a lock held across `Popen()` or a multi-second teardown stalls Live's UI behind it.
- **`_helper_transition`** serialises a whole start or stop sequence, so the two cannot interleave. Held for seconds by design.

**`_helper_port_lingering`** closes a real hole: `sr_helper.py`'s accept loop can keep port 8765 open for ~1s after the process exits. A `_start_helper()` probing during that window read "port busy" as "somebody else's helper", recorded no ownership, and never launched one -- speech dead for the rest of the session. `_stop_helper()` now records that its socket outlived its patience, and the next start waits (up to ~2s) instead of concluding the helper is external. It is guarded by **`_helper_transition`**, which both sides hold while touching it -- *not* by `_helper_lock`, whose remit is the two variables above and nothing else.

Teardown escalates `quit` -> `terminate()` -> **`kill()`**. Without the last step a helper blocked in `subprocess.run(osascript)` (which ignores SIGTERM) outlives Live and holds the port against the next session. `tests/test_helper_lifecycle.py` drives the last rung with a fake process that ignores `terminate()`; the fake used to have no `kill()` at all, so `proc.kill()` raised `AttributeError`, the catch-all swallowed it, and the escalation was never actually exercised by anything.

`disconnect()` wraps `super().disconnect()` in try/except with `_stop_helper()` in a `finally`. If Live's own teardown raises and this is unguarded, the registration is orphaned and no later instance can ever shut the helper down. The display-hook teardown that runs just before it is guarded for the same reason.

**The display hook is uninstalled on disconnect**, restoring Live's own `display.display`. While the patch is in place any frame Live renders after teardown re-enters `_consider_announcing`, can start a fresh timer, and can speak after the farewell -- which is exactly what cancelling the pending announcement is meant to prevent. It also keeps the closure, and through it the control surface, reachable for as long as Live's display object lives.

## Debounce Scheduling

`_pending_text` is a single-slot mailbox, so every timer carries the **generation** it was scheduled for and speaks only if `_debounce_gen` still matches. `cancel()` cannot stop a timer that has already begun running; without the generation check such a timer would take the *newer* update's text out of the mailbox and speak it immediately, collapsing the debounce window the newer timer exists to enforce. `_cancel_pending()` bumps the generation for the same reason.

**`_cancel_pending(wait=False)` only joins the timer when asked, and only teardown asks.** The generation bump alone is enough to keep a stale timer quiet; the join exists so `disconnect()` can be sure nothing lands after "Move disconnected" and so the timer stops holding the closure -- and the control surface -- alive. But the redraw path calls this too (urgent announcements, and every distinct dialog screen), and that runs on Live's display callback *ahead of* `original_display_method(content)`. A join there stalls the OLED for up to a second while a timer finishes a socket write, worst during a modal dialog, which is also what calls it most.

`_do_announce()` swallows and logs exceptions. It runs on the timer thread, where an escaping exception kills the thread silently -- inside Live stderr goes nowhere, so the failure would never reach the log.

Both this and `_intercepted_display()`'s catch-all report through **`_log_failure()`**, which logs the first occurrence per site at ERROR and the rest at DEBUG. They used to log at DEBUG unconditionally, which meant that at the default `level = INFO` a hook throwing on every frame produced a completely silent, completely dead bridge -- the exact failure the catch-all exists to survive, made invisible by the way it reported. Logging every occurrence at ERROR is the other failure: Live redraws several times a second, so one repeating fault would bury the log.

## Overlays and Change Detection

The hook tracks `last_main` (last **main** screen) separately from `last_announced` (last thing spoken). An **overlay** is a screen Live paints over the main view and then takes away again, leaving the view underneath unchanged. Overlays are announced but never become `last_main` -- otherwise the screen underneath is announced a second time the moment the overlay clears, which is pure noise for a screen-reader user.

Three kinds of overlay, and this taxonomy is **Live's own**, not ours. `Move/display.py`:

```python
def in_critical_display_state(state):
    return (state.active_parameter.parameter is not None
            or state.firmware.shut_down_state != ShutDownState.none
            or state.dialog.any_dialog_open)
```

| Overlay | How we detect it |
|---|---|
| **Notification** | `NotificationContent`. Live has 15 categories and raises them constantly -- untracked, this roughly doubled speech volume. |
| **Touched encoder** | Live's own `parameter_view` is gated on `component_map['Active_Parameter'].parameter is not None`. `ControlSurfaceMappingMixin.__init__` sets `component_map`; `Active_Parameter` is the key in `ableton/v3/control_surface/component_map.py`. **We read the same value a different way -- see below.** |

**Do not "simplify" the active-parameter read back to `component_map[key]`.** `_get_active_parameter()` uses `dict.get(component_map, 'Active_Parameter')`, going through `dict` explicitly rather than the subscript. Live's `ComponentMap` subclasses `dict` and its `__getitem__` *lazily constructs* an absent component (with `is_enabled=False`) and caches it -- a side effect on Live's control surface, from a function that runs on every display update. The subscript form is what Live's own code uses because Live *wants* that construction; we only want to look.
| **Shutdown prompt** | `_URGENT_TEXTS`, because Live drives it from firmware state this process cannot reach. If Live rewords it the prompt is merely debounced like anything else. |

Confirmed from the log before the fix: touching the volume encoder produced `Speaking: Volume` and then, 1.3 s later with nothing changed, `Speaking: No Device`.

### Modal dialogs

`_dialog_is_open()` reads `Live.Application.get_application().open_dialog_count`. That is exactly what Live reads -- `Move/dialog.py` is `any_dialog_open = application.open_dialog_count > 0`, updated by a listener on `open_dialog_count`.

Because `any_dialog_open` is a *cached* flag on the Move side, it lags the count Live changes, so `main_view` flaps between the dialog message and the view underneath while the dialog is still up. Observed:

```
Speaking: Live is showing a dialog that needs your attention.
Speaking: No Device                                            <- dialog still open
Speaking: Live is showing a dialog that needs your attention.
```

So a dialog is handled as an **episode**, not per-screen: while `open_dialog_count > 0`, announce each **distinct** screen once, then stay quiet about repeats until the count returns to 0.

Two sets, not one -- `screens` (what Live rendered) and `spoken` (what we said). Both are needed: several different screens resolve to the *same* `current_dialog_message`, so deduping only on the spoken text would still re-read it per screen, and deduping only on the screen would announce the same sentence twice. The screen check also comes first deliberately, because it is what keeps `_get_dialog_message()` off the redraw path -- Live redraws ~5x/second for the entire time a dialog is open (35 s in one measured log), and resolving the text per redraw meant a Live API read at that rate on Live's own callback thread. Per distinct screen it is one or two reads for the whole episode.

Deliberately *not* "announce only the first screen of the episode". The flap can present the stale main view before the dialog message, and first-wins would then spend the episode's one announcement on the wrong screen and never tell the user there is a dialog at all -- which is the entire point of the message. Per-screen dedupe costs at worst one extra "No Device" ahead of the message and can never lose it.

`last_main` is untouched for the whole episode, so dismissing the dialog does not re-announce the screen the user was already on -- but a screen the dialog actually *changed* still is.

**What gets said.** `Application.current_dialog_message` ("Text of the last dialog that appeared; Empty if all dialogs just disappeared") is preferred over the Move's own screen, which only ever says the generic *"Live is showing a dialog that needs your attention."* Read defensively via `_get_dialog_message()`, falling back to the OLED text.

The property **does exist in Live 12** -- it is registered in `_MxDCore/LomTypes.pyc` alongside `open_dialog_count`, `current_dialog_button_count` and `press_current_dialog_button`. But it is **not populated for every dialog**: observed empty for the macOS "Save changes before closing?" sheet. Live appears to fill it for its own message boxes (the ones `press_current_dialog_button` drives, as used by `pushbase/message_box_component.py`), not for native OS panels. So the generic fallback is a normal outcome, not a failure -- `_get_dialog_message()` logs at DEBUG which of *absent property* / *empty* / *raised* happened, because all three look identical from the announcement alone.

`_get_dialog_message()` uses `getattr(app, name, sentinel)` inside a `try`, **never `hasattr`**: `hasattr` swallows only `AttributeError`, so a property raising anything else escapes it -- and this function runs while a modal dialog has Live's UI blocked, where an escaping exception is the worst possible outcome. A test covers exactly that.

**When it gets said (macOS).** Only while Live is **not** the frontmost application. Measured from real logs: with Live frontmost, the announcement went out 1 ms after the dialog opened and never reached VoiceOver, because VoiceOver's own focus announcement for the same dialog preempted it 261 ms later. That race cannot be won -- VoiceOver's AppleScript `output` command takes only a spelling type, with no queue or priority parameter (checked against `VoiceOver.app`'s `sdef`), and `accessibilitySpeechQueueAnnouncement` is an NSAccessibility key for the *focused* app, which the helper is not.

So the helper does not compete. With Live frontmost, VoiceOver already says more than we can (title *and* buttons). With Live in the background VoiceOver says nothing at all, and a user with hands on the Move has no other way to learn why the device stopped responding -- that is the case worth covering.

Frontmost detection uses **`lsappinfo front`** plus `lsappinfo info -only bundleid`, and both Live 12 Suite and Live 12 Beta report `com.ableton.live`. `lsappinfo` is Launch Services' own CLI: ~12 ms, and unlike `System Events` it needs no Accessibility permission, so it cannot raise a TCC prompt at the worst possible moment. It fails open -- an unknown frontmost app still gets the announcement, because being too talkative beats being silently broken.

**Windows keeps the unconditional behaviour.** The same reasoning probably applies to NVDA and JAWS, but this project has no Windows machine to measure it on, and guessing would risk silencing a message that currently works.

`_is_urgent()` still bypasses the debounce and cancels anything queued, for the shutdown prompt and dialogs.

## Reading the lights

The first feature that announces something Live never rendered as text.

**Two different controls, and only one is in scope.** `Step_Buttons` is 16 buttons on MIDI notes **16–31**, the bottom row. `Pads` is a separate element built from `create_matrix_identifiers(68, 100, 8, flip_rows=True)` -- 32 pads on notes **68–99**, 4×8, deliberately out of scope. The script models the step buttons as a 4×4 matrix internally, but `step_buttons_raw[n]` is the *n*th button left to right and `note = 16 + n`, so numbering them 1–16 along the row matches what the user's hand is on.

**The light is the source of truth.** `NoteEditorComponent._get_color_for_step(index, visible_steps)` returns the skin name driving the LED, as a pure read (`_visible_steps()` builds a fresh dict, `filter_notes` filters a list; no Live API call, no mutation):

| Name | We say |
|---|---|
| `NoteEditor.StepFilled` | on |
| `NoteEditor.StepMuted` | on -- muted counts as on, deliberately |
| `NoteEditor.StepEmpty` | off |
| `StepDisabled`, `NoClip` | nothing |
| `StepTied`, `StepPartiallyTied` | nothing -- produced **only** by `show_duration_of_active_steps`, the hold-to-inspect gesture |
| `Playhead` | nothing -- and only when `StepColorManager.clip` is unset; the real playhead LED is drawn by `PlayheadComponent` (`playhead_notes = range(16, 32)`), which bypasses this function |

`_STEP_LIGHT_ON`/`_STEP_LIGHT_OFF` are **two frozensets, not one plus a default**. With a default, a skin name Ableton adds later would be announced as a confident "off".

**The staleness rule, which dictates the whole shape.** `_get_color_for_step` reads `self._clip_notes`, a cache refreshed by `__on_clip_notes_changed` (`@listens('notes')` on the clip). So the light must be sampled **before** the toggle and read again **on the `clip_notes` event** -- never synchronously after the original, where `_clip_notes` has not been refreshed and the answer is the *old* state, confidently backwards.

**The tap gates it; the light reports it.** Diffing all 16 lights on every `clip_notes` would also fire for Live-UI edits, undo and every note captured while recording -- far too chatty. So `_on_release_step` is wrapped to arm a record (index + before-light), and the `clip_notes` listener reads the light again and announces only if it changed.

Consequences, each the reason for a line in `_install_step_hooks`:

- **The diff is self-validating**, so *none* of `_on_release_step`'s short-circuits is mirrored and `_add_note_in_step`/`_delete_notes_in_step` need no wrapper. A velocity edit, a duration hold, or a tap with no clip leaves the light unchanged and says nothing.
- **There is deliberately no `finally`** clearing the record. Adding one is the obvious tidy-up and it silently disables the feature wherever Live fires the LOM listener *after* `_on_release_step` returns. A test covers the deferred case.
- **The record is consumed before announcing**, so a re-entrant `clip_notes` cannot announce twice.
- **The original call is the last statement and unguarded**, so nothing of ours can stop Live editing the clip, and its exception propagates untouched.

**Restore discipline.** Instance attribute only, **never the class** -- a class patch outlives every instance and every disconnect. Unwrap with `delattr`, **never `setattr(original)`**: the original is a *bound method* holding a strong reference to the editor, so writing it into the instance `__dict__` is not a restore -- it shadows the class method permanently and makes any later class-level patch invisible. That difference is behaviourally invisible, so the test asserts on `vars(note_editor)`. The listener is removed **first**, being the one thing that could still speak.

**Tap and hold are mutually exclusive by Live's own gesture split**, which is why no mode flag is needed. `_on_pad_pressed` pushes a `RelativeInternalParameter(name='Velocity')` into `Active_Parameter`, so a press already announces `"Velocity: N"` through the display hook; a short tap reaches `_on_release_step` via `released_immediately` and preempts it with `_speak_now`, while a long hold goes to `released_delayed` with `can_add_or_remove=False`, toggles nothing, and keeps the velocity overlay.

## Researching Live's Behaviour

Live ships the Move remote scripts as `.pyc` only (Python 3.11, magic `0x0da7`). To read them:

```
uv python install 3.11
uv run --python 3.11 --no-project python -c "
import marshal, dis
f = open('/Applications/Ableton Live 12 Suite.app/Contents/App-Resources/MIDI Remote Scripts/Move/display.pyc','rb')
f.read(16); dis.dis(marshal.load(f))"
```

This is how the automation glyph, the notification taxonomy, the dialog signal, and the fact that `content.lines` is *untruncated* (Live calls `_break_line` at draw time) were all established.

Findings worth not re-deriving, each of which cost an hour:

- **`draw_vertical_list(lines, list_cursor_char, list_index)`** takes no total, which is what settles the list-position question above.
- **`MenuCursor.position`** returns only 0/1/2 -- a row within the visible window, not an absolute index.
- **`with_loop_overview` is `cls(**k)`**, so `NotificationContent` survives it. Had it downcast to `Content`, every notification would have been misclassified as a main screen and the whole overlay taxonomy would be wrong.
- **`Display.display(content)`** is fed only by `render()` → `Optional[Content]`, so the `isinstance(message, str)` branch in `_do_display` is for other framework callers and can never reach our hook. `None` can, and is handled.
- **`component_map['Step_Sequence'].note_editor`** is the reachable chain, resolved by `Move.setup()` during construction. `ComponentMap.__getitem__` constructs the factory and writes it back, which is why `dict.get` matters here even more than for `Active_Parameter`.
- **`StepTied`/`StepPartiallyTied`** are produced *only* by `show_duration_of_active_steps`.
- **`NotificationView.render`** preserves `\n` when `supports_new_line=True`, which Move sets.
- Move raises a notification for nearly every discrete state toggle (`Notifications.Track.mute/solo/arm`, `Transport.*`, `Notes.*`, `Device.*`, `Clip.*`, `Scene.*`, `Sequence.current_bar`), which is why so little else needs new code.

**Disassembly rather than decompilation is the only option, and that is not a workaround.** Live 12's Python 3.11 introduced zero-cost exception tables and the adaptive interpreter, which broke every Python decompiler -- clean full decompilation of Live 12 `.pyc` is not possible with current tools. Reading bytecode with `dis` is what the wider Live scripting community does too (see [structure-void's unofficial docs](https://midiremotescripts.structure-void.com/)). For cross-checking API shape, gluon mirrors the extracted sources at [`AbletonLive12_MIDIRemoteScripts`](https://github.com/gluon/AbletonLive12_MIDIRemoteScripts) -- useful for the `ableton.v2`/`v3` framework, though the `Move` package itself is what matters here and is best read directly.

## Known Inaccessible Surfaces

**The rule that decides what belongs here: speak only what a sighted user already gets from the device.** No new features, no invented information, no new gestures. Two things were designed against this and then **cut** for failing it, so do not re-propose them:

- **List position ("3 of 12")** -- rejected. `_do_display` calls `draw_vertical_list(content.lines, content.list_cursor_char, content.list_index)`, and there is **no total in that call**. Live never draws one, so a sighted user cannot see it either. (It *is* reachable, via `component_map['Menu_Modes']._menu_cursor._current_item.{index,visible_items}` -- and `Content.list_index` is only ever 0/1/2, a row within the visible window, per `MenuCursor.position`. Reachable but not parity.)
- **Menu name on entry** -- rejected. `menu.list_content` builds `lines` from the visible items only; no title is ever drawn for a menu or submenu.

Still not addressed:

- **Loop overview** (`LoopOverviewData`: playhead, loop bounds, positions) -- graphical only, wrapped onto nearly every view via `with_loop_overview()`. Continuous, so translating it would need a query gesture.
- **Level meters** (`left_meter`/`right_meter`) -- same; set only on the master-volume screen.
- **The 32 pads** (`Session.*` clip state, `DrumGroup.PadFilled` content, `Instrument.NoteScale`) -- LED-only, genuinely inaccessible, and **the largest remaining gap on the device**. Deliberately out of scope by the owner's decision, not because it is hard.
- **Step state the user has not just touched** -- the light is read on a tap, so Live-UI edits, undo and recording stay silent by design. See "Reading the lights".

**Almost everything else is already covered by notifications.** Move raises an OLED notification for track mute/solo/arm/select, transport metronome/loop/tap-tempo, note delete/nudge/transpose, device, clip, scene, full-velocity, note-repeat and bar/page changes -- and the bridge already announces those. That is why the honest answer to "what else can be made accessible?" is "very little".

**`Content.value` is a partial gap.** It is a normalised 0–1 float driving the bar graphic, and for almost every screen the human-readable value is also in `lines` -- but not always. `parameter_view`'s master-track branch renders

```python
Content(lines=['Volume', '', ''], value=normalized_parameter_value(p), ...)
```

so the level exists *only* as the bar. A blind user turning the master volume heard "Volume" and never learned the level. `_format_content()` therefore takes the active parameter and, when the overlay produced a single text line, appends `str(parameter)` -- the same display string Live's own Velocity branch of `parameter_view` uses. Only for the single-line case: every other branch already puts a value string in `lines`, and appending there would double it.

The bar *position* on multi-line parameter screens is still not surfaced, and neither are `left_meter`/`right_meter`.

## Naming Conventions

- Project name in prose/docs: **Move-SR-Bridge**
- Python package/folder: **Move_SR_Bridge** (underscores)
- Log prefix in all logger calls: `Move_SR_Bridge:`
- Log file: `~/.move_sr_bridge/Move_SR_Bridge.log`
- Debug tool log file: `tools/speech_history.log` (separate from `Move_SR_Bridge.log`, no shared code with `sr_helper.py`)
- Helper files: `sr_helper.py`, `sr_helper.exe`, `sr_helper_mac`
- Bridge module: `sr_bridge.py`

## Release Process

### Version scheme

**PEP 440 dot form: `MAJOR.MINOR.PATCH[.devN]`** -- `1.7.0`, `1.7.0.dev1`. Chosen over `1.7.0-dev1` because `1.7.0.dev1` sorts *before* `1.7.0` under PEP 440, which is what it means: a pre-release of 1.7.0, not something after it. `version.py` is Python and should follow Python's convention; git tags take dots without complaint.

The canonical pattern lives in `scripts/bump_version.py` as `VERSION_PATTERN` and is duplicated in `build.yml`. **`tests/test_version.py` asserts the two are character-for-character identical** -- if they drift, CI accepts a version the tooling rejects (or the reverse) and it only surfaces at release time. Leading zeros in `devN` are rejected so `dev1` and `dev01` cannot both exist and disagree about ordering.

### `scripts/bump_version.py`

Rewrites **only** the `__version__` line, so the GPL header and docstring survive -- a rewrite that regenerated the file would be a licensing defect, not a cosmetic one.

| Command | Effect |
|---|---|
| `--show` | print the current version and its tag |
| `--set 1.7.0.dev1` | set exactly, validated |
| `--dev` | `1.7.0.dev1` → `1.7.0.dev2`; **errors** on a release version |
| `--release` | `1.7.0.dev3` → `1.7.0`; errors on a release version |

`--dev` refusing to guess is deliberate: deriving "the next dev" from `1.6.0` means deciding whether the next release is a patch, minor or major, and a tool that guesses that will eventually guess wrong silently.

### Branches and CI

1. Day-to-day work lands on **`dev`**, versioned `.devN`.
2. To release: `--release`, commit, tag `v<__version__>`, push the tag.

`.github/workflows/build.yml` triggers on **`v*` tags, pushes to `dev`, and `workflow_dispatch`**. The tag-only rule was dropped on purpose: it meant the frozen Windows/macOS artefacts were first exercised at the moment of release, which is the worst possible time to discover a packaging fault. Releases are still tag-driven -- **a branch build publishes nothing**, it only uploads workflow artifacts.

`verify-version` is two-mode, because a branch push has no tag to compare against:

- **tag** → `v${version}` must equal the tag exactly;
- **branch** → `__version__` must carry a `.devN` suffix, so a dev build can never be mistaken for a release in the log -- the same argument the tag rule already makes, extended one step.

A dev tag (`v1.7.0.dev1`) satisfies both and publishes as a **prerelease** (`prerelease: ${{ contains(github.ref_name, '.dev') }}`).

`test` (unit suite + `compileall`) runs on **Python 3.11** to match Live's interpreter, so 3.12+ syntax cannot slip through, and gates both platform builds.

`scripts/release_mac.sh` builds locally; it reads the version from `version.py` and prints the matching tag. It uses `$PYTHON` (default `python3`) -- do not reintroduce a hardcoded venv, since building on a different interpreter than CI's 3.13 silently produces a different artefact.

It also runs the unit suite and `smoke_helper.py` before packaging, because it did neither: the one release path a maintainer drives by hand was the one with no gates behind it, and it printed a ready-to-paste `gh release create` line for an unsmoke-tested, **single-architecture** artefact. Tagging is the recommended route; publishing the local zip is now labelled as the deliberate exception it is.

## Testing

`tests/` holds a stdlib-`unittest` suite that runs without Live, hardware, or any dependency:

```
python3 -m unittest discover -s tests -v
```

`tests/stubs.py` injects a fake `Move` package (including a `display_util` submodule with real content classes -- without it `_content_types` stays empty and the formatting tests would silently only exercise the fallback branch) and points `HOME` at a temp directory so tests never touch the real `~/.move_sr_bridge/`. The redirect happens **before** the "already imported?" early return in `import_bridge()`/`import_sr_helper()`, so a runner that pre-imports the package still gets it.

No test opens a real socket or binds a port. `test_protocol.py` drives `handle_client` over a `socketpair()`; `test_sr_bridge.py` substitutes the socket class; `_helper_is_running` is patched everywhere it could be reached.

**Watch for tests that cannot fail.** Two got through review and into the tree:

- a dialog-probe test that asserted `assertIn(result, (True, False))` -- unfalsifiable for a boolean, and in fact `_dialog_is_open()` short-circuits on `_Live is None` outside Live, so its body never ran at all;
- a `kill()` escalation test whose fake process had no `kill()` method, so the call raised `AttributeError` into the catch-all and the assertion (`terminated`) passed either way.

When adding a test for a rule, check it against a deliberately broken copy of the rule. Several tests here were written, seen to pass, and only *then* found not to fail when the code was mutated -- including one in this very suite whose fixture happened to make an alphabetical sort agree with the mtime sort it was meant to distinguish from.

Hardware behaviour still needs manual testing:
1. Deploy with `scripts/install_mac.sh` (macOS) or `scripts\install.bat` (Windows)
2. Open Live, select Move_SR_Bridge as Control Surface
3. Connect Move via USB, verify speech/braille output
4. Check `~/.move_sr_bridge/Move_SR_Bridge.log` and Live's `Log.txt` for errors

The helper is testable without Live: run `python3 Move_SR_Bridge/sr_helper.py`, then send it a line of JSON on `127.0.0.1:8765` (`{"cmd": "speak", "text": "..."}\n`) and check the log.
