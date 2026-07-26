<#
.SYNOPSIS
    Locate Live's Remote Scripts folder (Windows).

.DESCRIPTION
    Copyright (C) 2026 Jeremiah Ticket
    Licensed under GPLv3 -- see LICENSE for details.

    Called by the Windows .bat installers.  Mirrors
    scripts/lib/resolve_install_dir.sh (macOS) and the resolver inside
    scripts/installer/mac/Install Move-SR-Bridge.js -- keep the three in
    step, and see CLAUDE.md "Install Location Resolution" for the rationale.

    Resolution order:
      1. MOVE_SR_USER_LIBRARY (explicit override)
      2. The User Library recorded in Live's own Library.cfg
      3. The platform-default User Library location
      4. Inside Live's shared program data -- LAST RESORT ONLY.  That tree
         needs Administrator rights and is rewritten by Live updates, and
         one copy only serves the one Live version it was written into.

    Batch cannot parse XML, so all of this lives here.  Output is
    KEY=VALUE lines, parsed by the callers with:
      for /f "usebackq tokens=1* delims==" %%A in (`...`) do ...

.PARAMETER List
    Instead of resolving, print every existing installation directory,
    one per line (used by the uninstaller and the helper launcher).

.PARAMETER Create
    Create the resolved directory if it does not exist.  Without this the
    script only looks; uninstall must never create folders.
#>
[CmdletBinding()]
param(
    [switch]$List,
    [switch]$Create
)

$ErrorActionPreference = 'Stop'
$PackageName = 'Move_SR_Bridge'

