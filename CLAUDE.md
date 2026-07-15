# Move-SR-Bridge

Screen reader support for Ableton Move. GPLv3, Copyright 2026 Jeremiah Ticket.

## Architecture

Two-process design forced by Ableton Live's embedded Python lacking `ctypes`:

1. **`Move_SR_Bridge/`** -- MIDI Remote Script package installed to Live's `MIDI Remote Scripts/` directory. Subclasses the stock `Move` control surface, monkey-patches `Display.display()` to intercept OLED text, sends it over TCP to the helper.
2. **`sr_helper.py`** -- Standalone process listening on `127.0.0.1:8765`. Cross-platform with two backends:
   - **Windows:** Loads `Tolk.dll` via `ctypes.cdll` to speak/braille via NVDA, JAWS, ZoomText, Window-Eyes, or System Access.
   - **macOS (Tahoe 26+):** Speaks via VoiceOver AppleScript (`osascript`). Braille handled automatically by VoiceOver.

The bridge module (`sr_bridge.py`) is the TCP socket client running inside Live. It uses only `socket` and `json` -- no `ctypes`.

## Key Constraints

- **Live's Python 3.11 has no `ctypes`** (`_ctypes` not compiled in). This is the fundamental reason for the two-process architecture. Do not try to call DLLs from `__init__.py` or `sr_bridge.py`.
- **Live's Python DOES have `socket`, `subprocess`, `json`** -- these are safe to use in the remote script.
- **`sr_bridge.py` must stay compatible with Python 3.11** (Live's embedded interpreter). No f-strings with `=` debug syntax, no 3.12+ features.
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
```

- `enabled`: When true, speech is delayed until no display updates occur for `delay_ms` milliseconds. Prevents rapid-fire speech during encoder turns.
- `delay_ms`: Lower values feel more responsive; higher values reduce chatter. Set to 0 to effectively disable.

## File Layout

```
Move_SR_Bridge/          The MIDI Remote Script package (deployed to Live)
  __init__.py            Entry point -- subclasses Move, hooks Display.display()
  config.py              Config loader (~/.move_sr_bridge/config.ini)
  sr_bridge.py           TCP client (socket+json only, runs in Live's Python)
  sr_helper.py           TCP server + screen reader bridge (cross-platform)
  sr_helper.exe          Windows: PyInstaller build (Tolk backend)
  sr_helper_mac          macOS: PyInstaller build (VoiceOver backend)
  Tolk.dll               Windows: screen reader abstraction (64-bit, cdecl)
  nvdaControllerClient64.dll  Windows: NVDA companion DLL (loaded by Tolk)

scripts/
  build.py               PyInstaller build script (Windows)
  build_mac.py           PyInstaller build script (macOS)
  install.bat            Batch installer for Windows
  install_from_source.bat  Windows: installs without .exe
  uninstall.bat          Batch uninstaller (Windows)
  start_helper.bat       Manual helper launcher (Windows)
  install_mac.sh         Shell installer for macOS
  uninstall_mac.sh       Shell uninstaller for macOS)
  start_helper_mac.sh    Manual helper launcher (macOS)
  installer/
    mac/
      Install Move-SR-Bridge.js  JXA graphical installer (osacompile)
      build.sh                   Builds the .app installer bundle
```

## Build & Deploy

### Windows
- Build exe: `python scripts/build.py` (requires `pip install pyinstaller`)
- Deploy to Live: `scripts\install.bat` (detects all Live 12 installations, prompts for selection)
- Uninstall: `scripts\uninstall.bat` (removes from selected Live 12 installation)
- Live MIDI Remote Scripts path: `C:\ProgramData\Ableton\Live 12 Suite\Resources\MIDI Remote Scripts\Move_SR_Bridge\`
- Live log: `C:\Users\<you>\AppData\Roaming\Ableton\Live 12.x.x\Preferences\Log.txt`

### macOS (Tahoe 26+)
- Build binary: `python scripts/build_mac.py` (requires `pip install pyinstaller`)
- Deploy to Live: `scripts/install_mac.sh` (detects Live installations in /Applications)
- Deploy to Live (GUI): `scripts/installer/mac/build.sh` then double-click `Install Move-SR-Bridge.app`
- Uninstall: `scripts/uninstall_mac.sh`
- Live MIDI Remote Scripts path: `/Applications/Ableton Live XX.app/Contents/App-Resources/MIDI Remote Scripts/`
- VoiceOver setup: Enable "Allow VoiceOver to be controlled with AppleScript" in VoiceOver Utility > General

- Helper log: `Move_SR_Bridge.log` (written next to the helper at runtime)

## Protocol

Newline-delimited JSON over TCP to `127.0.0.1:8765`:

```json
{"cmd": "speak", "text": "..."}
{"cmd": "braille", "text": "..."}
{"cmd": "cancel"}
{"cmd": "quit"}
```

## Naming Conventions

- Project name in prose/docs: **Move-SR-Bridge**
- Python package/folder: **Move_SR_Bridge** (underscores)
- Log prefix in all logger calls: `Move_SR_Bridge:`
- Log file: `Move_SR_Bridge.log`
- Helper files: `sr_helper.py`, `sr_helper.exe`, `sr_helper_mac`
- Bridge module: `sr_bridge.py`

## Testing

No automated test suite. Testing is done manually:
1. Deploy to Live's MIDI Remote Scripts
2. Open Live, select Move_SR_Bridge as Control Surface
3. Connect Move via USB, verify speech/braille output
4. Check `Move_SR_Bridge.log` and Live's `Log.txt` for errors
