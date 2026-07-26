// Install Move-SR-Bridge.js -- JXA installer for macOS
// Copyright (C) 2026 Jeremiah Ticket
// Licensed under GPLv3 -- see LICENSE for details.
//
// Compiled into a .app bundle via osacompile (see build.sh).
// Uses macOS system dialogs which are fully VoiceOver accessible.
//
// Installs into the Ableton User Library's "Remote Scripts" folder, whose
// location is read from Live's own Library.cfg where possible.  This
// mirrors scripts/lib/resolve_install_dir.sh and
// scripts/lib/ResolveInstallDir.ps1 -- keep the three in step, and see
// CLAUDE.md "Install Location Resolution" for the rationale.
//
// Installing inside Live's application bundle is the last resort only.
// That bundle is code-signed with a hardened runtime, so writing into it
// breaks the signature seal, needs admin rights, and -- most importantly
// -- is wiped by every Live update.  The User Library is per-user, always
// writable, and survives updates.

var PACKAGE_NAME = "Move_SR_Bridge";
var USER_LIBRARY_DEFAULT = "/Music/Ableton/User Library";
var REMOTE_SCRIPTS_DIRNAME = "Remote Scripts";
var TITLE_INSTALL = "Move-SR-Bridge Installer";
var TITLE_UNINSTALL = "Move-SR-Bridge Uninstaller";

function run(argv) {
    var app = Application.currentApplication();
    app.includeStandardAdditions = true;

    // The package is embedded inside this app's own bundle -- self-contained,
    // no sibling folder required.
    var packageSrc = getResourcesDir() + "/" + PACKAGE_NAME;

    // Verify the embedded package exists
    var fm = $.NSFileManager.defaultManager;
    if (!fm.fileExistsAtPath(packageSrc)) {
        app.displayDialog(
            "This installer appears to be incomplete: the Move_SR_Bridge " +
                "package is missing from the app bundle.\n\n" +
                "Please re-download the installer.",
            {
                withTitle: TITLE_INSTALL,
                buttons: ["OK"],
                defaultButton: 1,
            }
        );
        return;
    }

    // Main menu: Install or Uninstall?
    var mainChoice;
    try {
        mainChoice = app.displayDialog(
            "Move-SR-Bridge Installer\n\n" +
                "Ableton Move screen reader support.\n" +
                "Would you like to install or uninstall?",
            {
                withTitle: "Move-SR-Bridge",
                buttons: ["Install", "Uninstall", "Cancel"],
                defaultButton: 1,
                cancelButton: 3,
            }
        );
    } catch (e) {
        return; // Cancelled
    }

    if (mainChoice.buttonReturned === "Install") {
        doInstall(app, fm, packageSrc);
    } else if (mainChoice.buttonReturned === "Uninstall") {
        doUninstall(app, fm);
    }
}

