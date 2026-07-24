# Move-SR-Bridge

Screen reader support for the Ableton Move hardware controller when
connected to Ableton Live as a control surface.

## Downloads

Pre-built releases are available on the [Releases page](https://github.com/CatsAreCool710/Move_SR_Bridge/releases):

- **`Move-SR-Bridge-Windows.zip`** -- Windows release
- **`Move-SR-Bridge-macOS.zip`** -- macOS release. Contains a single
  self-contained `Install Move-SR-Bridge.app` -- everything it needs is
  embedded inside the app bundle.

## Introduction

I got an Ableton Move a few weeks ago and already really love this thing. It has forced me to think in new ways due to its limitations. One of the main reasons I bought it was to also control Live. I was sad to discover anything you do does not speak. Not the scale menus for the pads, parameters, or notifications.

Move-SR-Bridge intercepts the text content rendered to the Move's 128x64
OLED display -- menus, parameter names, values, and notifications -- and
sends it to your screen reader for speech and braille output. The OLED
display continues to function normally.

**Note:** This project does not add any features to the Move -- it
merely intercepts whatever text the Move sends to its OLED and speaks
it. What you hear is exactly what you see on the display.

## Supported Screen Readers

### Windows

Via the [Tolk](https://github.com/ndarilek/tolk) abstraction library:

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

This tree describes the **repository**. The distributed releases differ:
the Windows release zip mirrors this folder structure (`Move_SR_Bridge/` +
`scripts/`), while the macOS release zip contains only the single
self-contained `Install Move-SR-Bridge.app` (the package is embedded
inside `Contents/Resources/`).

```
Move-SR-Bridge/
  LICENSE                              GPLv3 license text
  README.md                            This file

  Move_SR_Bridge/                      The MIDI Remote Script package
    __init__.py                        Remote script entry point
    sr_bridge.py                       TCP socket client (runs in Live)
    sr_helper.py                       Helper process source (cross-platform)
    sr_helper.exe                      Compiled helper -- Windows (PyInstaller)
    sr_helper_mac                      Compiled helper -- macOS (PyInstaller)
    Tolk.dll                           Tolk screen reader library (Windows)
    nvdaControllerClient64.dll         NVDA companion DLL (Windows)

  scripts/                             Build and install scripts
    build.py                           PyInstaller build script (Windows)
    build_mac.py                       PyInstaller build script (macOS)
    install.bat                        Batch installer (Windows)
    install_from_source.bat            Batch installer, source only (Windows)
    uninstall.bat                      Batch uninstaller (Windows)
    start_helper.bat                   Manual helper launcher (Windows)
    install_mac.sh                     Shell installer (macOS)
    uninstall_mac.sh                   Shell uninstaller (macOS)
    start_helper_mac.sh                Manual helper launcher (macOS)
```

## Installation

### Windows

#### Method 1: Batch Installer (Recommended)

1. Open a Command Prompt (you may need **Run as Administrator** since
   the MIDI Remote Scripts directory is under `C:\ProgramData`).
2. Navigate to the project directory.
3. Run:
   ```
   scripts\install.bat
   ```
4. The script will show you what will be copied and ask for confirmation.
5. Follow the on-screen instructions.

#### Method 2: Manual Copy

1. Copy the entire `Move_SR_Bridge/` folder to:
   ```
   C:\ProgramData\Ableton\Live 12 Suite\Resources\MIDI Remote Scripts\
   ```
   (Adjust the path if you have Live 12 Standard, Lite, or Intro.)

2. After copying, you should have:
   ```
   MIDI Remote Scripts\
     Move\                (stock Ableton scripts -- leave this alone)
     Move_SR_Bridge\      (this project)
       __init__.py
       sr_bridge.py
       sr_helper.py
       sr_helper.exe
       Tolk.dll
       nvdaControllerClient64.dll
   ```
3. Open Ableton Live, go to **Settings > Link/Tempo/MIDI**, and select
   **Move_SR_Bridge** as the Control Surface.
4. Set the Input and Output ports to your Move's MIDI Live Port.
5. Make sure your screen reader is running.

### macOS

#### Method 1: Graphical Installer (Recommended)

1. Download `Move-SR-Bridge-macOS.zip` from the
   [Releases page](https://github.com/CatsAreCool710/Move_SR_Bridge/releases)
   and extract it.
2. Double-click **Install Move-SR-Bridge.app**.
3. Choose **Install**, select which Live installation(s) to target, and
   follow the prompts. The same app also handles uninstalling later --
   just run it again and choose **Uninstall**.

This app is self-contained (the package is embedded inside it), so it
does not need to sit next to any other files.

#### Method 2: Shell Installer (from source)

1. Open Terminal.
2. Navigate to the project directory (a clone of this repo, with
   `Move_SR_Bridge/sr_helper_mac` already built -- see
   [Building From Source](#building-from-source)).
3. Run:
   ```
   scripts/install_mac.sh
   ```
4. Follow the prompts to select which Live installation(s) to target.

#### Method 3: Manual Copy

1. Copy the entire `Move_SR_Bridge/` folder to your Live installation's
   MIDI Remote Scripts directory:
   ```
   /Applications/Ableton Live 12 Suite.app/Contents/App-Resources/MIDI Remote Scripts/
   ```
2. Make the helper binary executable:
   ```
   chmod +x .../Move_SR_Bridge/sr_helper_mac
   ```
3. Open Ableton Live, go to **Settings > Link/Tempo/MIDI**, and select
   **Move_SR_Bridge** as the Control Surface.

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

1. Open a Command Prompt (you may need **Run as Administrator**).
2. Run:
   ```
   scripts\uninstall.bat
   ```
3. Select the installation(s) to remove, or choose **A** for all.

### macOS

If you installed via **Install Move-SR-Bridge.app**, just run it again
and choose **Uninstall**.

If you installed from source:

1. Open Terminal.
2. Run:
   ```
   scripts/uninstall_mac.sh
   ```
3. Select the installation(s) to remove.

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

| Action                        | Output                               |
|-------------------------------|--------------------------------------|
| Shift + Step menus            | Selected menu item                   |
| Encoder turns (parameters)    | Parameter name and value             |
| Notifications (undo, etc.)    | Notification text                    |
| Script load                   | "Move connected"                     |
| Script unload / Live close   | "Move disconnected"                  |

Both speech and braille output are supported on Windows (braille
availability depends on the active screen reader). On macOS, speech is
routed through VoiceOver, which handles braille output automatically.

## How It Works

Ableton Live's embedded Python lacks `ctypes`, so screen reader DLLs
cannot be called directly from within the MIDI Remote Script. Move-SR-Bridge
solves this with a two-process architecture:

```
Ableton Live (embedded Python)             sr_helper (system Python / compiled)
+--------------------------------------+  +-----------------------------------+
| Move_SR_Bridge/__init__.py           |  | Windows: loads Tolk.dll via       |
|   Wraps Display.display()            |  |   ctypes, speaks via NVDA/JAWS/  |
|   Extracts text from content    TCP  |  |   etc.                           |
|   Sends JSON to localhost:8765 ----->|  | macOS: speaks via VoiceOver      |
| Move_SR_Bridge/sr_bridge.py         |  |   AppleScript (osascript)        |
|   Socket client                      |  +-----------------------------------+
+--------------------------------------+
```

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
  editing). Announced as "name: value".
- **NotificationContent** -- transient overlays (undo, delete, mode
  changes). The full notification text is announced.
- **Content** -- general display. All non-empty lines are joined.

## Troubleshooting

### Move_SR_Bridge does not appear in the Control Surface dropdown

Live scans scripts on startup. If the script has an import error, it
will be silently skipped. Check Live's log file:

- **Windows:** `C:\Users\<you>\AppData\Roaming\Ableton\Live 12.x.x\Preferences\Log.txt`
- **macOS:** `~/Library/Preferences/Ableton/Live 12.x.x/Log.txt`

Search for `Move_SR_Bridge` to see any errors.

### No speech output

**Windows:**
1. Make sure your screen reader is running (check the system tray).
2. Check the helper log file at `Move_SR_Bridge\Move_SR_Bridge.log`
   (in the MIDI Remote Scripts directory) for errors. Look for the
   "Tolk loaded -- detected screen reader:" line to confirm detection.
3. If the helper did not start, check Task Manager for `sr_helper.exe`.
4. Try running the helper manually with `scripts\start_helper.bat` to
   see console output.

**macOS:**
1. Make sure VoiceOver is enabled (Cmd+F5).
2. Verify VoiceOver AppleScript is enabled: open VoiceOver Utility
   (VO+F8), go to General, check "Allow VoiceOver to be controlled
   with AppleScript".
3. Check the helper log file at `Move_SR_Bridge/Move_SR_Bridge.log`.
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
