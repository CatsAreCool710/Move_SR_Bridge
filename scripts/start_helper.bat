@echo off
REM start_helper.bat - Manually launch the screen reader helper process
REM Copyright (C) 2026 Jeremiah Ticket
REM Licensed under GPLv3 -- see LICENSE for details.
REM
REM Part of Move-SR-Bridge.
REM
REM Launches sr_helper.py using system Python with a visible console
REM window for debugging.  The helper listens on TCP port 8765 and
REM forwards speech/braille commands to the active screen reader via Tolk.
REM
REM The Move_SR_Bridge remote script will auto-detect this running helper
REM and skip launching its own sr_helper.exe.  When Live disconnects,
REM the script will NOT shut down this manually-started helper.

setlocal enabledelayedexpansion

echo Move-SR-Bridge Helper (manual launch)
echo =======================================
echo.
echo This will start the screen reader helper with a visible console window.
echo You can see status messages and any errors here.
echo.
echo The helper will listen on 127.0.0.1:8765 and forward speech/braille
echo to your active screen reader (NVDA, JAWS, ZoomText, etc.).
echo.

REM --- Find sr_helper.py ---
set "HELPER="

set "SCRIPT_PATH=%~dp0"
for %%I in ("%SCRIPT_PATH%..") do set "PROJECT_ROOT=%%~fI"
set "SOURCE_HELPER=%PROJECT_ROOT%\Move_SR_Bridge\sr_helper.py"

if exist "%SOURCE_HELPER%" (
    set "HELPER=%SOURCE_HELPER%"
    goto :found
)

REM Check deployed location
for /d %%D in ("C:\ProgramData\Ableton\Live 12*") do (
    set "CANDIDATE=%%D\Resources\MIDI Remote Scripts\Move_SR_Bridge\sr_helper.py"
    if exist "!CANDIDATE!" (
        set "HELPER=!CANDIDATE!"
        goto :found
    )
)

echo ERROR: Cannot find sr_helper.py
echo Checked:
echo   %SOURCE_HELPER%
echo   C:\ProgramData\Ableton\Live 12*\Resources\MIDI Remote Scripts\Move_SR_Bridge\
pause
exit /b 1

:found
echo Using: %HELPER%
echo.

REM --- Prompt for confirmation ---
set /p CONFIRM="Press Enter to start the helper, or any other key to cancel: "
if not "%CONFIRM%"=="" (
    echo.
    echo Helper not started.
    pause
    exit /b 0
)

echo.
echo Starting helper...
echo.
echo ==================================================================
echo   Helper is running. Press Ctrl+C to stop.
echo ==================================================================
echo.

python "%HELPER%"

if %ERRORLEVEL% neq 0 (
    echo.
    echo Helper exited with error code %ERRORLEVEL%.
    echo Make sure Python is installed and accessible from PATH.
    pause
)