// ---------------------------------------------------------------------------
//  Installation
// ---------------------------------------------------------------------------
function doInstall(app, fm, packageSrc) {
    // Live only scans Remote Scripts at startup, so it must be restarted
    // for the install to take effect either way.
    if (isLiveRunning(app)) {
        return;
    }

    var resolved = resolveRemoteScriptsDir(app);
    if (resolved === null) return;

    var dest = resolved.path + "/" + PACKAGE_NAME;

    // Confirm
    try {
        app.displayDialog(
            "This will install Move-SR-Bridge to:\n\n" +
                dest +
                "\n\n(Located by: " +
                resolved.source +
                ")\n\nContinue?",
            {
                withTitle: TITLE_INSTALL,
                buttons: ["Install", "Cancel"],
                defaultButton: 1,
                cancelButton: 2,
            }
        );
    } catch (e) {
        return;
    }

    // A helper left over from a previous session would keep port 8765 and
    // go on running the old binary after we replace the files.
    stopHelper(app);

    // A last-resort install lands inside a root-owned app bundle, so the
    // copy itself needs the authorisation prompt too.
    //
    // Staged rather than in place, matching install_mac.sh.  The old copy
    // is only removed once the new one is complete and sitting beside it,
    // so a failure part-way through cannot leave the user with the old
    // install deleted and no new one -- which "rm -rf dest && cp -R" did
    // whenever the rm was permitted and the cp was not.
    var stage = dest + ".new." + $.NSProcessInfo.processInfo.processIdentifier;
    var backup = dest + ".old." + $.NSProcessInfo.processInfo.processIdentifier;
    var copyCmd =
        "set -e; " +
        "rm -rf " + shQuote(stage) + " " + shQuote(backup) + "; " +
        "cp -R " + shQuote(packageSrc) + " " + shQuote(stage) + "; " +
        "rm -rf " + shQuote(stage) + "/__pycache__; " +
        "chmod +x " + shQuote(stage + "/sr_helper_mac") + " 2>/dev/null || true; " +
        // Swap only now that the new copy is known good.  If the final
        // move fails, put the old one back rather than leaving nothing.
        "if [ -d " + shQuote(dest) + " ]; then " +
        "mv " + shQuote(dest) + " " + shQuote(backup) + "; fi; " +
        "if mv " + shQuote(stage) + " " + shQuote(dest) + "; then " +
        "rm -rf " + shQuote(backup) + "; " +
        "else " +
        "if [ -d " + shQuote(backup) + " ]; then mv " + shQuote(backup) + " " +
        shQuote(dest) + "; fi; " +
        "rm -rf " + shQuote(stage) + "; exit 1; " +
        "fi";

    if (!runPrivileged(app, copyCmd, resolved.lastResort,
                       "Move-SR-Bridge needs permission to install inside " +
                       "Ableton Live's application folder.")) {
        app.displayDialog(
            "Move-SR-Bridge could not be installed to:\n\n" + dest,
            {
                withTitle: TITLE_INSTALL,
                buttons: ["OK"],
                defaultButton: 1,
            }
        );
        return;
    }

    // Any copy at a different location must go: two packages with the same
    // name on Live's script search path is ambiguous, and the stale one
    // would keep shadowing this install.
    var sweep = removeStaleInstalls(app, fm, dest);

    var msg = "Move-SR-Bridge installed successfully!\n\n";
    msg += "Installed to:\n  " + dest + "\n";
    msg += "Located by: " + resolved.source + "\n\n";

    if (resolved.lastResort) {
        msg +=
            "WARNING: this copy is inside Live's application bundle and\n" +
            "will be erased by the next Live update. Reinstall after each\n" +
            "one, or open Live once to create your User Library and run\n" +
            "this installer again.\n\n";
    }

    if (sweep.removed.length > 0) {
        msg += "Removed stale copies from:\n";
        for (var i = 0; i < sweep.removed.length; i++) {
            msg += "  " + sweep.removed[i] + "\n";
        }
        msg += "\n";
    }
    if (sweep.failed.length > 0) {
        msg +=
            "WARNING: an old copy is still on Live's search path and may\n" +
            "override this install. Remove it manually:\n";
        for (var i = 0; i < sweep.failed.length; i++) {
            msg += "  " + sweep.failed[i] + "\n";
        }
        msg += "\n";
    }

    msg +=
        "To use:\n" +
        "  1. Open Ableton Live\n" +
        "  2. Go to Settings > Link, Tempo & MIDI\n" +
        "  3. Select 'Move_SR_Bridge' as your Control Surface\n" +
        "  4. Connect your Move via USB\n\n" +
        "VoiceOver setup (required):\n" +
        "  1. Enable VoiceOver (Cmd+F5)\n" +
        "  2. Open VoiceOver Utility (VO+F8)\n" +
        "  3. Go to General > check 'Allow VoiceOver to be\n" +
        "     controlled with AppleScript'\n\n" +
        "Config file: ~/.move_sr_bridge/config.ini\n" +
        "  (created on first Live launch -- edit to customise\n" +
        "   debounce and logging settings)\n\n" +
        "Log file: ~/.move_sr_bridge/Move_SR_Bridge.log";

    app.displayDialog(msg, {
        withTitle: TITLE_INSTALL,
        buttons: ["OK"],
        defaultButton: 1,
    });
}

