# Move-SR-Bridge

Screen reader support for the Ableton Move hardware controller when
connected to Ableton Live as a control surface.

## Introduction

I got an Ableton Move a few weeks ago and already really love this thing. It has forced me to think in new ways due to its limitations. One of the main reasons I bought it was to also control Live. I was sad to discover anything you do does not speak. Not the scale menus for the pads, parameters, or notifications.

Move-SR-Bridge intercepts the text content rendered to the Move's 128x64
OLED display -- menus, parameter names, values, and notifications -- and
sends it to your screen reader for speech and braille output. The OLED
display continues to function normally.

## Supported Screen Readers

Via the [Tolk](https://github.com/ndarilek/tolk) abstraction library,
Move-SR-Bridge supports:

- **NVDA**
- **JAWS**
- **Window-Eyes**
- **ZoomText**
- **System Access**

Tolk automatically detects which screen reader is running and routes
speech and braille output accordingly.

## Requirements

- **Windows** (64-bit)
- **Ableton Live 12** (tested with 12.3.6)
- **Ableton Move** (connected via USB)
- A supported **screen reader** (running)

## Project Structure

```
Move-SR-Bridge/
  LICENSE                              GPLv3 license text
  README.md                            This file

  Move_SR_Bridge/                      The MIDI Remote Script package
    __init__.py                        Remote script entry point
    sr_bridge.py                       TCP socket client (runs in Live)
    sr_helper.py                       Helper process source code
    sr_helper.exe                      Compiled helper (PyInstaller)
    Tolk.dll                           Tolk screen reader library
    nvdaControllerClient64.dll         NVDA companion DLL (used by Tolk)

  scripts/                             Build and install scripts
    build.py                           PyInstaller build script
    install.bat                        Batch installer (pre-built)
    install_from_source.bat            Batch installer (source only)
    start_helper.bat                   Manual helper launcher
```

## Installation

There are two ways to install Move-SR-Bridge.

### Method 1: Batch Installer (Recommended)

1. Open a Command Prompt (you may need **Run as Administrator** since
   the MIDI Remote Scripts directory is under `C:\ProgramData`).
2. Navigate to the project directory.
3. Run:
   ```
   scripts\install.bat
   ```
4. The script will show you what will be copied and ask for confirmation.
5. Follow the on-screen instructions.

### Method 2: Manual Copy

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

## Running From Source

If you prefer not to use the compiled `sr_helper.exe`, you can run the
helper from source using system Python:

1. Install from source (omits the .exe):
   ```
   scripts\install_from_source.bat
   ```

2. Before opening Live, start the helper manually:
   ```
   scripts\start_helper.bat
   ```
   This opens a console window running `sr_helper.py` via system Python.
   The console shows status messages useful for debugging.

3. Open Live and configure Move_SR_Bridge as usual. The remote script
   auto-detects the running helper via TCP and will not try to launch
   its own `sr_helper.exe`.

4. When Live unloads the script, it will **not** shut down a
   manually-started helper. Close the console window yourself, or
   press Ctrl+C.

## Building From Source

To compile `sr_helper.exe` from `sr_helper.py`:

1. Install PyInstaller:
   ```
   pip install pyinstaller
   ```

2. From the project root, run:
   ```
   python scripts\build.py
   ```

3. The script will ask for confirmation, then build the helper
   (`--onefile --noconsole`) and copy the resulting `.exe` into
   `Move_SR_Bridge/`.

## What Gets Announced

| Action                        | Output                               |
|-------------------------------|--------------------------------------|
| Shift + Step menus            | Selected menu item                   |
| Encoder turns (parameters)    | Parameter name and value             |
| Notifications (undo, etc.)    | Notification text                    |
| Script load                   | "Move connected"                     |
| Script unload / Live close   | "Move disconnected"                  |

Both speech and braille output are supported (braille availability
depends on the active screen reader).

## How It Works

Ableton Live's embedded Python lacks `ctypes`, so the Tolk DLL cannot
be called directly from within the MIDI Remote Script. Move-SR-Bridge
solves this with a two-process architecture:

```
Ableton Live (embedded Python)             sr_helper.exe
+--------------------------------------+  +---------------------------+
| Move_SR_Bridge/__init__.py           |  | Loads Tolk.dll via ctypes |
|   Wraps Display.display()            |  |   Tolk auto-detects the  |
|   Extracts text from content    TCP  |  |   active screen reader   |
|   Sends JSON to localhost:8765 ----->|  |   (NVDA, JAWS, etc.)     |
| Move_SR_Bridge/sr_bridge.py         |  |                           |
|   Socket client                      |  | Tolk.dll                  |
+--------------------------------------+  |   nvdaControllerClient64  |
                                          +----.dll-------------------+
```

1. The script subclasses the stock `Move` control surface and
   monkey-patches `Display.display()` after the hardware is identified.

2. Every time the display content changes, the intercepted method
   extracts the text lines and sends them as JSON over a TCP socket to
   `127.0.0.1:8765`.

3. `sr_helper.exe` receives the commands and forwards them to the active
   screen reader via Tolk.

4. The original display method is always called -- the OLED keeps working.

### Helper Auto-Detection

When the remote script loads, it probes TCP port 8765 before launching
`sr_helper.exe`. If a helper is already listening (started manually or
from a previous session), the script connects to it without spawning a
new process. When the script unloads, it only sends a quit command to
the helper if it launched it -- a manually-started helper is left
running.

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

```
C:\Users\<you>\AppData\Roaming\Ableton\Live 12.x.x\Preferences\Log.txt
```

Search for `Move_SR_Bridge` to see any errors.

### No speech output

1. Make sure your screen reader is running (check the system tray).
2. Check the helper log file at `Move_SR_Bridge\Move_SR_Bridge.log`
   (in the MIDI Remote Scripts directory) for errors. Look for the
   "Tolk loaded -- detected screen reader:" line to confirm detection.
3. If the helper did not start, check Task Manager for `sr_helper.exe`.
4. Try running the helper manually with `scripts\start_helper.bat` to
   see console output.

### Manual helper launch (debugging)

```
scripts\start_helper.bat
```

Or directly:
```
cd "C:\ProgramData\Ableton\Live 12 Suite\Resources\MIDI Remote Scripts\Move_SR_Bridge"
python sr_helper.py
```

## AI Assistance & Security

This project was developed with AI assistance (Claude by Anthropic) under
human direction and review. While care has been taken to ensure correctness,
AI-generated code may contain errors or security vulnerabilities. Users
should review the source code and use this software at their own risk. No
warranty is provided -- see the GPLv3 license for details.

## Third-Party Components

- **Tolk.dll** -- Tolk screen reader abstraction library by Davy Kager.
  Licensed under the
  [GNU Lesser General Public License v3](https://www.gnu.org/licenses/lgpl-3.0.html).
  Redistributed unmodified.

- **nvdaControllerClient64.dll** -- NVDA Controller Client library.
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
