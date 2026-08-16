# Move-SR-Bridge

Screen reader support for the Ableton Move hardware controller when
connected to Ableton Live as a control surface.

## Downloads

Pre-built releases are available on the [Releases page](https://github.com/CatsAreCool710/Move_SR_Bridge/releases):

- **`Move-SR-Bridge-Windows.zip`** -- Windows release
- **`Move-SR-Bridge-macOS.zip`** -- macOS release. Contains a single
  self-contained `Install Move-SR-Bridge.app` -- everything it needs is
  embedded inside the app bundle.

See [CHANGELOG.md](CHANGELOG.md) for what changed in each release.

## Introduction

I got an Ableton Move a few weeks ago and already really love this thing. It has forced me to think in new ways due to its limitations. One of the main reasons I bought it was to also control Live. I was sad to discover anything you do does not speak. Not the scale menus for the pads, parameters, or notifications.

Move-SR-Bridge intercepts the text content rendered to the Move's 128x64
OLED display -- menus, parameter names, values, and notifications -- and
sends it to your screen reader for speech and braille output. The OLED
display continues to function normally.

**Note:** This project does not add any features to the Move -- it
merely intercepts whatever text the Move sends to its OLED and speaks
it. What you hear is exactly what you see on the display.

### How this relates to Move's own screen reader

Move has an official, built-in screen reader you reach by opening
`http://move.local/screen-reader` in a browser. **That covers Move running
standalone**, and it is the right tool for that job -- it announces button
presses and knob turns as you play the instrument on its own.

Move-SR-Bridge covers the other half: **Move used as a control surface for
Ableton Live**. In that mode the OLED is driven by Live's own `Move` remote
script running inside Live, not by Move's standalone firmware, so the
built-in web screen reader does not see any of it. The two are
complementary, and using this project does not disable or replace Move's
own screen reader.

If you only use Move standalone, you do not need this project.

## Supported Screen Readers

### Windows

Via the [Tolk](https://github.com/dkager/tolk) abstraction library:

- **NVDA**
- **JAWS**
- **Window-Eyes**
- **ZoomText**
- **System Access**

Tolk automatically detects which screen reader is running and routes
speech and braille output accordingly.

### macOS

- **VoiceOver** (macOS Tahoe 26 or later) -- speaks via AppleScript.
  Braille output to connected displays is handled automatically by
  VoiceOver.

## Requirements

### Windows

- **Windows** (64-bit)
- **Ableton Live 12** (tested with 12.3.6)
- **Ableton Move** (connected via USB)
- A supported **screen reader** (running)

### macOS

- **macOS Tahoe 26** or later
- **Ableton Live 12**
- **Ableton Move** (connected via USB)
- **VoiceOver** enabled (Cmd+F5), with "Allow VoiceOver to be controlled
  with AppleScript" turned on in VoiceOver Utility > General

## Project Structure

This tree describes the **repository**, plus the two compiled helpers
(marked "built") which are produced by `scripts/build.py` /
`scripts/build_mac.py` and are not checked in. The distributed releases
differ again: the Windows release zip mirrors this folder structure
(`Move_SR_Bridge/` + `scripts/`), while the macOS release zip contains
only the single self-contained `Install Move-SR-Bridge.app` (the package
is embedded inside `Contents/Resources/`).

```
Move-SR-Bridge/
  LICENSE                              GPLv3 license text
  README.md                            This file
  CHANGELOG.md                         What changed in each release

  Move_SR_Bridge/                      The MIDI Remote Script package
    __init__.py                        Remote script entry point
    config.py                          Config loader + shared file paths
    version.py                         Version string (single source)
    sr_bridge.py                       TCP socket client (runs in Live)
    sr_helper.py                       Helper process source (cross-platform)
    sr_helper.exe                      Compiled helper -- Windows (built)
    sr_helper_mac                      Compiled helper -- macOS (built)
    Tolk.dll                           Tolk screen reader library (Windows)
    nvdaControllerClient64.dll         NVDA companion DLL (Windows)

  scripts/                             Build and install scripts
    build.py                           PyInstaller build script (Windows)
    build_mac.py                       PyInstaller build script (macOS)
    smoke_helper.py                    Release check: a built helper must
                                        honour config.ini
    install.bat                        Batch installer (Windows)
    install_from_source.bat            Batch installer, source only (Windows)
    uninstall.bat                      Batch uninstaller (Windows)
    start_helper.bat                   Manual helper launcher (Windows)
    install_mac.sh                     Shell installer (macOS)
    uninstall_mac.sh                   Shell uninstaller (macOS)
    start_helper_mac.sh                Manual helper launcher (macOS)
    release_mac.sh                     Local macOS release builder
    lib/
      resolve_install_dir.sh           Install-location resolver (macOS)
      ResolveInstallDir.ps1            Install-location resolver (Windows)
    installer/mac/                     JXA graphical installer sources

  tools/
    speech_history_logger.py           macOS debug tool (see Diagnostics)

  tests/                               Unit tests (stdlib unittest only)
```

Run the tests with no dependencies, no Live and no hardware:

```
python3 -m unittest discover -s tests -v
```

### Where things get installed

On **both platforms** the remote script goes into your **Ableton User
Library**, in a `Remote Scripts` subfolder:

| What | Windows | macOS |
|------|---------|-------|
| Remote script package | `%USERPROFILE%\Documents\Ableton\User Library\Remote Scripts\Move_SR_Bridge\` | `~/Music/Ableton/User Library/Remote Scripts/Move_SR_Bridge/` |
| Settings | `%USERPROFILE%\.move_sr_bridge\config.ini` | `~/.move_sr_bridge/config.ini` |
| Log | `%USERPROFILE%\.move_sr_bridge\Move_SR_Bridge.log` | `~/.move_sr_bridge/Move_SR_Bridge.log` |

Those are the *default* User Library paths. Live lets you move the User
Library, and on Windows OneDrive frequently redirects `Documents`
somewhere else, so the installers do not assume them — see
[How the install location is chosen](#how-the-install-location-is-chosen).

This is **Ableton's own documented method**, not a workaround. Per
[Installing third-party remote scripts](https://help.ableton.com/hc/en-us/articles/209072009-Installing-third-party-remote-scripts):
as of **Live 10.1.13** you can create a `Remote Scripts` folder in the User
Library, scripts placed there appear in Live's Preferences → MIDI, and
*"after upgrading to a newer Live version, remote scripts placed in this
folder will continue to be loaded in Live."*

So the User Library is the right home on both platforms: it needs no
administrator rights, one copy serves every Live installation on the
machine, and it survives Live updates. The older locations — Live's
`C:\ProgramData\Ableton\...` tree on Windows, and Live's application
bundle on macOS — are all three of the opposite, and the installers now
only fall back to them when no User Library can be found or created.

Settings and the log live under your home directory on both platforms —
the install directory is not always writable, and on macOS it is not a
place anything should be writing to at runtime.

### How the install location is chosen

Every installer and uninstaller — the Windows `.bat` files, the macOS
shell scripts, and the macOS graphical installer — resolves the location
the same way, trying each step in turn:

1. **`MOVE_SR_USER_LIBRARY`**, if you set it. This wins outright; if it
   points at a folder that cannot be used, the install stops rather than
   quietly going somewhere you did not ask for.
2. **Live's own `Library.cfg`.** Live records the User Library path in
   plain XML at `%APPDATA%\Ableton\Live <version>\Preferences\Library.cfg`
   (Windows) or `~/Library/Preferences/Ableton/Live <version>/Library.cfg`
   (macOS). Live never deletes old version folders, and version-number
   order is *not* the same as "the one you actually run" — a 12.4.5 beta
   can sit next to the 12.4.3 that is current — so the **most recently
   modified** file is used, not the highest version number.
3. **The default User Library path** for the platform. On Windows this
   follows OneDrive's Documents redirection rather than hardcoding
   `%USERPROFILE%\Documents`.
4. **Creating the default User Library**, if none exists yet. Live picks
   it up the next time it starts.
5. **Inside Live itself** — `C:\ProgramData\Ableton\Live *\Resources\MIDI
   Remote Scripts` on Windows, the application bundle on macOS. This is a
   genuine last resort and the installers warn before using it: it needs
   administrator rights, is erased or rewritten by Live updates, and only
   serves the one Live version it was written into. The graphical macOS
   installer offers to browse for your User Library before resorting to
   it, and asks for confirmation either way.

If you moved your User Library and step 2 somehow does not find it, Live
shows the current path under **Settings > Library > Location of User
Library**.

Whichever step wins, the installers then **remove copies at every other
location**. Two packages with the same name on Live's search path is
ambiguous, and a stale copy would keep shadowing the new one.

## Installation

### Windows

Move-SR-Bridge installs into your **Ableton User Library**, by default:

```
%USERPROFILE%\Documents\Ableton\User Library\Remote Scripts\Move_SR_Bridge\
```

It no longer installs into `C:\ProgramData\Ableton\Live *\Resources\MIDI
Remote Scripts\`. That location needs administrator rights, is rewritten
by Live updates, and has to be installed to once per Live version. The
User Library needs none of that, and one copy serves every Live
installation. The installers still sweep the old location for stale
copies — see
[How the install location is chosen](#how-the-install-location-is-chosen).

#### Method 1: Batch Installer (Recommended)

1. Open a Command Prompt. **Administrator is no longer needed** for a
   normal User Library install.
2. Navigate to the project directory (or the extracted release zip).
3. Run:
   ```
   scripts\install.bat
   ```
4. The script shows where it will install, how it found that location,
   and what will be copied, then asks for confirmation.
5. Follow the on-screen instructions.

The `scripts\lib\ResolveInstallDir.ps1` file must stay next to the `.bat`
files — they call it to read Live's `Library.cfg`, and refuse to run
without it. It ships in the release zip.

If you set `MOVE_SR_USER_LIBRARY` before running, that path is used
instead of anything auto-detected:

```
set "MOVE_SR_USER_LIBRARY=D:\Ableton\User Library"
scripts\install.bat
```

#### Method 2: Manual Copy

1. Find your User Library path in Live under **Settings > Library >
   Location of User Library**.

2. Copy the entire `Move_SR_Bridge/` folder into a `Remote Scripts`
   folder inside it, creating that folder if it does not exist:
   ```
   %USERPROFILE%\Documents\Ableton\User Library\Remote Scripts\
   ```

3. After copying, you should have:
   ```
   Remote Scripts\
     Move_SR_Bridge\      (this project)
       __init__.py
       config.py
       version.py
       sr_bridge.py
       sr_helper.py
       sr_helper.exe
       Tolk.dll
       nvdaControllerClient64.dll
   ```
4. Delete any older copy from Live's program data, or it will shadow this
   one:
   ```
   C:\ProgramData\Ableton\Live *\Resources\MIDI Remote Scripts\Move_SR_Bridge
   ```
5. Open Ableton Live, go to **Settings > Link/Tempo/MIDI**, and select
   **Move_SR_Bridge** as the Control Surface.
6. Set the Input and Output ports to your Move's MIDI Live Port.
7. Make sure your screen reader is running.

### macOS

On macOS, Move-SR-Bridge installs into your **Ableton User Library**, by
default:

```
~/Music/Ableton/User Library/Remote Scripts/Move_SR_Bridge/
```

It deliberately does *not* install inside Live's application bundle.
That bundle is code-signed with a hardened runtime, so writing into it
breaks the signature seal, needs admin rights, and — most importantly —
**is erased by every Live update**. The User Library is per-user, always
writable, survives updates, and one install covers every Live
installation on the machine.

The exact path is read from Live's own `Library.cfg`, so a relocated User
Library is found automatically — see
[How the install location is chosen](#how-the-install-location-is-chosen).
If that somehow fails, the graphical installer offers to browse for the
folder, and the shell scripts take it from `MOVE_SR_USER_LIBRARY`.

All three methods below remove any older copy found inside a Live app
bundle, since two packages with the same name on Live's search path is
ambiguous.

#### Before you start: opening the downloaded installer

`Install Move-SR-Bridge.app` is **not signed or notarized**, so macOS
Gatekeeper blocks it on first launch. See
[Opening the Unsigned Installer](#opening-the-unsigned-installer) below
for the steps — including a one-line Terminal alternative if the
Settings panel is awkward to navigate.

#### Method 1: Graphical Installer (Recommended)

1. Download `Move-SR-Bridge-macOS.zip` from the
   [Releases page](https://github.com/CatsAreCool710/Move_SR_Bridge/releases)
   and extract it.
2. Quit Ableton Live if it is running.
3. Open **Install Move-SR-Bridge.app** (see the Gatekeeper note above).
4. Choose **Install** and follow the prompts. The same app also handles
   uninstalling later -- just run it again and choose **Uninstall**.

This app is self-contained (the package is embedded inside it), so it
does not need to sit next to any other files.

#### Method 2: Shell Installer (from source)

1. Quit Ableton Live if it is running.
2. Open Terminal.
3. Navigate to the project directory (a clone of this repo, with
   `Move_SR_Bridge/sr_helper_mac` already built -- see
   [Building From Source](#building-from-source)).
4. Run:
   ```
   scripts/install_mac.sh
   ```
   The script reads your User Library location from Live's `Library.cfg`.
   To override it:
   ```
   MOVE_SR_USER_LIBRARY="/path/to/User Library" scripts/install_mac.sh
   ```

#### Method 3: Manual Copy

1. Copy the entire `Move_SR_Bridge/` folder into your User Library's
   `Remote Scripts` folder (create it if it does not exist):
   ```
   ~/Music/Ableton/User Library/Remote Scripts/
   ```
2. Make the helper binary executable:
   ```
   chmod +x ~/Music/Ableton/User\ Library/Remote\ Scripts/Move_SR_Bridge/sr_helper_mac
   ```
3. Delete any older copy from inside Live's app bundle:
   ```
   /Applications/Ableton Live*.app/Contents/App-Resources/MIDI Remote Scripts/Move_SR_Bridge
   ```
4. Open Ableton Live, go to **Settings > Link/Tempo/MIDI**, and select
   **Move_SR_Bridge** as the Control Surface.

#### Opening the Unsigned Installer

`Install Move-SR-Bridge.app` is built by CI and is **not code-signed or
notarized** — that requires a paid Apple Developer ID, which this project
does not have. macOS therefore blocks it the first time you open it,
usually with *"Apple could not verify 'Install Move-SR-Bridge.app' is
free of malware."*

This is Gatekeeper reacting to the missing signature, not to anything
detected in the app. You have two ways past it.

**Option A — Terminal (fastest, fewest steps)**

Remove the quarantine flag the download added, then open it normally:

```
xattr -d com.apple.quarantine ~/Downloads/"Install Move-SR-Bridge.app"
open ~/Downloads/"Install Move-SR-Bridge.app"
```

Adjust the path if you extracted the zip somewhere other than
`~/Downloads`. If `xattr` reports *"No such xattr"*, the flag was already
cleared — just run the `open` command.

**Option B — System Settings**

1. Try to open the app once and dismiss the warning dialog. This is
   required; the button in step 3 does not appear until macOS has
   blocked a launch.
2. Open **System Settings > Privacy & Security**.
3. Interact with the scroll area and navigate to the bottom. VoiceOver
   announces a line naming the blocked app, followed by an
   **Open Anyway** button. Activate it.
4. Authenticate with Touch ID or your password.
5. A final confirmation dialog appears — choose **Open Anyway**.

Either way you only do this once per download.

If you would rather not run an unsigned app at all, use
[Method 2: Shell Installer](#method-2-shell-installer-from-source),
which builds and installs from source with no app bundle involved.

#### VoiceOver Setup (Required)

1. Enable VoiceOver: **Cmd+F5**
2. Open VoiceOver Utility: **VO+F8** (VO = Ctrl+Option, or Caps Lock)
3. Go to **General**
4. Check **"Allow VoiceOver to be controlled with AppleScript"**
5. Close VoiceOver Utility

## Running From Source

If you prefer not to use the compiled helper, you can run it from source
using system Python:

### Windows

1. Install from source (omits the .exe):
   ```
   scripts\install_from_source.bat
   ```

2. Before opening Live, start the helper manually:
   ```
   scripts\start_helper.bat
   ```
   This opens a console window running `sr_helper.py` via system Python.

### macOS

1. Before opening Live, start the helper manually:
   ```
   scripts/start_helper_mac.sh
   ```
   Or directly:
   ```
   python3 Move_SR_Bridge/sr_helper.py
   ```

In both cases, the remote script auto-detects the running helper via TCP
and will not try to launch its own. When Live unloads the script, it will
**not** shut down a manually-started helper -- close it yourself or press
Ctrl+C.

## Uninstallation

### Windows

1. Open a Command Prompt.
2. Run:
   ```
   scripts\uninstall.bat
   ```
3. It lists every copy it found — in your User Library and in any older
   `C:\ProgramData\Ableton\...` location — and removes them all on
   confirmation.

Removing a copy left under `C:\ProgramData` needs **Run as
Administrator**; the script says so and exits non-zero if it hits one it
cannot delete. A User Library install needs no elevation.

Your settings and log at `%USERPROFILE%\.move_sr_bridge` are kept —
delete that folder by hand if you want them gone too.

### macOS

If you installed via **Install Move-SR-Bridge.app**, just run it again
and choose **Uninstall**.

If you installed from source:

1. Quit Ableton Live.
2. Open Terminal.
3. Run:
   ```
   scripts/uninstall_mac.sh
   ```

Both sweep every location the installers can use — the User Library
recorded in Live's `Library.cfg`, the default User Library, and any older
copy left inside a Live app bundle — and then offer to delete
`~/.move_sr_bridge/` (your settings and log).

## Building From Source

To compile the helper binary from `sr_helper.py`:

1. Install PyInstaller:
   ```
   pip install pyinstaller
   ```

2. From the project root, run:
   - **Windows:** `python scripts\build.py`
   - **macOS:** `python scripts/build_mac.py`

3. The script builds the helper (`--onefile`) and copies the resulting
   binary into `Move_SR_Bridge/`.

On macOS, to also build the self-contained graphical installer
(`Install Move-SR-Bridge.app`) after `sr_helper_mac` exists, run
`scripts/installer/mac/build.sh`. It embeds the package and `LICENSE`
inside the app bundle. Official releases build a universal2 (arm64 +
x86_64) `sr_helper_mac` via CI; a local build produces a binary matching
your own Mac's architecture only.

## What Gets Announced

| Action | Output |
|---|---|
| Shift + Step menus | Selected menu item, and "submenu" when it opens one |
| Step buttons (tap) | "Step 5 on" / "Step 5 off" |
| Encoder turns (parameters) | Parameter name and value |
| Notifications (undo, etc.) | Notification text |
| Script load | "Move connected" |
| Script unload / Live close | "Move disconnected" |

**Menus.** Live draws a `>` beside a menu item that opens a list and a `-`
beside one that acts immediately, so that marker is now spoken. In Settings,
"Brightness" opens the LED and pad brightness levels and reads as
"Brightness, submenu"; "Standalone" switches the device out of Live's control
the moment you press the wheel, and reads with no marker.

**Step buttons.** A short tap on one of the 16 buttons along the bottom row
toggles that step, and its new state is read back from the button's own light.
The number is 1-based within the page you are on. Holding a step instead
enters velocity editing and announces that, so the two never overlap. The 32
pads are not announced.

To turn step announcements off, add this to
`~/.move_sr_bridge/config.ini` -- by hand, since an existing config file is
never rewritten:

```ini
[speech]
step_toggles = false
```

Both speech and braille output are supported on Windows (braille
availability depends on the active screen reader). On macOS, speech is
routed through VoiceOver, which handles braille output automatically.

## How It Works

Ableton Live's embedded Python lacks `ctypes`, so screen reader DLLs
cannot be called directly from within the MIDI Remote Script. Move-SR-Bridge
solves this with a two-process architecture:

There are two processes, connected by a TCP socket on `127.0.0.1:8765`:

| Process | Runs in | Responsibility |
|---|---|---|
| **Remote script** (`__init__.py`, `sr_bridge.py`) | Live's embedded Python | Wraps `Display.display()`, extracts text from the OLED content, sends it as JSON to the socket |
| **Helper** (`sr_helper.py` / compiled binary) | System Python, separate process | Listens on the socket; on Windows loads `Tolk.dll` via `ctypes` to reach NVDA/JAWS/etc., on macOS speaks via VoiceOver AppleScript |

The split exists because the remote script cannot load a DLL itself, so
everything requiring `ctypes` lives on the far side of the socket.

1. The script subclasses the stock `Move` control surface and
   monkey-patches `Display.display()` after the hardware is identified.

2. Every time the display content changes, the intercepted method
   extracts the text lines and sends them as JSON over a TCP socket to
   `127.0.0.1:8765`.

3. The helper receives the commands and forwards them to the active
   screen reader.

4. The original display method is always called -- the OLED keeps working.

### Helper Auto-Detection

When the remote script loads, it probes TCP port 8765 before launching
the helper. If a helper is already listening (started manually or from
a previous session), the script connects to it without spawning a new
process. When the script unloads, it only sends a quit command to the
helper if it launched it -- a manually-started helper is left running.

### Content Types

The Move's display system uses several content types, each formatted
differently for speech:

- **VerticalListContent** -- scrolling menus. The currently selected
  item is announced.
- **HorizontalListContent** -- name/value pairs (e.g., parameter
  editing). Announced as "name: value" -- except when the name is the
  track or scene currently selected in Live, in which case only the
  value is spoken (see Double-Speech Reduction below).
- **NotificationContent** -- transient overlays (undo, delete, mode
  changes). The full notification text is announced.
- **Content** -- general display. All non-empty lines are joined with
  commas, except where Live has wrapped a single sentence across lines
  (detected by a lowercase continuation), which is joined with a space so
  you don't hear a pause mid-sentence.

### Making the Screen Speakable

Some of what Live draws is meaningful to look at but meaningless to hear.
Move-SR-Bridge normalises it:

- **Automation indicator.** Live marks an automated parameter by
  prefixing its name with a Private Use Area glyph from the Move's icon
  font. A screen reader has no pronunciation for it, so the automation
  state was simply lost. It is now spoken as "automated" -- e.g.
  "automated Cutoff: 800 Hz".
- **Other icon glyphs** are dropped rather than left to be announced as
  "unknown character".
- **Display-width abbreviations** are expanded where they are unreadable
  aloud (`Autmtn. Arm` becomes `Automation Arm`). Conventional audio
  shorthand like `Freq`, `LFO` and `Env` is deliberately left alone, so
  what you hear matches what Live calls the same control elsewhere.

### Notifications and Repetition

Live shows transient notifications (undo, copy, mode changes, and a dozen
other categories) that briefly replace the main screen and then clear.
Move-SR-Bridge tracks the last *main* screen separately from the last
thing spoken, so when a notification clears, the unchanged screen
underneath is not announced all over again. Without this, routine use
produces roughly twice as much speech.

### Urgent Screens

Two screens skip the debounce delay entirely and are spoken immediately,
dropping anything queued behind them:

- **A modal dialog in Live.** Live is blocked until it is dismissed. This
  is detected from Live's own dialog state, not by matching the on-screen
  message.
- **The shutdown prompt** ("Press wheel to shut down"), which is waiting
  on a button press.

### Modal dialogs and VoiceOver (macOS)

When a dialog opens in Live, Move-SR-Bridge speaks **the dialog's actual
text** — "Save changes to Untitled before closing?" — rather than the
Move's own screen, which only says a dialog exists.

It does this **only while Live is in the background.** If Live is the
frontmost app, VoiceOver already announces the dialog itself, with more
detail than the Move has (the question *and* the buttons), and it
preempts anything Move-SR-Bridge tries to say at the same moment.
Competing with it would at best duplicate what you just heard. With Live
in the background VoiceOver says nothing about it — and that is exactly
when you might be sitting at the Move wondering why it has stopped
responding.

If a dialog is open and the Move seems dead, bring Live to the front:
VoiceOver will read the dialog.

On Windows the message is spoken unconditionally.

### Double-Speech Reduction

Ableton Live has its own native VoiceOver narration for track/scene
selection (independent of Move_SR_Bridge, and independent of the Move's
OLED), so changing tracks or scenes can otherwise be announced twice --
once by Live, once by Move_SR_Bridge. To reduce this, when the Move's
screen shows a "name: value" pair (e.g. "2-MIDI: No Device") and the
name matches the track or scene currently selected in Live, only the
value is spoken ("No Device") -- Live's own narration is expected to
have just said the name. This is a heuristic based on what's currently
selected, not a guarantee that Live actually spoke.

If the parameter is automated, "automated" is still announced: you hear
"automated, 0 dB" rather than a bare "0 dB". Live draws the automation
indicator as part of the name, so dropping the name would otherwise drop
that information too.

## Troubleshooting

### Move_SR_Bridge does not appear in the Control Surface dropdown

Live scans scripts on startup. If the script has an import error, it
will be silently skipped. Check Live's log file:

- **Windows:** `C:\Users\<you>\AppData\Roaming\Ableton\Live 12.x.x\Preferences\Log.txt`
- **macOS:** `~/Library/Preferences/Ableton/Live 12.x.x/Log.txt`

Search for two things:

- **`RemoteScriptError`** — Live's own tag for a script that failed to
  load. This is the term to look for first; the traceback under it names
  the file and line.
- **`Move_SR_Bridge`** — this script's own log lines, plus the
  `Control Surface="Move_SR_Bridge"` entry that confirms Live actually
  selected it.

Note that Live caches compiled `.pyc` files next to the script. If you
edit an installed script in place and the change seems to have no effect,
delete the `__pycache__` folder beside it so Live recompiles. (The
installers already avoid shipping one.)

If the log shows nothing at all for `Move_SR_Bridge`, Live never saw it —
it is installed somewhere Live does not scan. The installer prints both
the destination and how it found it ("Located by: Live's Library.cfg");
compare that against **Settings > Library > Location of User Library** in
Live. If they disagree, reinstall with `MOVE_SR_USER_LIBRARY` set to the
path Live shows:

- **Windows:** `set "MOVE_SR_USER_LIBRARY=C:\path\to\User Library"` then
  `scripts\install.bat`
- **macOS:** `MOVE_SR_USER_LIBRARY="/path/to/User Library" scripts/install_mac.sh`

### No speech output

**Windows:**
1. Make sure your screen reader is running (check the system tray).
2. Check the helper log file at
   `%USERPROFILE%\.move_sr_bridge\Move_SR_Bridge.log` for errors. Look
   for the "Tolk loaded -- detected screen reader:" line to confirm
   detection.
3. If the helper did not start, check Task Manager for `sr_helper.exe`.
4. Try running the helper manually with `scripts\start_helper.bat` to
   see console output.

**macOS:**
1. Make sure VoiceOver is enabled (Cmd+F5).
2. Verify VoiceOver AppleScript is enabled: open VoiceOver Utility
   (VO+F8), go to General, check "Allow VoiceOver to be controlled
   with AppleScript".
3. Check the helper log file at `~/.move_sr_bridge/Move_SR_Bridge.log`.
4. Try running the helper manually with `scripts/start_helper_mac.sh`
   to see terminal output.

### Manual helper launch (debugging)

**Windows:**
```
scripts\start_helper.bat
```

**macOS:**
```
scripts/start_helper_mac.sh
```

## AI Assistance & Security

This project was developed with AI assistance (Claude by Anthropic via opencode) under
human direction and review. While care has been taken to ensure correctness,
AI-generated code may contain errors or security vulnerabilities. Users
should review the source code and use this software at their own risk. No
warranty is provided -- see the GPLv3 license for details.

## Third-Party Components

- **Tolk.dll** (Windows) -- Tolk screen reader abstraction library by Davy Kager.
  Licensed under the
  [GNU Lesser General Public License v3](https://www.gnu.org/licenses/lgpl-3.0.html).
  Redistributed unmodified.

- **nvdaControllerClient64.dll** (Windows) -- NVDA Controller Client library.
  Copyright NV Access Limited. Licensed under the
  [GNU Lesser General Public License v2.1](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html).
  Redistributed unmodified. Used by Tolk as a companion DLL for NVDA
  support.

## Disclaimer

This project is not affiliated with or endorsed by Ableton AG, NV
Access Limited, or Davy Kager. Ableton, Ableton Live, and Move are
trademarks of Ableton AG. NVDA is a trademark of NV Access Limited.

## License

Copyright (C) 2026 Jeremiah Ticket

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

See [LICENSE](LICENSE) for the full license text.