// ---------------------------------------------------------------------------
//  Uninstallation
// ---------------------------------------------------------------------------
function doUninstall(app, fm) {
    if (isLiveRunning(app)) {
        return;
    }

    // Gather every place a copy could live -- the same candidate list the
    // installer resolves against, so a relocated User Library is covered.
    var targets = installedPackageDirs(app, fm);

    if (targets.length === 0) {
        var checked = candidatePackageDirs(app);
        app.displayDialog(
            "Move-SR-Bridge does not appear to be installed.\n\n" +
                "Checked:\n  " +
                checked.join("\n  "),
            {
                withTitle: TITLE_UNINSTALL,
                buttons: ["OK"],
                defaultButton: 1,
            }
        );
        return;
    }

    var confirmMsg = "Remove Move-SR-Bridge from:\n\n";
    for (var i = 0; i < targets.length; i++) {
        confirmMsg += "  " + targets[i].label + "\n";
    }
    confirmMsg += "\nContinue?";

    try {
        app.displayDialog(confirmMsg, {
            withTitle: TITLE_UNINSTALL,
            buttons: ["Remove", "Cancel"],
            defaultButton: 1,
            cancelButton: 2,
        });
    } catch (e) {
        return;
    }

    stopHelper(app);

    var removed = [];
    var failed = [];
    for (var i = 0; i < targets.length; i++) {
        if (removePath(app, targets[i].path, targets[i].inBundle)) {
            removed.push(targets[i].label);
        } else {
            failed.push(targets[i].label);
        }
    }

    // Ask about the config file. "Keep Config" is also the cancel button, so
    // Escape/Return-on-default and clicking "Keep Config" all take the same
    // safe no-delete path via the catch block below.
    var configDir = ObjC.unwrap($.NSHomeDirectory()) + "/.move_sr_bridge";
    if (fm.fileExistsAtPath(configDir)) {
        try {
            var configChoice = app.displayDialog(
                "Also remove the settings and log folder?\n" + configDir,
                {
                    withTitle: TITLE_UNINSTALL,
                    buttons: ["Remove Settings", "Keep Settings"],
                    defaultButton: 2,
                    cancelButton: 2,
                }
            );
            if (configChoice.buttonReturned === "Remove Settings") {
                doShell(app, "rm -rf " + shQuote(configDir));
            }
        } catch (e) {
            // Keep settings (cancelled / "Keep Settings" clicked)
        }
    }

    var msg =
        failed.length === 0
            ? "Move-SR-Bridge uninstalled successfully!\n\n"
            : "Move-SR-Bridge uninstalled with some errors.\n\n";

    if (removed.length > 0) {
        msg += "Removed from:\n";
        for (var i = 0; i < removed.length; i++) {
            msg += "  " + removed[i] + "\n";
        }
    }
    if (failed.length > 0) {
        msg += "\nFailed to remove from:\n";
        for (var i = 0; i < failed.length; i++) {
            msg += "  " + failed[i] + "\n";
        }
        msg += "\nRemove these manually.";
    }

    app.displayDialog(msg, {
        withTitle: TITLE_UNINSTALL,
        buttons: ["OK"],
        defaultButton: 1,
    });
}

// ---------------------------------------------------------------------------
//  User Library resolution
//
//  Order: MOVE_SR_USER_LIBRARY -> Live's Library.cfg -> the default
//  location -> create the default -> ask the user -> inside Live itself.
//  The last step is a genuine last resort; see the file header.
// ---------------------------------------------------------------------------
function defaultUserLibrary() {
    return ObjC.unwrap($.NSHomeDirectory()) + USER_LIBRARY_DEFAULT;
}

// Where a hand-picked User Library gets recorded.
//
// Only this installer can end up somewhere none of the three resolvers
// would ever derive on their own -- the "choose a folder" branch, taken
// when the default library cannot be created.  Without a record, that copy
// is invisible to every uninstaller and to the next install's stale sweep,
// so it sits on Live's search path shadowing the new package forever.
// Written here, read by all three implementations.
var RECORDED_LIBRARY_FILE =
    ObjC.unwrap($.NSHomeDirectory()) + "/.move_sr_bridge/install_location";

function recordChosenLibrary(app, lib) {
    try {
        doShell(
            app,
            "mkdir -p " +
                shQuote(ObjC.unwrap($.NSHomeDirectory()) + "/.move_sr_bridge") +
                " && printf '%s\\n' " +
                shQuote(lib) +
                " > " +
                shQuote(RECORDED_LIBRARY_FILE)
        );
    } catch (e) {
        // Not fatal: the install itself succeeded, and the only cost is
        // that a later uninstall will not find this copy automatically.
    }
}

