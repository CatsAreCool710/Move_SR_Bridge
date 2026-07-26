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
REM
REM Installed copies are found through the same resolver the installer
REM uses (scripts\lib\ResolveInstallDir.ps1), so this follows Live's
REM Library.cfg and finds the helper wherever the install actually landed.

REM No delayed expansion: paths from the resolver may contain '!'.
setlocal

echo Move-SR-Bridge Helper (manual launch)
echo =======================================
echo.
echo This will start the screen reader helper with a visible console window.
echo You can see status messages and any errors here.
echo.
echo The helper will listen on 127.0.0.1:8765 and forward speech/braille
echo to your active screen reader (NVDA, JAWS, ZoomText, etc.).
echo.

set "SCRIPT_PATH=%~dp0"
for %%I in ("%SCRIPT_PATH%..") do set "PROJECT_ROOT=%%~fI"
set "SOURCE_HELPER=%PROJECT_ROOT%\Move_SR_Bridge\sr_helper.py"

REM --- Prefer the project source copy ---
set "HELPER="
if exist "%SOURCE_HELPER%" (
    set "HELPER=%SOURCE_HELPER%"
    goto :found
)

REM --- Fall back to whatever is installed ---
set "RESOLVER=%SCRIPT_PATH%lib\ResolveInstallDir.ps1"
if not exist "%RESOLVER%" (
    echo ERROR: Cannot find sr_helper.py
    echo Checked: %SOURCE_HELPER%
    echo.
    echo The scripts\lib\ folder is missing, so installed copies cannot
    echo be located either.
    pause
    exit /b 1
)

REM Discovery deliberately avoids delayed expansion and numbered variables.
REM `set "HELPER_!COUNT!=%%P"` would need it, and delayed expansion eats any
REM '!' in a path -- legal in a Windows folder name. Instead each resolver
REM line is handed to a :count / :pick subroutine, where plain %VAR% is
REM re-expanded on every call, giving the same result with no '!' hazard.
set "COUNT=0"
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%RESOLVER%" -List`) do call :count "%%P"

if "%COUNT%"=="0" (
    echo ERROR: Cannot find sr_helper.py
    echo Checked:
    echo   %SOURCE_HELPER%
    echo   your Ableton User Library's Remote Scripts folder
    echo   C:\ProgramData\Ableton\Live *\Resources\MIDI Remote Scripts\
    pause
    exit /b 1
)

if "%COUNT%"=="1" (
    set "SEL=1"
    goto :choose
)

echo Found multiple installed helpers:
set "N=0"
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%RESOLVER%" -List`) do call :show "%%P"
echo.

REM Check for command-line argument
if not "%~1"=="" (
    set "SEL=%~1"
    echo Using command-line selection: %~1
    goto :validate_helper
)

set "SEL="
set /p SEL="Select number [1-%COUNT%]: "

:validate_helper
REM Reject anything that is not a plain number in range. findstr does the
REM digits-only check; the numeric comparison then needs no expansion tricks.
echo %SEL%| findstr /r /c:"^[1-9][0-9]*$" >nul
if errorlevel 1 goto :badsel
if %SEL% GTR %COUNT% goto :badsel
goto :choose

:badsel
echo ERROR: Invalid selection "%SEL%". Please enter 1-%COUNT%.
pause
exit /b 1

:choose
set "HELPER="
set "N=0"
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%RESOLVER%" -List`) do call :pick "%%P"
if not defined HELPER (
    echo ERROR: Could not resolve selection %SEL%.
    pause
    exit /b 1
)
goto :found

:count
if exist "%~1\sr_helper.py" set /a COUNT+=1
goto :eof

:show
if not exist "%~1\sr_helper.py" goto :eof
set /a N+=1
echo   %N%. %~1\sr_helper.py
goto :eof

:pick
if not exist "%~1\sr_helper.py" goto :eof
set /a N+=1
if "%N%"=="%SEL%" set "HELPER=%~1\sr_helper.py"
goto :eof

:found
echo Using: %HELPER%
echo.

REM --- Prompt for confirmation ---
REM Cleared first -- see install.bat: an inherited CONFIRM would cancel.
set "CONFIRM="
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