# ---------------------------------------------------------------------------
# Both ProjectPath (read out of Live's Library.cfg) and MOVE_SR_USER_LIBRARY
# (typed by a user) are outside-controlled and may carry a trailing
# separator.  All three implementations of this algorithm must build the
# same string from the same inputs, because "is this the copy I just
# installed?" is a plain string comparison against the sweep list.
#
# Join-Path is NOT sufficient on its own: it absorbs one trailing separator
# but not two, so 'C:\lib\\' + 'Remote Scripts' keeps the doubled separator
# and stops matching what the shell and JXA implementations produce.  Strip
# first, exactly like msb_strip_trailing_slashes and stripTrailingSlashes.
# ---------------------------------------------------------------------------
function Remove-TrailingSeparators {
    param([string]$Path)
    if ([string]::IsNullOrEmpty($Path)) { return $Path }
    $trimmed = $Path.TrimEnd('\', '/')
    # A bare root ("C:\", "\") trims away to nothing or to a drive letter with
    # no separator; keep the original rather than emit something unusable.
    if ([string]::IsNullOrEmpty($trimmed) -or $trimmed -match '^[A-Za-z]:$') {
        return $Path
    }
    return $trimmed
}

# ---------------------------------------------------------------------------
# Live's preference folders.  Live leaves old version folders behind
# forever, and version-number order is NOT the same as "most recently
# used" -- a 12.4.5 beta can sit next to a 12.4.3 that is the one actually
# running.  Sort by LastWriteTime instead.
#
# Windows puts Library.cfg one level deeper than macOS
# (%APPDATA%\Ableton\Live 12.x.x\Preferences\Library.cfg), but older
# layouts kept it at the top, so look in both.
# ---------------------------------------------------------------------------
function Get-NewestLibraryCfg {
    # $env:APPDATA is always set on Windows, but guard anyway: Join-Path
    # throws on a null Path, and that escaped as a raw PowerShell error with
    # no ERROR= line, leaving the caller with nothing useful to print.
    if (-not $env:APPDATA) { return $null }
    $roots = @(
        (Join-Path $env:APPDATA 'Ableton\Live *\Preferences\Library.cfg'),
        (Join-Path $env:APPDATA 'Ableton\Live *\Library.cfg')
    )
    $found = @()
    foreach ($r in $roots) {
        try {
            $found += Get-ChildItem -Path $r -File -ErrorAction SilentlyContinue
        } catch { }
    }
    if ($found.Count -eq 0) { return $null }
    return ($found | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
}

# Library.cfg is plain XML:
#   <UserLibrary><LibraryProject Id="0">
#     <ProjectName Value="User Library" />
#     <ProjectPath Value="C:\Users\you\Documents\Ableton" />
# The library lives at ProjectPath\ProjectName.
function Get-UserLibraryFromConfig {
    $cfg = Get-NewestLibraryCfg
    if (-not $cfg) { return $null }

    $text = $null
    try { $text = Get-Content -Raw -LiteralPath $cfg -ErrorAction Stop } catch { return $null }
    if (-not $text) { return $null }

    $name = $null
    $path = $null

    # Structured parse first; fall back to regex if Live ever ships a file
    # the XML parser chokes on (a stray entity, a truncated write).
    #
    # GetAttribute('Value') rather than $node.ProjectName.Value. Both work
    # (PowerShell's XML adapter surfaces the attribute), but GetAttribute is
    # explicit rather than relying on adapter behaviour, and it does not
    # depend on there being no child element called "Value".
    try {
        $xml = [xml]$text
        $nameNode = $xml.SelectSingleNode('//UserLibrary/LibraryProject/ProjectName')
        $pathNode = $xml.SelectSingleNode('//UserLibrary/LibraryProject/ProjectPath')
        if ($nameNode) { $name = $nameNode.GetAttribute('Value') }
        if ($pathNode) { $path = $pathNode.GetAttribute('Value') }
    } catch { }

    if (-not $path) {
        # [\r\n], not \r?\n: a lone CR is a line break too, and treating it
        # as content would leave the whole file on one "line" here while the
        # shell's `tr -d '\n\r'` handled it. Same input, same result, in all
        # three implementations.
        $flat = $text -replace '[\r\n]', ''
        if ($flat -match '<UserLibrary>(.*?)</UserLibrary>') {
            $block = $Matches[1]
            if ($block -match '<ProjectName\s+Value="([^"]*)"') { $name = $Matches[1] }
            if ($block -match '<ProjectPath\s+Value="([^"]*)"') { $path = $Matches[1] }
        }
    }

    if (-not $path) { return $null }
    if (-not $name) { $name = 'User Library' }
    return (Join-Path (Remove-TrailingSeparators $path) $name)
}

# A User Library the macOS graphical installer was pointed at by hand.
#
# Only that installer has a "choose a folder" branch, so this file will not
# exist on a Windows-only machine.  It is read here anyway so all three
# implementations share one candidate list: a User Library on a synced or
# shared volume can be reachable from both platforms, and a copy that only
# one uninstaller can see is exactly the stale-shadow problem the sweep
# exists to prevent.
function Get-RecordedUserLibrary {
    $f = Join-Path $env:USERPROFILE '.move_sr_bridge\install_location'
    if (-not (Test-Path -LiteralPath $f)) { return $null }
    try {
        $line = (Get-Content -LiteralPath $f -TotalCount 1 -ErrorAction Stop)
    } catch { return $null }
    if (-not $line) { return $null }
    $line = $line.Trim()
    if (-not $line) { return $null }
    return (Remove-TrailingSeparators $line)
}

# GetFolderPath('MyDocuments') follows OneDrive's Known Folder redirection.
# Hardcoding %USERPROFILE%\Documents would point at an empty stub folder on
# any machine where OneDrive has taken Documents over -- which is the
# default on a lot of Windows 11 installs, and the main reason Library.cfg
# matters more here than on macOS.
function Get-DefaultUserLibrary {
    $docs = [Environment]::GetFolderPath('MyDocuments')
    if (-not $docs -and $env:USERPROFILE) {
        $docs = Join-Path $env:USERPROFILE 'Documents'
    }
    if (-not $docs) { return $null }
    return (Join-Path $docs 'Ableton\User Library')
}

# Shared program-data trees, newest first.  Last resort only.
function Get-LiveProgramDataScriptDirs {
    if (-not $env:ProgramData) { return @() }
    $base = Join-Path $env:ProgramData 'Ableton'
    if (-not (Test-Path -LiteralPath $base)) { return @() }
    $dirs = @()
    try {
        # @(...) so a single result stays an array and no result stays empty
        # rather than collapsing to $null.
        $dirs = @(Get-ChildItem -Path (Join-Path $base 'Live *') -Directory -ErrorAction SilentlyContinue |
                  Sort-Object LastWriteTime -Descending)
    } catch { return @() }
    $out = @()
    foreach ($d in $dirs) {
        $s = Join-Path $d.FullName 'Resources\MIDI Remote Scripts'
        if (Test-Path -LiteralPath $s) { $out += $s }
    }
    return $out
}

# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------
if ($List) {
    # A plain hashtable: PowerShell hashtable keys are case-insensitive,
    # which is what we want for Windows paths.
    $seen = @{}
    $candidates = @()

    if ($env:MOVE_SR_USER_LIBRARY) {
        $candidates += (Join-Path (Remove-TrailingSeparators $env:MOVE_SR_USER_LIBRARY) "Remote Scripts\$PackageName")
    }
    $fromCfg = Get-UserLibraryFromConfig
    if ($fromCfg) { $candidates += (Join-Path $fromCfg "Remote Scripts\$PackageName") }
    $recorded = Get-RecordedUserLibrary
    if ($recorded) { $candidates += (Join-Path $recorded "Remote Scripts\$PackageName") }
    $defaultLib = Get-DefaultUserLibrary
    if ($defaultLib) {
        $candidates += (Join-Path $defaultLib "Remote Scripts\$PackageName")
    }
    foreach ($s in @(Get-LiveProgramDataScriptDirs)) {
        $candidates += (Join-Path $s $PackageName)
    }

    foreach ($c in $candidates) {
        if ($seen.ContainsKey($c)) { continue }
        $seen[$c] = $true
        if (Test-Path -LiteralPath $c) { Write-Output $c }
    }
    exit 0
}

$resolved = $null
$source = $null
$lastResort = $false

# 1. Explicit override wins outright.  An override that cannot be used is
#    an error, not a reason to install somewhere the user did not ask for.
if ($env:MOVE_SR_USER_LIBRARY) {
    $resolved = Join-Path (Remove-TrailingSeparators $env:MOVE_SR_USER_LIBRARY) 'Remote Scripts'
    $source = 'MOVE_SR_USER_LIBRARY override'
    if ($Create) { New-Item -ItemType Directory -Force -Path $resolved -ErrorAction SilentlyContinue | Out-Null }
    if (-not (Test-Path -LiteralPath $resolved)) {
        Write-Output 'ERROR=MOVE_SR_USER_LIBRARY is set but that folder does not exist'
        exit 1
    }
}

# 2. Whatever Live itself records.
if (-not $resolved) {
    $lib = Get-UserLibraryFromConfig
    if ($lib -and (Test-Path -LiteralPath $lib)) {
        $candidate = Join-Path $lib 'Remote Scripts'
        if ($Create) { New-Item -ItemType Directory -Force -Path $candidate -ErrorAction SilentlyContinue | Out-Null }
        if (Test-Path -LiteralPath $candidate) {
            $resolved = $candidate
            $source = "Live's Library.cfg"
        }
    }
}

# 3. The documented default.
$default = Get-DefaultUserLibrary
if (-not $resolved -and $default) {
    if (Test-Path -LiteralPath $default) {
        $candidate = Join-Path $default 'Remote Scripts'
        if ($Create) { New-Item -ItemType Directory -Force -Path $candidate -ErrorAction SilentlyContinue | Out-Null }
        if (Test-Path -LiteralPath $candidate) {
            $resolved = $candidate
            $source = 'default User Library location'
        }
    }
}

# 3b. No User Library exists yet -- create the default one.  Live picks it
#     up on next start; far preferable to step 4.
if (-not $resolved -and $Create -and $default) {
    $candidate = Join-Path $default 'Remote Scripts'
    New-Item -ItemType Directory -Force -Path $candidate -ErrorAction SilentlyContinue | Out-Null
    if (Test-Path -LiteralPath $candidate) {
        $resolved = $candidate
        $source = 'newly created default User Library'
    }
}

# 4. Last resort: Live's own shared program data.  Needs Administrator,
#    is rewritten by Live updates, and covers only that one Live version.
if (-not $resolved) {
    $dirs = @(Get-LiveProgramDataScriptDirs)
    if ($dirs.Count -gt 0) {
        $resolved = $dirs[0]
        $source = "inside Live's program data (last resort)"
        $lastResort = $true
    }
}

if (-not $resolved) {
    Write-Output 'ERROR=Could not locate an Ableton User Library or Live installation'
    exit 1
}

Write-Output "PATH=$resolved"
Write-Output "SOURCE=$source"
if ($lastResort) { Write-Output 'LASTRESORT=1' }
exit 0