function recordedUserLibrary() {
    try {
        var fm = $.NSFileManager.defaultManager;
        if (!fm.fileExistsAtPath(RECORDED_LIBRARY_FILE)) return null;
        var text = ObjC.unwrap(
            $.NSString.stringWithContentsOfFileEncodingError(
                RECORDED_LIBRARY_FILE,
                $.NSUTF8StringEncoding,
                null
            )
        );
        if (!text) return null;
        var line = String(text).split(/[\r\n]+/)[0].trim();
        return line ? stripTrailingSlashes(line) : null;
    } catch (e) {
        return null;
    }
}

function envUserLibrary() {
    try {
        var v = ObjC.unwrap(
            $.NSProcessInfo.processInfo.environment.objectForKey(
                "MOVE_SR_USER_LIBRARY"
            )
        );
        return v ? stripTrailingSlashes(String(v)) : null;
    } catch (e) {
        return null;
    }
}

// Live never deletes old preference folders, and version-number order is
// NOT the same as "most recently used" -- a 12.4.5 beta can sit next to a
// 12.4.3 that is the one actually running.  Sort by modification time.
//
// `ls -t | head -1` rather than NSFileManager attribute sorting: these
// paths contain spaces, and shelling out matches the .sh resolver exactly.
function newestLibraryCfg(app) {
    var prefs = ObjC.unwrap($.NSHomeDirectory()) + "/Library/Preferences/Ableton";
    try {
        var out = doShell(
            app,
            "ls -t " +
                shQuote(prefs) +
                "/*/Library.cfg " +
                shQuote(prefs) +
                "/*/Preferences/Library.cfg 2>/dev/null | head -1"
        );
        out = String(out).trim();
        return out === "" ? null : out;
    } catch (e) {
        return null;
    }
}

// Library.cfg is plain XML:
//   <UserLibrary><LibraryProject Id="0">
//     <ProjectName Value="User Library" />
//     <ProjectPath Value="/Users/you/Music/Ableton" />
// The library lives at ProjectPath/ProjectName.
function userLibraryFromConfig(app) {
    var cfg = newestLibraryCfg(app);
    if (!cfg) return null;

    var text = ObjC.unwrap(
        $.NSString.stringWithContentsOfFileEncodingError(
            cfg,
            $.NSUTF8StringEncoding,
            null
        )
    );
    if (!text) return null;

    // [\r\n], not \r?\n: a lone CR is a line break too, and treating it as
    // content would leave the whole file on one "line" here while the
    // shell's `tr -d '\n\r'` handled it. Same input, same result, in all
    // three implementations.
    var flat = String(text).replace(/[\r\n]/g, "");
    var block = flat.match(/<UserLibrary>([\s\S]*?)<\/UserLibrary>/);
    if (!block) return null;

    var pathMatch = block[1].match(/<ProjectPath\s+Value="([^"]*)"/);
    if (!pathMatch) return null;
    var nameMatch = block[1].match(/<ProjectName\s+Value="([^"]*)"/);
    var name = nameMatch ? nameMatch[1] : "User Library";

    // Strip BEFORE joining, not after: ProjectPath is Live-controlled data
    // and may carry a trailing slash, which would otherwise survive in the
    // middle of the result as "/path//User Library". The .sh and .ps1
    // resolvers both produce a single separator there, and the three are
    // required to build byte-identical paths.
    return stripTrailingSlashes(stripTrailingSlashes(pathMatch[1]) + "/" + name);
}

function stripTrailingSlashes(p) {
    while (p.length > 1 && p.charAt(p.length - 1) === "/") {
        p = p.substring(0, p.length - 1);
    }
    return p;
}

// Try to create dir; return true on success.
function ensureDir(app, path) {
    try {
        doShell(app, "mkdir -p " + shQuote(path));
        return dirExists(app, path);
    } catch (e) {
        return false;
    }
}

