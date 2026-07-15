# Move-SR-Bridge -- Agent Instructions

This file provides context for AI coding agents (GitHub Copilot, Cursor, etc.) working on this project.

## Project Overview

Move-SR-Bridge adds screen reader support to the Ableton Move hardware controller when used with Ableton Live. It intercepts text rendered to the Move's OLED display and routes it to the active screen reader.

## Architecture

This is a **two-process** system. The reason is that Ableton Live's embedded Python 3.11 does not include `ctypes` (the `_ctypes` native module is not compiled in), so DLLs cannot be loaded from within the MIDI Remote Script.

### Process 1: MIDI Remote Script (runs inside Live)

- **Location:** `Move_SR_Bridge/` (deployed to Live's `MIDI Remote Scripts/` directory)
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
{"cmd": "cancel"}
{"cmd": "quit"}
```

## File Structure

```
Move_SR_Bridge/                  MIDI Remote Script package
  __init__.py                    Entry point, Move subclass, display hook
  sr_bridge.py                   TCP socket client (runs in Live)
  sr_helper.py                   TCP server + screen reader bridge (cross-platform)
  sr_helper.exe                  Windows: compiled helper (PyInstaller onefile)
  sr_helper_mac                  macOS: compiled helper (PyInstaller onefile)
  Tolk.dll                       Windows: screen reader abstraction (64-bit, cdecl)
  nvdaControllerClient64.dll     Windows: NVDA companion DLL (loaded by Tolk)

scripts/                         Build and deployment scripts
  build.py                       PyInstaller build script (Windows)
  build_mac.py                   PyInstaller build script (macOS)
  install.bat                    Windows: deploy to Live (pre-built, with .exe)
  install_from_source.bat        Windows: deploy to Live (source only, no .exe)
  start_helper.bat               Windows: manual helper launcher (visible console)
  install_mac.sh                 macOS: deploy to Live
  uninstall_mac.sh               macOS: uninstall from Live
  start_helper_mac.sh            macOS: manual helper launcher
```

## Critical Rules

1. **Never use `ctypes` in `__init__.py` or `sr_bridge.py`** -- these run inside Live's Python which does not have it.
2. **Never use f-strings with `=` (debug syntax) in `sr_bridge.py`** -- Live runs Python 3.11 which doesn't support them.
3. **Tolk uses cdecl** (`ctypes.cdll`), not stdcall (`ctypes.windll`). String params are `c_wchar_p`.
4. **All Python files must have GPLv3 license headers.** Copyright holder: Jeremiah Ticket.
5. **The package folder name must be a valid Python identifier** -- `Move_SR_Bridge` with underscores, not hyphens.
6. **Log prefix:** All logger calls use `Move_SR_Bridge:` as the prefix.
7. **Log file:** `Move_SR_Bridge.log`, written next to the helper executable at runtime.
8. **Helper auto-detection:** The remote script probes TCP port 8765 before launching the helper. If a helper is already running (manual launch), it connects without spawning a new one. On disconnect, it only sends `quit` if it launched the helper.
9. **macOS VoiceOver:** The helper uses `osascript` to call `tell application "VoiceOver" to speak "..."`. Text must be escaped for AppleScript strings (escape `\` and `"`).

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

### Windows
- **Live MIDI Remote Scripts:** `C:\ProgramData\Ableton\Live 12 Suite\Resources\MIDI Remote Scripts\`
- **Live log:** `C:\Users\<user>\AppData\Roaming\Ableton\Live 12.x.x\Preferences\Log.txt`

### macOS
- **Live MIDI Remote Scripts:** `/Applications/Ableton Live XX.app/Contents/App-Resources/MIDI Remote Scripts/`

- **Helper log:** `Move_SR_Bridge.log` (in the deployed package directory)

## Testing

No automated tests. Manual testing only:

1. Deploy `Move_SR_Bridge/` to Live's MIDI Remote Scripts
2. Open Live, select `Move_SR_Bridge` as Control Surface
3. Connect Move via USB
4. Verify speech and braille output with your screen reader
5. Check `Move_SR_Bridge.log` and Live's `Log.txt` for errors

## Supported Screen Readers

- **Windows (via Tolk):** NVDA, JAWS, Window-Eyes, ZoomText, System Access. Tolk auto-detects which one is running.
- **macOS (Tahoe 26+):** VoiceOver via AppleScript. Braille handled automatically by VoiceOver when active.
