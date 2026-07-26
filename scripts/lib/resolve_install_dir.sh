#!/bin/bash
# resolve_install_dir.sh - Locate Live's Remote Scripts folder (macOS)
# Copyright (C) 2026 Jeremiah Ticket
# Licensed under GPLv3 -- see LICENSE for details.
#
# Sourced by the macOS install/uninstall/helper scripts.  Mirrors
# scripts/lib/ResolveInstallDir.ps1 (Windows) and the resolver inside
# scripts/installer/mac/Install Move-SR-Bridge.js -- keep the three in
# step, and see CLAUDE.md "Install Location Resolution" for the rationale.
#
# Resolution order:
#   1. MOVE_SR_USER_LIBRARY (explicit override)
#   2. The User Library recorded in Live's own Library.cfg
#   3. The platform-default User Library location
#   4. Inside Live's application bundle -- LAST RESORT ONLY.  That bundle is
#      code-signed with a hardened runtime, so writing into it breaks the
#      signature seal, needs admin rights, and is erased by every Live
#      update.  Only reached if the User Library can neither be found nor
#      created; callers must warn when MSB_LAST_RESORT is set.

PACKAGE_NAME="Move_SR_Bridge"

# ---------------------------------------------------------------------------
# Live's preference folders.  Live leaves old version folders behind
# forever, and version-number order is NOT the same as "most recently
# used" -- a 12.4.5 beta can sit next to a 12.4.3 that is the one
# actually running.  Sort by modification time instead.
# ---------------------------------------------------------------------------
msb_newest_library_cfg() {
    # -t sorts by mtime, newest first.  Piping to head keeps whole lines:
    # these paths contain spaces ("Live 12.4.3"), so a `for` loop over
    # command substitution would split them apart.
    ls -t "$HOME/Library/Preferences/Ableton/"*/Library.cfg \
          "$HOME/Library/Preferences/Ableton/"*/Preferences/Library.cfg \
          2>/dev/null | head -1
}