// Returns {path: <Remote Scripts dir>, source: <how we found it>,
// lastResort: bool}, or null if the user cancelled.
function resolveRemoteScriptsDir(app) {
    var override = envUserLibrary();
    if (override) {
        var dir = stripTrailingSlashes(override) + "/" + REMOTE_SCRIPTS_DIRNAME;
        if (ensureDir(app, dir)) {
            return {
                path: dir,
                source: "MOVE_SR_USER_LIBRARY override",
                lastResort: false,
            };
        }
        // An override that cannot be used is an error, not a reason to
        // install somewhere the user did not ask for.
        app.displayDialog(
            "MOVE_SR_USER_LIBRARY is set to:\n\n" +
                override +
                "\n\nbut that folder does not exist and could not be created.",
            { withTitle: TITLE_INSTALL, buttons: ["OK"], defaultButton: 1 }
        );
        return null;
    }

    var fromCfg = userLibraryFromConfig(app);
    if (fromCfg && dirExists(app, fromCfg)) {
        var d = fromCfg + "/" + REMOTE_SCRIPTS_DIRNAME;
        if (ensureDir(app, d)) {
            return {
                path: d,
                source: "Live's Library.cfg",
                lastResort: false,
            };
        }
    }

    var def = defaultUserLibrary();
    if (dirExists(app, def)) {
        var d2 = def + "/" + REMOTE_SCRIPTS_DIRNAME;
        if (ensureDir(app, d2)) {
            return {
                path: d2,
                source: "default User Library location",
                lastResort: false,
            };
        }
    }

    // No User Library exists yet -- create the default one, exactly as the
    // .sh and .ps1 resolvers do at this step. Live picks it up on its next
    // start. Without this the GUI installer prompted for a folder in a
    // situation where install_mac.sh silently succeeded, so the same
    // starting state gave two different experiences.
    if (ensureDir(app, def + "/" + REMOTE_SCRIPTS_DIRNAME)) {
        return {
            path: def + "/" + REMOTE_SCRIPTS_DIRNAME,
            source: "newly created default User Library",
            lastResort: false,
        };
    }

    // Could not even create it. Ask, rather than guess -- Live lets the
    // library be relocated, and a folder made in the wrong place would
    // simply never be scanned.
    var chosen = askForUserLibrary(app, def);
    if (chosen) {
        var d3 = chosen + "/" + REMOTE_SCRIPTS_DIRNAME;
        if (ensureDir(app, d3)) {
            // Recorded so the uninstaller and the next install's sweep can
            // still find this copy -- no resolver would ever derive this
            // path on its own.
            recordChosenLibrary(app, chosen);
            return {
                path: d3,
                source: "folder you selected",
                lastResort: false,
            };
        }
    }

    return offerLastResort(app);
}

// Offer to browse for the User Library.  Returns a path or null.
function askForUserLibrary(app, defaultPath) {
    try {
        app.displayDialog(
            "Could not find your Ableton User Library.\n\n" +
                "Expected it at:\n" +
                defaultPath +
                "\n\nIf you moved it, choose its location on the next " +
                "screen.\n\nLive shows the current path under\n" +
                "Settings > Library > Location of User Library.",
            {
                withTitle: TITLE_INSTALL,
                buttons: ["Choose Folder", "Cancel"],
                defaultButton: 1,
                cancelButton: 2,
            }
        );
    } catch (e) {
        return null;
    }

    try {
        // chooseFolder can hand back a trailing slash; normalise it away so
        // the path we build and later compare against stays consistent.
        return stripTrailingSlashes(
            String(
                app.chooseFolder({
                    withPrompt: "Select your Ableton User Library folder:",
                })
            )
        );
    } catch (e) {
        return null; // Cancelled
    }
}

// Absolute last resort: install inside Live's own application bundle.
// Warn clearly first -- it needs admin rights, breaks Live's code
// signature, and is erased by every Live update.
function offerLastResort(app) {
    var liveApps = detectLiveApps(app);
    if (liveApps.length === 0) {
        app.displayDialog(
            "Could not find an Ableton User Library or an Ableton Live " +
                "installation.\n\nOpen Live once so it creates your User " +
                "Library, then run this installer again.",
            { withTitle: TITLE_INSTALL, buttons: ["OK"], defaultButton: 1 }
        );
        return null;
    }

    var target = liveApps[0];   // newest by mtime
    try {
        app.displayDialog(
            "No Ableton User Library could be found or created.\n\n" +
                "Move-SR-Bridge can be installed inside Live itself:\n  " +
                target.name +
                "\n\nThis is not recommended. It needs an administrator " +
                "password, breaks Live's code signature, and is erased by " +
                "every Live update -- you would have to reinstall after " +
                "each one.\n\nBetter: open Live once so it creates your " +
                "User Library, then run this installer again.",
            {
                withTitle: TITLE_INSTALL,
                buttons: ["Install Inside Live", "Cancel"],
                defaultButton: 2,
                cancelButton: 2,
            }
        );
    } catch (e) {
        return null;
    }

    return {
        path: target.scriptsDir,
        source: "inside Live's application bundle (last resort)",
        lastResort: true,
    };
}

