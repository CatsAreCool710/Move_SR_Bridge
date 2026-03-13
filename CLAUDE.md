# Move-SR-Bridge

Screen reader support for Ableton Move via Tolk. GPLv3, Copyright 2026 Jeremiah Ticket.

## Architecture

Two-process design forced by Ableton Live's embedded Python lacking `ctypes`:

1. **`Move_SR_Bridge/`** -- MIDI Remote Script package installed to Live's `MIDI Remote Scripts/` directory. Subclasses the stock `Move` control surface, monkey-patches `Display.display()` to intercept OLED text, sends it over TCP to the helper.
2. **`sr_helper.exe`** (or `sr_helper.py` via system Python) -- Standalone process listening on `127.0.0.1:8765`. Loads `Tolk.dll` via `ctypes.cdll` to speak/braille via whichever screen reader is active (NVDA, JAWS, ZoomText, Window-Eyes, System Access).

The bridge module (`sr_bridge.py`) is the TCP socket client running inside Live. It uses only `socket` and `json` -- no `ctypes`.

## Key Constraints

- **Live's Python 3.11 has no `ctypes`** (`_ctypes` not compiled in). This is the fundamental reason for the two-process architecture. Do not try to call DLLs from `__init__.py` or `sr_bridge.py`.
- **Live's Python DOES have `socket`, `subprocess`, `json`** -- these are safe to use in the remote script.
- **`sr_bridge.py` must stay compatible with Python 3.11** (Live's embedded interpreter). No f-strings with `=` debug syntax, no 3.12+ features.
- **Tolk uses cdecl** (`ctypes.cdll`), not stdcall (`ctypes.windll`). All string parameters are `c_wchar_p` (wide strings).
- **Tolk needs companion DLLs** alongside it: `nvdaControllerClient64.dll` for NVDA. JAWS/ZoomText use COM (no extra DLLs).
- **The package folder name** (`Move_SR_Bridge`) must be a valid Python identifier (no hyphens). This is what appears in Live's Control Surface dropdown.
- **GPLv3 license headers** required on all Python source files. Copyright holder: Jeremiah Ticket.

## File Layout

```
Move_SR_Bridge/          The MIDI Remote Script package (deployed to Live)
  __init__.py            Entry point -- subclasses Move, hooks Display.display()
  sr_bridge.py           TCP client (socket+json only, runs in Live's Python)
  sr_helper.py           TCP server + Tolk bridge (runs via system Python/exe)
  sr_helper.exe          PyInstaller --onefile --noconsole build of sr_helper.py
  Tolk.dll               Screen reader abstraction (64-bit, cdecl)
  nvdaControllerClient64.dll  NVDA companion DLL (loaded by Tolk)

scripts/
  build.py               PyInstaller build script
  install.bat            Batch installer (copies to Live's MIDI Remote Scripts)
  install_from_source.bat  Installs without .exe
  start_helper.bat       Manual helper launcher with visible console
```

## Build & Deploy

- Build exe: `python scripts/build.py` (requires `pip install pyinstaller`)
- Deploy to Live: `scripts/install.bat` (auto-detects Live 12 path)
- Live MIDI Remote Scripts path: `C:\ProgramData\Ableton\Live 12 Suite\Resources\MIDI Remote Scripts\Move_SR_Bridge\`
- Live log: `C:\Users\seash\AppData\Roaming\Ableton\Live 12.3.6\Preferences\Log.txt`
- Helper log: `Move_SR_Bridge.log` (written next to sr_helper.exe at runtime)

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
- Helper files: `sr_helper.py`, `sr_helper.exe`
- Bridge module: `sr_bridge.py`

## Testing

No automated test suite. Testing is done manually:
1. Deploy to Live's MIDI Remote Scripts
2. Open Live, select Move_SR_Bridge as Control Surface
3. Connect Move via USB, verify speech/braille output
4. Check `Move_SR_Bridge.log` and Live's `Log.txt` for errors
