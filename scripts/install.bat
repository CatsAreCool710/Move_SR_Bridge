@echo off
REM install.bat - Install Move-SR-Bridge (pre-built) to Ableton Live
REM Copyright (C) 2026 Jeremiah Ticket
REM Licensed under GPLv3 -- see LICENSE for details.

setlocal enabledelayedexpansion

echo Move-SR-Bridge Installer
echo =========================
echo.
echo This script will copy Move-SR-Bridge to Ableton Live's MIDI Remote Scripts folder.
echo.

REM --- Auto-detect Ableton Live 12 MIDI Remote Scripts path ---
set "SCRIPTS_DIR="
for /d %%D in ("C:\ProgramData\Ableton\Live 12*") do (
    set "CANDIDATE=%%D\Resources\MIDI Remote Scripts"
    if exist "!CANDIDATE!" (
        set "SCRIPTS_DIR=!CANDIDATE!"
    )
)

if not defined SCRIPTS_DIR (
    echo ERROR: Could not find Ableton Live 12 MIDI Remote Scripts directory.
    echo Expected: C:\ProgramData\Ableton\Live 12*\Resources\MIDI Remote Scripts\
    echo.
    echo Please copy the Move_SR_Bridge folder manually.
    pause
    exit /b 1
)

REM --- Determine source directory (project root\Move_SR_Bridge) ---
set "SCRIPT_PATH=%~dp0"
for %%I in ("%SCRIPT_PATH%..") do set "PROJECT_ROOT=%%~fI"
set "SOURCE=%PROJECT_ROOT%\Move_SR_Bridge"

if not exist "%SOURCE%\__init__.py" (
    echo ERROR: Cannot find %SOURCE%\__init__.py
    echo Make sure you are running this from the scripts\ folder.
    pause
    exit /b 1
)

set "DEST=%SCRIPTS_DIR%\Move_SR_Bridge"

echo Detected Live MIDI Remote Scripts: %SCRIPTS_DIR%
echo.
echo Source:      %SOURCE%
echo Destination: %DEST%
echo.
echo Files to be copied:
echo   __init__.py
echo   sr_bridge.py
echo   sr_helper.py
echo   sr_helper.exe
echo   Tolk.dll
echo   nvdaControllerClient64.dll
echo.

REM --- Prompt for confirmation ---
set /p CONFIRM="Press Enter to install, or any other key to cancel: "
if not "%CONFIRM%"=="" (
    echo.
    echo Installation cancelled.
    pause
    exit /b 0
)

echo.
echo Installing...
echo.

REM --- Copy files ---
if exist "%DEST%" (
    echo Removing old installation...
    rmdir /s /q "%DEST%"
)

xcopy "%SOURCE%" "%DEST%\" /E /I /Q /Y

if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: Copy failed. Try running as Administrator.
    pause
    exit /b 1
)

echo.
echo ================================================
echo   Installation complete!
echo ================================================
echo.
echo Next steps:
echo   1. Open Ableton Live
echo   2. Go to Settings ^> Link/Tempo/MIDI
echo   3. Select "Move_SR_Bridge" as the Control Surface
echo   4. Set Input/Output to your Move's MIDI Live Port
echo   5. Make sure your screen reader is running
echo.
pause
