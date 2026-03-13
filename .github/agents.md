# Move-SR-Bridge -- Agent Instructions

This file provides context for AI coding agents (GitHub Copilot, Cursor, etc.) working on this project.

## Project Overview

Move-SR-Bridge adds screen reader support to the Ableton Move hardware controller when used with Ableton Live. It intercepts text rendered to the Move's OLED display and routes it to the active screen reader (NVDA, JAWS, ZoomText, Window-Eyes, or System Access) via the Tolk abstraction library.

## Architecture

This is a **two-process** system. The reason is that Ableton Live's embedded Python 3.11 does not include `ctypes` (the `_ctypes` native module is not compiled in), so DLLs cannot be loaded from within the MIDI Remote Script.

### Process 1: MIDI Remote Script (runs inside Live)

- **Location:** `Move_SR_Bridge/` (deployed to Live's `MIDI Remote Scripts/` directory)
- **Entry point:** `__init__.py` -- subclasses the stock `Move` control surface
- **Display hook:** monkey-patches `Display.display()` after `on_identified()` to intercept OLED content
- **TCP client:** `sr_bridge.py` sends JSON commands over TCP to `127.0.0.1:8765`
- **Constraint:** Only `socket`, `subprocess`, `json`, and other pure-Python/statically-linked modules are available. **No `ctypes`, no `pip` packages.**
- **Python version:** Must be compatible with Python 3.11 (Live's embedded interpreter). No 3.12+ features.

### Process 2: Helper (runs via system Python or compiled .exe)

- **Source:** `sr_helper.py`
- **Compiled:** `sr_helper.exe` (PyInstaller `--onefile --noconsole`)
- **Role:** TCP server on port 8765. Receives JSON commands, forwards speech/braille to screen readers via `Tolk.dll` (`ctypes.cdll`, cdecl calling convention).
- **Dependencies:** `Tolk.dll` + `nvdaControllerClient64.dll` (companion for NVDA support) must be in the same directory.

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
  sr_helper.py                   TCP server + Tolk bridge (system Python)
  sr_helper.exe                  Compiled helper (PyInstaller onefile)
  Tolk.dll                       Screen reader abstraction (64-bit, cdecl)
  nvdaControllerClient64.dll     NVDA companion DLL (loaded by Tolk)

scripts/                         Build and deployment scripts
  build.py                       PyInstaller build script
  install.bat                    Deploy to Live (pre-built, with .exe)
  install_from_source.bat        Deploy to Live (source only, no .exe)
  start_helper.bat               Manual helper launcher (visible console)
```

## Critical Rules

1. **Never use `ctypes` in `__init__.py` or `sr_bridge.py`** -- these run inside Live's Python which does not have it.
2. **Never use f-strings with `=` (debug syntax) in `sr_bridge.py`** -- Live runs Python 3.11 which doesn't support them.
3. **Tolk uses cdecl** (`ctypes.cdll`), not stdcall (`ctypes.windll`). String params are `c_wchar_p`.
4. **All Python files must have GPLv3 license headers.** Copyright holder: Jeremiah Ticket.
5. **The package folder name must be a valid Python identifier** -- `Move_SR_Bridge` with underscores, not hyphens.
6. **Log prefix:** All logger calls use `Move_SR_Bridge:` as the prefix.
7. **Log file:** `Move_SR_Bridge.log`, written next to the helper executable at runtime.
8. **Helper auto-detection:** The remote script probes TCP port 8765 before launching `sr_helper.exe`. If a helper is already running (manual launch), it connects without spawning a new one. On disconnect, it only sends `quit` if it launched the helper.

## Build Commands

- **Build exe:** `python scripts/build.py` (requires `pip install pyinstaller`)
- **Deploy to Live:** `scripts\install.bat`
- **Deploy source only:** `scripts\install_from_source.bat`
- **Manual helper:** `scripts\start_helper.bat`

## Key Paths

- **Live MIDI Remote Scripts:** `C:\ProgramData\Ableton\Live 12 Suite\Resources\MIDI Remote Scripts\`
- **Live log:** `C:\Users\<user>\AppData\Roaming\Ableton\Live 12.x.x\Preferences\Log.txt`
- **Helper log:** `Move_SR_Bridge.log` (in the deployed package directory)

## Testing

No automated tests. Manual testing only:

1. Deploy `Move_SR_Bridge/` to Live's MIDI Remote Scripts
2. Open Live, select `Move_SR_Bridge` as Control Surface
3. Connect Move via USB
4. Verify speech and braille output with your screen reader
5. Check `Move_SR_Bridge.log` and Live's `Log.txt` for errors

## Supported Screen Readers

Via Tolk: NVDA, JAWS, Window-Eyes, ZoomText, System Access. Tolk auto-detects which one is running. No SAPI fallback is enabled.