# Extract the User Library path from Library.cfg.  It is plain XML:
#   <UserLibrary><LibraryProject Id="0">
#     <ProjectName Value="User Library" />
#     <ProjectPath Value="/Users/you/Music/Ableton" />
# The library lives at ProjectPath/ProjectName.
msb_user_library_from_config() {
    local cfg
    cfg="$(msb_newest_library_cfg)"
    [ -n "$cfg" ] || return 1
    [ -r "$cfg" ] || return 1

    # FIRST match wins, matching the lazy regexes the PowerShell and JXA
    # resolvers use.  A plain `sed 's|.*<Tag ...|'` would do the opposite:
    # its leading `.*` is greedy and swallows up to the LAST occurrence, so
    # a cfg with more than one <LibraryProject> made the three disagree.
    # sed has no lazy quantifier, so put one tag per line and take head -1.
    local block name path
    block="$(tr -d '\n\r' < "$cfg" | tr '<' '\n' | awk '
        /^UserLibrary>/  { inblock = 1; next }
        /^\/UserLibrary>/ { if (inblock) exit }
        inblock')"
    [ -n "$block" ] || return 1

    name="$(printf '%s\n' "$block" \
            | sed -n 's|^ProjectName  *Value="\([^"]*\)".*|\1|p' | head -1)"
    path="$(printf '%s\n' "$block" \
            | sed -n 's|^ProjectPath  *Value="\([^"]*\)".*|\1|p' | head -1)"
    [ -n "$path" ] || return 1
    [ -n "$name" ] || name="User Library"

    # Trailing slashes are stripped so the three resolvers build byte-identical
    # paths -- ProjectPath is Live-controlled data and may carry one.
    path="${path%"${path##*[!/]}"}"
    printf '%s/%s\n' "$path" "$name"
}

msb_default_user_library() {
    printf '%s\n' "$HOME/Music/Ableton/User Library"
}

# A User Library the graphical installer was pointed at by hand.
#
# That installer has a "choose a folder" branch (taken when the default
# library cannot be created) which can land the package somewhere no
# resolver would ever derive.  It records the choice here so the sweep and
# the uninstallers can still find that copy -- otherwise it stays on Live's
# search path shadowing every later install.  Absent on any machine that
# never took that branch, which is nearly all of them.
msb_recorded_user_library() {
    local f="$HOME/.move_sr_bridge/install_location"
    [ -f "$f" ] || return 0
    local line
    IFS= read -r line < "$f" 2>/dev/null || return 0
    [ -n "$line" ] || return 0
    msb_strip_trailing_slashes "$line"
}

# Strip trailing slashes so this resolver builds byte-identical paths to
# the PowerShell (Remove-TrailingSeparators) and JXA (stripTrailingSlashes)
# ones.  Applied to MOVE_SR_USER_LIBRARY as well as to Library.cfg data: an
# override the user typed with a trailing slash is exactly as likely as one
# Live wrote, and "/lib//Remote Scripts" made the three disagree
# byte-for-byte.
#
# PowerShell needs its own helper for this and cannot lean on Join-Path,
# which absorbs a single trailing separator but leaves a doubled one in
# place ("C:\lib\\" + "Remote Scripts" keeps both slashes).
msb_strip_trailing_slashes() {
    local p="$1"
    p="${p%"${p##*[!/]}"}"
    printf '%s\n' "$p"
}

# The override, normalised.  Empty output means it is not set.
msb_env_user_library() {
    [ -n "${MOVE_SR_USER_LIBRARY:-}" ] || return 0
    msb_strip_trailing_slashes "$MOVE_SR_USER_LIBRARY"
}

# Live app bundles, newest by mtime first.  Deliberately NOT alphabetical:
# "Ableton Live 9 Trial" sorts after "Ableton Live 11" as a string, so a
# name sort can pick a stale version over the one actually in use.
msb_live_apps_newest_first() {
    ls -td /Applications/Ableton\ Live*.app 2>/dev/null
}

# ---------------------------------------------------------------------------
# Sets MSB_REMOTE_SCRIPTS, MSB_SOURCE and MSB_LAST_RESORT ("1" when the
# answer is inside Live's app bundle).  Returns 1 if nothing usable at all.
#
# Pass "create" as $1 to create the directory when it does not yet exist;
# uninstall and the helper launcher pass nothing, so they never make
# folders just by looking.
# ---------------------------------------------------------------------------
msb_resolve_remote_scripts() {
    local create="${1:-}"
    local lib=""
    MSB_SOURCE=""
    MSB_REMOTE_SCRIPTS=""
    MSB_LAST_RESORT=""

    # 1. Explicit override wins outright, existing or not.
    if [ -n "${MOVE_SR_USER_LIBRARY:-}" ]; then
        MSB_REMOTE_SCRIPTS="$(msb_env_user_library)/Remote Scripts"
        MSB_SOURCE="MOVE_SR_USER_LIBRARY override"
        [ "$create" = "create" ] && mkdir -p "$MSB_REMOTE_SCRIPTS" 2>/dev/null
        [ -d "$MSB_REMOTE_SCRIPTS" ] && return 0
        # An override that cannot be used is an error, not a reason to
        # silently install somewhere the user did not ask for.
        MSB_REMOTE_SCRIPTS=""
        return 1
    fi

    # 2. Whatever Live itself records.
    lib="$(msb_user_library_from_config 2>/dev/null || true)"
    if [ -n "$lib" ] && [ -d "$lib" ]; then
        MSB_REMOTE_SCRIPTS="${lib}/Remote Scripts"
        MSB_SOURCE="Live's Library.cfg"
        [ "$create" = "create" ] && mkdir -p "$MSB_REMOTE_SCRIPTS" 2>/dev/null
        [ -d "$MSB_REMOTE_SCRIPTS" ] && return 0
    fi

    # 3. The documented default.
    lib="$(msb_default_user_library)"
    if [ -d "$lib" ]; then
        MSB_REMOTE_SCRIPTS="${lib}/Remote Scripts"
        MSB_SOURCE="default User Library location"
        [ "$create" = "create" ] && mkdir -p "$MSB_REMOTE_SCRIPTS" 2>/dev/null
        [ -d "$MSB_REMOTE_SCRIPTS" ] && return 0
    fi

    # 3b. No User Library exists yet -- create the default one.  Live picks
    #     it up on next start; this is far preferable to option 4.
    if [ "$create" = "create" ] && mkdir -p "${lib}/Remote Scripts" 2>/dev/null; then
        MSB_REMOTE_SCRIPTS="${lib}/Remote Scripts"
        MSB_SOURCE="newly created default User Library"
        return 0
    fi

    # 4. Last resort: inside Live itself.  See the header for why this is
    #    a bad place to end up.
    # Newest bundle first, but only ones that actually contain a MIDI
    # Remote Scripts folder -- the PowerShell and JXA resolvers both filter
    # on that, and without it install_mac.sh would mkdir -p a path Live may
    # never scan (or abort under `set -e` when it is not writable).
    local app scripts_dir
    while IFS= read -r app; do
        [ -n "$app" ] || continue
        scripts_dir="${app}/Contents/App-Resources/MIDI Remote Scripts"
        if [ -d "$scripts_dir" ]; then
            MSB_REMOTE_SCRIPTS="$scripts_dir"
            MSB_SOURCE="inside Live's application bundle (last resort)"
            MSB_LAST_RESORT="1"
            return 0
        fi
    done < <(msb_live_apps_newest_first)

    MSB_REMOTE_SCRIPTS=""
    MSB_SOURCE=""
    return 1
}

# Every place a copy could be, for uninstall and for migrating away from
# older install locations.
msb_all_candidate_dirs() {
    if [ -n "${MOVE_SR_USER_LIBRARY:-}" ]; then
        printf '%s/Remote Scripts/%s\n' "$(msb_env_user_library)" "$PACKAGE_NAME"
    fi

    local lib
    lib="$(msb_user_library_from_config 2>/dev/null || true)"
    [ -n "$lib" ] && printf '%s/Remote Scripts/%s\n' "$lib" "$PACKAGE_NAME"

    local recorded
    recorded="$(msb_recorded_user_library 2>/dev/null || true)"
    [ -n "$recorded" ] && printf '%s/Remote Scripts/%s\n' "$recorded" "$PACKAGE_NAME"

    printf '%s/Remote Scripts/%s\n' "$(msb_default_user_library)" "$PACKAGE_NAME"

    # Legacy / last-resort: inside Live's application bundle.
    #
    # Through msb_live_apps_newest_first, not a bare glob: a glob expands
    # alphabetically, and this list must agree with the resolver above (and
    # with the PowerShell and JXA implementations, which both mtime-sort)
    # about which Live comes first.  It was the one place in this file that
    # still ordered by name.
    local app
    while IFS= read -r app; do
        [ -d "$app" ] || continue
        printf '%s/Contents/App-Resources/MIDI Remote Scripts/%s\n' \
            "$app" "$PACKAGE_NAME"
    done < <(msb_live_apps_newest_first)
}

# De-duplicated, existing-only candidate list.
msb_installed_dirs() {
    local seen="" d
    while IFS= read -r d; do
        [ -d "$d" ] || continue
        case "$seen" in
            *"|$d|"*) continue ;;
        esac
        seen="${seen}|$d|"
        printf '%s\n' "$d"
    done < <(msb_all_candidate_dirs)
}