// ---------------------------------------------------------------------------
//  Enumerating every place a copy could be
// ---------------------------------------------------------------------------

// All package directories worth checking, whether they exist or not.
function candidatePackageDirs(app) {
    var out = [];
    var seen = {};

    function add(dir) {
        if (dir && !seen[dir]) {
            seen[dir] = true;
            out.push(dir);
        }
    }

    var override = envUserLibrary();
    if (override) {
        add(override + "/" + REMOTE_SCRIPTS_DIRNAME + "/" + PACKAGE_NAME);
    }

    var fromCfg = userLibraryFromConfig(app);
    if (fromCfg) {
        add(fromCfg + "/" + REMOTE_SCRIPTS_DIRNAME + "/" + PACKAGE_NAME);
    }

    var recorded = recordedUserLibrary();
    if (recorded) {
        add(recorded + "/" + REMOTE_SCRIPTS_DIRNAME + "/" + PACKAGE_NAME);
    }

    add(defaultUserLibrary() + "/" + REMOTE_SCRIPTS_DIRNAME + "/" + PACKAGE_NAME);

    var liveApps = detectLiveApps(app);
    for (var i = 0; i < liveApps.length; i++) {
        add(liveApps[i].scriptsDir + "/" + PACKAGE_NAME);
    }

    return out;
}

// The subset that actually exists, tagged so callers know which ones may
// need an authorisation prompt to delete.
function installedPackageDirs(app, fm) {
    var found = [];
    var candidates = candidatePackageDirs(app);
    for (var i = 0; i < candidates.length; i++) {
        if (fm.fileExistsAtPath(candidates[i])) {
            var inBundle = candidates[i].indexOf("/Contents/App-Resources/") !== -1;
            found.push({
                label: candidates[i] + (inBundle ? "  (inside app bundle)" : ""),
                path: candidates[i],
                inBundle: inBundle,
            });
        }
    }
    return found;
}

// Remove every copy except the one just installed.
function removeStaleInstalls(app, fm, keepPath) {
    var installed = installedPackageDirs(app, fm);
    var removed = [];
    var failed = [];
    for (var i = 0; i < installed.length; i++) {
        if (installed[i].path === keepPath) continue;
        if (removePath(app, installed[i].path, installed[i].inBundle)) {
            removed.push(installed[i].path);
        } else {
            failed.push(installed[i].path);
        }
    }
    return { removed: removed, failed: failed };
}

// Delete a path, retrying with an authorisation prompt when it sits inside
// a Live app bundle (which may be root-owned).
function removePath(app, path, allowAdmin) {
    return runPrivileged(
        app,
        "rm -rf " + shQuote(path),
        allowAdmin,
        "Move-SR-Bridge needs permission to remove an old copy from " +
            "inside Ableton Live's application folder."
    );
}

// Run a shell command, retrying once with an authorisation prompt if
// allowed.  Returns true on success.
function runPrivileged(app, command, allowAdmin, prompt) {
    try {
        doShell(app, command);
        return true;
    } catch (e) {
        if (!allowAdmin) return false;
    }
    try {
        app.doShellScript(command, {
            administratorPrivileges: true,
            withPrompt: prompt,
        });
        return true;
    } catch (e2) {
        return false;
    }
}

// ---------------------------------------------------------------------------
//  Helpers
// ---------------------------------------------------------------------------
function getResourcesDir() {
    var bundleURL = $.NSBundle.mainBundle.bundleURL;
    return ObjC.unwrap(bundleURL.path) + "/Contents/Resources";
}

