@echo off
REM uninstall.bat - Uninstall Move-SR-Bridge from Ableton Live
REM Copyright (C) 2026 Jeremiah Ticket
REM Licensed under GPLv3 -- see LICENSE for details.
REM
REM Removes Move-SR-Bridge from every location an installer could have put
REM it: the User Library recorded in Live's Library.cfg, the default User
REM Library, and the old C:\ProgramData\Ableton\Live *\Resources\MIDI
REM Remote Scripts trees.  See scripts\lib\ResolveInstallDir.ps1.

setlocal enabledelayedexpansion

echo Move-SR-Bridge Uninstaller
echo ===========================
echo.

set "SCRIPT_PATH=%~dp0"
set "RESOLVER=%SCRIPT_PATH%lib\ResolveInstallDir.ps1"
if not exist "%RESOLVER%" (
    echo ERROR: Cannot find %RESOLVER%
    echo The scripts\lib\ folder is missing from this download.
    pause
    exit /b 1
)

REM --- Enumerate every existing installation ---
REM The resolver is run twice (list, then remove) rather than stashed in a
REM pseudo-array. An array would need delayed expansion for its index, and
REM that would eat any '!' in the paths -- which is legal in a folder name.
REM Delayed expansion stays OFF for both passes.
setlocal disabledelayedexpansion
set "COUNT=0"
echo Installations found:
echo.
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%RESOLVER%" -List`) do (
    set /a COUNT+=1
    echo   %%P
)
endlocal & set "COUNT=%COUNT%"

if "%COUNT%"=="0" (
    echo   ^(none^)
    echo.
    echo Move-SR-Bridge does not appear to be installed.
    echo.
    echo Checked your Ableton User Library and
    echo C:\ProgramData\Ableton\Live *\Resources\MIDI Remote Scripts\
    pause
    exit /b 0
)
echo.

REM Cleared first, and this one matters most: `set /p` leaves the variable
REM untouched on a bare Enter, so a YN=Y inherited from the environment
REM would answer a destructive prompt on the user's behalf.
set "YN="
set /p YN="Remove all of the above? [Y/N]: "
if /i not "%YN%"=="Y" (
    echo Cancelled.
    pause
    exit /b 0
)
echo.

REM --- Kill running sr_helper.exe if found ---
tasklist /FI "IMAGENAME eq sr_helper.exe" 2>nul | find /I "sr_helper.exe" >nul
if !ERRORLEVEL!==0 (
    echo Detected running sr_helper.exe process.
    echo Terminating sr_helper.exe...
    taskkill /F /IM sr_helper.exe >nul 2>&1
    echo sr_helper.exe terminated.
    echo.
)

REM --- Remove (second resolver pass; see the note above) ---
setlocal disabledelayedexpansion
set "REMOVED=0"
set "FAIL=0"
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%RESOLVER%" -List`) do (
    echo Removing: %%P
    rmdir /s /q "%%P" 2>nul
    if exist "%%P" (
        echo   FAILED. A copy under C:\ProgramData needs Administrator rights.
        set "FAIL=1"
    ) else (
        echo   Done.
        set /a REMOVED+=1
    )
)
endlocal & set "REMOVED=%REMOVED%" & set "FAIL=%FAIL%"
echo.

if "%FAIL%"=="1" (
    echo Uninstall completed with errors -- see above.
    echo Re-run this script as Administrator to remove the rest.
    pause
    exit /b 1
)

echo ================================================
echo   Uninstallation complete!
echo ================================================
echo.
echo Removed Move-SR-Bridge from %REMOVED% location^(s^).
echo.

REM --- Offer to remove the settings/log folder ---
REM uninstall_mac.sh and the graphical installer both ask.  This one used to
REM tell the user to do it by hand, so the same uninstall left different
REM state behind depending on which platform you ran it on.
if exist "%USERPROFILE%\.move_sr_bridge" (
    echo Your settings and log are at:
    echo   %USERPROFILE%\.move_sr_bridge
    echo.
    REM Cleared first, as with the YN prompt above.
    set "DELCFG="
    set /p DELCFG="Remove them too? [Y/N]: "
    if /i "!DELCFG!"=="Y" (
        rmdir /s /q "%USERPROFILE%\.move_sr_bridge" 2>nul
        if exist "%USERPROFILE%\.move_sr_bridge" (
            echo   FAILED -- remove it by hand.
        ) else (
            echo   Removed.
        )
    ) else (
        echo   Kept.
    )
    echo.
)

pause
