@echo off
REM uninstall.bat - Uninstall Move-SR-Bridge from Ableton Live
REM Copyright (C) 2026 Jeremiah Ticket
REM Licensed under GPLv3 -- see LICENSE for details.

setlocal enabledelayedexpansion

echo Move-SR-Bridge Uninstaller
echo ===========================
echo.
echo This script will remove Move-SR-Bridge from Ableton Live's MIDI Remote Scripts folder.
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
    echo Nothing to uninstall.
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

REM --- Build list of targets ---
if /i "!SEL!"=="A" (
    set "FIRST=1"
    set "LAST=%COUNT%"
) else (
    set "FIRST=!SEL!"
    set "LAST=!SEL!"
)

REM --- Kill running sr_helper.exe if found ---
tasklist /FI "IMAGENAME eq sr_helper.exe" 2>nul | find /I "sr_helper.exe" >nul
if !ERRORLEVEL!==0 (
    echo Detected running sr_helper.exe process.
    echo Terminating sr_helper.exe...
    taskkill /F /IM sr_helper.exe >nul 2>&1
    echo sr_helper.exe terminated.
    echo.
)

REM --- Remove from each selected target ---
set "REMOVED=0"
for /l %%I in (!FIRST!,1,!LAST!) do (
    set "DEST=!SCRIPTS_%%I!\Move_SR_Bridge"
    echo.

    if not exist "!DEST!" (
        echo Move-SR-Bridge is not installed in !NAME_%%I!. Skipping.
    ) else (
        echo Found Move-SR-Bridge in !NAME_%%I!:
        echo   !DEST!
        echo.
        set /p YN="Remove Move-SR-Bridge from !NAME_%%I!? [Y/N]: "
        if /i "!YN!"=="Y" (
            rmdir /s /q "!DEST!"
            if !ERRORLEVEL! neq 0 (
                echo ERROR: Failed to remove !DEST!. Try running as Administrator.
            ) else (
                echo Removed from !NAME_%%I! successfully.
                set /a REMOVED+=1
            )
        ) else (
            echo Skipped !NAME_%%I!.
        )
    )
)

echo.
if !REMOVED! gtr 0 (
    echo ================================================
    echo   Uninstallation complete!
    echo ================================================
    echo.
    echo Removed Move-SR-Bridge from !REMOVED! installation^(s^).
) else (
    echo No installations were removed.
)
echo.
pause
