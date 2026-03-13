@echo off
REM install_from_source.bat - Install Move-SR-Bridge without the compiled exe
REM Copyright (C) 2026 Jeremiah Ticket
REM Licensed under GPLv3 -- see LICENSE for details.
REM
REM This installs everything except sr_helper.exe.  Use this if you
REM want to run the helper from source via start_helper.bat or
REM "python sr_helper.py" instead of using the pre-built executable.

setlocal enabledelayedexpansion

echo Move-SR-Bridge Install From Source
echo ====================================
echo.
echo This script will copy Move-SR-Bridge to Ableton Live WITHOUT sr_helper.exe.
echo You'll need to run the helper manually.
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
    echo Please copy the files manually.
    pause
    exit /b 1
)

REM --- Determine source directory ---
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
echo   Tolk.dll
echo   nvdaControllerClient64.dll
echo.
echo NOTE: sr_helper.exe will NOT be copied.
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

REM --- Copy files (excluding .exe) ---
if exist "%DEST%" (
    echo Removing old installation...
    rmdir /s /q "%DEST%"
)

mkdir "%DEST%"

copy "%SOURCE%\__init__.py" "%DEST%\" >nul
copy "%SOURCE%\sr_bridge.py" "%DEST%\" >nul
copy "%SOURCE%\sr_helper.py" "%DEST%\" >nul
copy "%SOURCE%\Tolk.dll" "%DEST%\" >nul
copy "%SOURCE%\nvdaControllerClient64.dll" "%DEST%\" >nul

if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: Copy failed. Try running as Administrator.
    pause
    exit /b 1
)

echo.
echo ================================================
echo   Installation complete! (source-only)
echo ================================================
echo.
echo IMPORTANT: Before opening Live, start the helper manually:
echo   scripts\start_helper.bat
echo   -- or --
echo   python "%DEST%\sr_helper.py"
echo.
echo Then in Live:
echo   1. Go to Settings ^> Link/Tempo/MIDI
echo   2. Select "Move_SR_Bridge" as the Control Surface
echo   3. Set Input/Output to your Move's MIDI Live Port
echo   4. Make sure your screen reader is running
echo.
pause
