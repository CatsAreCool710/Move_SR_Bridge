@echo off
REM install_from_source.bat - Install Move-SR-Bridge without the compiled exe
REM Copyright (C) 2026 Jeremiah Ticket
REM Licensed under GPLv3 -- see LICENSE for details.
REM
REM This installs everything except sr_helper.exe.  Use this if you
REM want to run the helper from source via start_helper.bat or
REM "python sr_helper.py" instead of using the pre-built executable.
REM
REM Install location is resolved exactly as in install.bat -- see
REM scripts\lib\ResolveInstallDir.ps1.

setlocal enabledelayedexpansion

echo Move-SR-Bridge Install From Source
echo ====================================
echo.
echo This installs Move-SR-Bridge WITHOUT sr_helper.exe.
echo You'll need to run the helper manually.
echo.

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

REM --- Resolve the install location ---
REM Batch cannot parse XML, so Library.cfg handling lives in PowerShell.
set "RESOLVER=%SCRIPT_PATH%lib\ResolveInstallDir.ps1"
if not exist "%RESOLVER%" (
    echo ERROR: Cannot find %RESOLVER%
    echo The scripts\lib\ folder is missing from this download.
    pause
    exit /b 1
)

REM Delayed expansion is switched OFF while the resolver output is read.
REM With it on, `set "X=%%B"` re-scans the substituted text and eats any '!'
REM in the path -- and '!' is legal in a Windows folder name. The trailing
REM `endlocal & set ...` is the standard idiom for carrying values back out:
REM that line is parsed under the inner (disabled) setting, so the '!'
REM survives the hand-off too.
setlocal disabledelayedexpansion
set "REMOTE_SCRIPTS="
set "DEST_SOURCE="
set "LAST_RESORT="
set "RESOLVE_ERROR="
for /f "usebackq tokens=1* delims==" %%A in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%RESOLVER%" -Create`) do (
    if "%%A"=="PATH" set "REMOTE_SCRIPTS=%%B"
    if "%%A"=="SOURCE" set "DEST_SOURCE=%%B"
    if "%%A"=="LASTRESORT" set "LAST_RESORT=1"
    if "%%A"=="ERROR" set "RESOLVE_ERROR=%%B"
)
endlocal & set "REMOTE_SCRIPTS=%REMOTE_SCRIPTS%" & set "DEST_SOURCE=%DEST_SOURCE%" & set "LAST_RESORT=%LAST_RESORT%" & set "RESOLVE_ERROR=%RESOLVE_ERROR%"

if not "!RESOLVE_ERROR!"=="" (
    echo ERROR: !RESOLVE_ERROR!
    echo.
    echo Find the path in Live under Settings ^> Library ^> Location of
    echo User Library, then set MOVE_SR_USER_LIBRARY to it and try again.
    pause
    exit /b 1
)
if "!REMOTE_SCRIPTS!"=="" (
    echo ERROR: Could not locate an Ableton User Library or Live installation.
    echo.
    echo Open Live once so it creates your User Library, then run this again.
    pause
    exit /b 1
)

set "DEST=!REMOTE_SCRIPTS!\Move_SR_Bridge"

echo Source:      %SOURCE%
echo Destination: !DEST!
echo Located by:  !DEST_SOURCE!
echo.
echo Files to be copied:
echo   __init__.py
echo   config.py
echo   version.py
echo   sr_bridge.py
echo   sr_helper.py
echo   Tolk.dll
echo   nvdaControllerClient64.dll
echo.
echo NOTE: sr_helper.exe will NOT be copied.
echo.

if "!LAST_RESORT!"=="1" (
    echo WARNING: no Ableton User Library was found, so this will install
    echo into Live's shared program data. That location needs Administrator
    echo rights, is rewritten by Live updates, and only serves that one
    echo Live version.
    echo.
    echo Better: open Live once so it creates your User Library, or set
    echo MOVE_SR_USER_LIBRARY to its path, then run this again.
    echo.
)

REM --- Prompt for confirmation ---
REM Cleared first: `set /p` leaves the variable untouched when the user just
REM presses Enter, so a CONFIRM inherited from the environment would read as
REM "they typed something" and silently cancel the install.
set "CONFIRM="
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

REM --- Kill running sr_helper.exe if found (avoid a locked destination) ---
tasklist /FI "IMAGENAME eq sr_helper.exe" 2>nul | find /I "sr_helper.exe" >nul
if !ERRORLEVEL!==0 (
    echo Detected running sr_helper.exe process.
    echo Terminating sr_helper.exe...
    taskkill /F /IM sr_helper.exe >nul 2>&1
    echo sr_helper.exe terminated.
    echo.
)

REM --- Copy files (excluding .exe) ---
if exist "!DEST!" (
    echo Removing old installation...
    rmdir /s /q "!DEST!"
    if exist "!DEST!" (
        echo ERROR: Failed to remove the old installation at !DEST!
        echo Close Live and any Explorer window showing that folder, then
        echo try again. If it is under C:\ProgramData, run as Administrator.
        pause
        exit /b 1
    )
)

mkdir "!DEST!"

set "ITEM_FAIL=0"
copy "%SOURCE%\__init__.py" "!DEST!" >nul
if !ERRORLEVEL! neq 0 set "ITEM_FAIL=1"
REM config.py is required: __init__.py imports it, and without it the
REM remote script falls back to built-in defaults with no config file.
copy "%SOURCE%\config.py" "!DEST!" >nul
if !ERRORLEVEL! neq 0 set "ITEM_FAIL=1"
copy "%SOURCE%\version.py" "!DEST!" >nul
if !ERRORLEVEL! neq 0 set "ITEM_FAIL=1"
copy "%SOURCE%\sr_bridge.py" "!DEST!" >nul
if !ERRORLEVEL! neq 0 set "ITEM_FAIL=1"
copy "%SOURCE%\sr_helper.py" "!DEST!" >nul
if !ERRORLEVEL! neq 0 set "ITEM_FAIL=1"
copy "%SOURCE%\Tolk.dll" "!DEST!" >nul
if !ERRORLEVEL! neq 0 set "ITEM_FAIL=1"
copy "%SOURCE%\nvdaControllerClient64.dll" "!DEST!" >nul
if !ERRORLEVEL! neq 0 set "ITEM_FAIL=1"

if "!ITEM_FAIL!"=="1" (
    echo.
    echo ERROR: One or more files failed to copy.
    if "!LAST_RESORT!"=="1" echo Try running this script as Administrator.
    pause
    exit /b 1
)

echo Installed successfully.
echo.

REM --- Sweep stale copies at any other location ---
REM Delayed expansion OFF again: %%P is a path from the resolver and may
REM contain '!'. With it off, %DEST% expands once when the block is parsed,
REM which is exactly right -- DEST does not change inside the loop.
setlocal disabledelayedexpansion
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%RESOLVER%" -List`) do (
    if /i not "%%P"=="%DEST%" (
        echo Removing stale copy at:
        echo   %%P
        rmdir /s /q "%%P" 2>nul
        if exist "%%P" (
            echo   FAILED -- remove it manually, it may override this install.
            echo   ^(a copy under C:\ProgramData needs Administrator rights^)
        ) else (
            echo   Removed.
        )
        echo.
    )
)
endlocal

echo ================================================
echo   Installation complete! (source-only)
echo ================================================
echo.
echo Installed to: !DEST!
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
echo   Config file: %USERPROFILE%\.move_sr_bridge\config.ini
echo     (created automatically on first launch, edit to customise debounce)
echo.
pause