function dirExists(app, path) {
    try {
        return (
            doShell(
                app,
                "test -d " + shQuote(path) + " && echo yes || echo no"
            ).trim() === "yes"
        );
    } catch (e) {
        return false;
    }
}

function stopHelper(app) {
    try {
        doShell(app, "pkill -x sr_helper_mac 2>/dev/null || true");
    } catch (e) {
        // Nothing running, or pkill unavailable -- harmless either way.
    }
}

function isLiveRunning(app) {
    try {
        var result = doShell(app, "pgrep -x Live 2>/dev/null || true");
        if (result.trim() !== "") {
            app.displayDialog(
                "Ableton Live is currently running.\n\n" +
                    "Please quit Live before installing or uninstalling\n" +
                    "Move-SR-Bridge. Live only scans Remote Scripts when\n" +
                    "it starts up.",
                {
                    withTitle: "Move-SR-Bridge",
                    buttons: ["OK"],
                    defaultButton: 1,
                }
            );
            return true;
        }
    } catch (e) {
        // pgrep not found or other error -- proceed anyway
    }
    return false;
}

function detectLiveApps(app) {
    var fm = $.NSFileManager.defaultManager;
    var appsDir = "/Applications";
    var contents = ObjC.unwrap(
        fm.contentsOfDirectoryAtPathError(appsDir, null)
    );
    var liveApps = [];
    if (!contents) return liveApps;

    // Mirrors the shell's glob, /Applications/Ableton Live*.app -- note
    // there is no space or ".+" after "Live".  The stricter form used to
    // require a suffix ("Ableton Live 12 Suite"), so a plain
    // "Ableton Live.app" was a candidate for install_mac.sh and invisible
    // here: a copy one installer made was one the other could never sweep
    // or uninstall, and it would silently shadow the new package.
    var regex = /^Ableton Live.*\.app$/;

    for (var i = 0; i < contents.length; i++) {
        var name = ObjC.unwrap(contents[i]);
        if (regex.test(name)) {
            var appPath = appsDir + "/" + name;
            var scriptsDir =
                appPath + "/Contents/App-Resources/MIDI Remote Scripts";
            if (fm.fileExistsAtPath(scriptsDir)) {
                liveApps.push({
                    name: name.replace(/\.app$/, ""),
                    path: appPath,
                    scriptsDir: scriptsDir,
                });
            }
        }
    }

    // Newest by modification time first -- NOT alphabetical. As a string,
    // "Ableton Live 9 Trial" sorts after "Ableton Live 11", so a name sort
    // can pick a stale version over the one actually in use. The .sh and
    // .ps1 resolvers both order by mtime; this must match them.
    var order = liveAppsNewestFirst(app);
    liveApps.sort(function (a, b) {
        var ia = order.indexOf(a.path);
        var ib = order.indexOf(b.path);
        if (ia === -1) ia = order.length;
        if (ib === -1) ib = order.length;
        return ia - ib;
    });

    return liveApps;
}

// Bundle paths ordered newest-mtime-first, via the same `ls -td` the shell
// resolver uses so the two cannot drift apart.
//
// Split on \r as well as \n: AppleScript's `do shell script` returns its
// result with every newline translated to a carriage return, so splitting
// on "\n" alone yielded ONE element containing every path run together.
// detectLiveApps() then found -1 for every indexOf(), scored them all
// equal, and the mtime sort silently became a no-op -- leaving the
// alphabetical order this exists to replace.
function liveAppsNewestFirst(app) {
    try {
        var out = doShell(app, "ls -td /Applications/Ableton\\ Live*.app 2>/dev/null");
        return String(out).split(/[\r\n]+/).map(stripTrailingSlashes).filter(function (l) {
            return l !== "";
        });
    } catch (e) {
        return [];
    }
}

// NOTE: this installer deliberately does NOT write ~/.move_sr_bridge/config.ini.
// config.py owns the default config and creates it on first Live launch.  An
// installer-side copy drifted out of sync once already (it was missing the
// whole [logging] section, so the documented "set level = DEBUG" diagnostic
// workflow pointed at a key that did not exist in the file users actually had).

// Escape a string for safe embedding as a single-quoted POSIX shell argument.
function shQuote(str) {
    return "'" + String(str).replace(/'/g, "'\\''") + "'";
}

function doShell(app, command) {
    return app.doShellScript(command);
}
