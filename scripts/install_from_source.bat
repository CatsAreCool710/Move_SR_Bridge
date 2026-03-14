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

REM --- Enumerate Ableton Live 12 installations ---
set "COUNT=0"
for /d %%D in ("C:\ProgramData\Ableton\Live 12*") do (
    set "CANDIDATE=%%D\Resources\MIDI Remote Scripts"
    if exist "!CANDIDATE!" (
        set /a COUNT+=1
        set "DIR_!COUNT!=%%D"
        set "SCRIPTS_!COUNT!=!CANDIDATE!"
        for %%N in ("%%D") do set "NAME_!COUNT!=%%~nxN"
    )
)

if %COUNT%==0 (
    echo ERROR: Could not find any Ableton Live 12 MIDI Remote Scripts directory.
    echo Expected: C:\ProgramData\Ableton\Live 12*\Resources\MIDI Remote Scripts\
    echo.
    echo Please copy the files manually.
    pause
    exit /b 1
)

REM --- Select target version ---
if %COUNT%==1 (
    set "SEL=1"
    echo Detected: !NAME_1!
    goto :selected
)

REM Multiple installations found
echo Multiple Ableton Live installations found:
for /l %%I in (1,1,%COUNT%) do (
    echo   %%I. !NAME_%%I!
)
echo   A. All of the above
echo.

REM Check for command-line argument
if not "%~1"=="" (
    set "SEL=%~1"
    echo Using command-line selection: !SEL!
    goto :validate
)

set /p SEL="Select version [1-%COUNT%, A]: "

:validate
REM Validate selection
if /i "!SEL!"=="A" goto :selected

REM Check if it's a valid number
set "VALID=0"
for /l %%I in (1,1,%COUNT%) do (
    if "!SEL!"=="%%I" set "VALID=1"
)
if "!VALID!"=="0" (
    echo ERROR: Invalid selection "!SEL!". Please enter 1-%COUNT% or A.
    pause
    exit /b 1
)

:selected

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

echo.
echo Source: %SOURCE%
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

REM --- Build list of targets ---
if /i "!SEL!"=="A" (
    set "FIRST=1"
    set "LAST=%COUNT%"
) else (
    set "FIRST=!SEL!"
    set "LAST=!SEL!"
)

REM Show destinations
for /l %%I in (!FIRST!,1,!LAST!) do (
    echo Destination: !SCRIPTS_%%I!\Move_SR_Bridge
)
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

REM --- Copy files to each target (excluding .exe) ---
set "FAIL=0"
for /l %%I in (!FIRST!,1,!LAST!) do (
    set "DEST=!SCRIPTS_%%I!\Move_SR_Bridge"
    echo.
    echo --- Installing to !NAME_%%I! ---

    if exist "!DEST!" (
        echo Removing old installation...
        rmdir /s /q "!DEST!"
    )

    mkdir "!DEST!"

    copy "%SOURCE%\__init__.py" "!DEST!\" >nul
    copy "%SOURCE%\sr_bridge.py" "!DEST!\" >nul
    copy "%SOURCE%\sr_helper.py" "!DEST!\" >nul
    copy "%SOURCE%\Tolk.dll" "!DEST!\" >nul
    copy "%SOURCE%\nvdaControllerClient64.dll" "!DEST!\" >nul

    if !ERRORLEVEL! neq 0 (
        echo ERROR: Copy failed for !NAME_%%I!. Try running as Administrator.
        set "FAIL=1"
    ) else (
        echo Installed to !NAME_%%I! successfully.
    )
)

if "!FAIL!"=="1" (
    echo.
    echo Some installations failed. See errors above.
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
echo   python Move_SR_Bridge\sr_helper.py
echo.
echo Then in Live:
echo   1. Go to Settings ^> Link/Tempo/MIDI
echo   2. Select "Move_SR_Bridge" as the Control Surface
echo   3. Set Input/Output to your Move's MIDI Live Port
echo   4. Make sure your screen reader is running
echo.
pause
