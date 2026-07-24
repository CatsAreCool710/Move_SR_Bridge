// Install Move-SR-Bridge.js -- JXA installer for macOS
// Copyright (C) 2026 Jeremiah Ticket
// Licensed under GPLv3 -- see LICENSE for details.
//
// Compiled into a .app bundle via osacompile (see build.sh).
// Uses macOS system dialogs which are fully VoiceOver accessible.

function run(argv) {
    var app = Application.currentApplication();
    app.includeStandardAdditions = true;

    var PACKAGE_NAME = "Move_SR_Bridge";

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
                withTitle: "Move-SR-Bridge Installer",
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
        doInstall(app, fm, packageSrc, PACKAGE_NAME);
    } else if (mainChoice.buttonReturned === "Uninstall") {
        doUninstall(app, fm, PACKAGE_NAME);
    }
}

// ---------------------------------------------------------------------------
//  Installation
// ---------------------------------------------------------------------------
function doInstall(app, fm, packageSrc, packageName) {
    // Check if Live is running
    if (isLiveRunning(app)) {
        return;
    }

    // Detect Live installations
    var liveApps = detectLiveApps();
    if (liveApps.length === 0) {
        app.displayDialog(
            "No Ableton Live installations found in /Applications.\n\n" +
                "If Live is installed elsewhere, copy the " +
                packageName +
                "/ folder to your Live MIDI Remote Scripts directory manually.",
            {
                withTitle: "Move-SR-Bridge Installer",
                buttons: ["OK"],
                defaultButton: 1,
            }
        );
        return;
    }

    // Select installation(s)
    var selected = selectInstallations(app, liveApps, "install");
    if (selected.length === 0) return;

    // Confirm
    var confirmMsg =
        "This will install Move-SR-Bridge to " +
        selected.length +
        " Live installation(s):\n\n";
    for (var i = 0; i < selected.length; i++) {
        confirmMsg += "  " + liveApps[selected[i]].name + "\n";
    }
    confirmMsg += "\nContinue?";

    try {
        app.displayDialog(confirmMsg, {
            withTitle: "Move-SR-Bridge Installer",
            buttons: ["Install", "Cancel"],
            defaultButton: 1,
            cancelButton: 2,
        });
    } catch (e) {
        return;
    }

    // Install to each selected Live -- each installation is independent, so
    // a failure on one shouldn't abort the rest of the batch.
    var installed = [];
    var failed = [];
    for (var i = 0; i < selected.length; i++) {
        var live = liveApps[selected[i]];
        var dest = live.scriptsDir + "/" + packageName;
        try {
            if (fm.fileExistsAtPath(dest)) {
                doShell(app, "rm -rf " + shQuote(dest));
            }
            doShell(app, "cp -R " + shQuote(packageSrc) + " " + shQuote(dest));

            var helperPath = dest + "/sr_helper_mac";
            if (fm.fileExistsAtPath(helperPath)) {
                doShell(app, "chmod +x " + shQuote(helperPath));
            }
            installed.push(live.name);
        } catch (e) {
            failed.push(live.name);
        }
    }

    if (installed.length === 0) {
        var failMsg = "Move-SR-Bridge could not be installed to any selected installation:\n\n";
        for (var i = 0; i < failed.length; i++) {
            failMsg += "  " + failed[i] + "\n";
        }
        app.displayDialog(failMsg, {
            withTitle: "Move-SR-Bridge Installer",
            buttons: ["OK"],
            defaultButton: 1,
        });
        return;
    }

    // Create config if it doesn't exist
    var configOk = ensureConfig(app, fm);

    // Success (or partial success)
    var msg =
        failed.length === 0
            ? "Move-SR-Bridge installed successfully!\n\n"
            : "Move-SR-Bridge installed with some errors.\n\n";

    msg += "Installed to:\n";
    for (var i = 0; i < installed.length; i++) {
        msg += "  " + installed[i] + "\n";
    }
    msg += "\n";

    if (failed.length > 0) {
        msg += "Failed for:\n";
        for (var i = 0; i < failed.length; i++) {
            msg += "  " + failed[i] + "\n";
        }
        msg += "\n";
    }

    if (!configOk) {
        msg += "Warning: could not create the default config file at\n" +
            "~/.move_sr_bridge/config.ini -- defaults will be used.\n\n";
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
        "  (edit to customise debounce settings)";

    app.displayDialog(msg, {
        withTitle: "Move-SR-Bridge Installer",
        buttons: ["OK"],
        defaultButton: 1,
    });
}

// ---------------------------------------------------------------------------
//  Uninstallation
// ---------------------------------------------------------------------------
function doUninstall(app, fm, packageName) {
    // Check if Live is running
    if (isLiveRunning(app)) {
        return;
    }

    // Detect Live installations and check which have Move_SR_Bridge installed
    var liveApps = detectLiveApps();
    var installedApps = [];

    for (var i = 0; i < liveApps.length; i++) {
        var dest = liveApps[i].scriptsDir + "/" + packageName;
        if (fm.fileExistsAtPath(dest)) {
            installedApps.push(liveApps[i]);
        }
    }

    if (installedApps.length === 0) {
        app.displayDialog(
            "Move-SR-Bridge is not installed in any Ableton Live installation.",
            {
                withTitle: "Move-SR-Bridge Uninstaller",
                buttons: ["OK"],
                defaultButton: 1,
            }
        );
        return;
    }

    // Select which to remove
    var names = [];
    for (var i = 0; i < installedApps.length; i++) {
        names.push(installedApps[i].name);
    }

    var selected;
    if (installedApps.length === 1) {
        try {
            app.displayDialog(
                "Move-SR-Bridge is installed in:\n  " +
                    names[0] +
                    "\n\nRemove it?",
                {
                    withTitle: "Move-SR-Bridge Uninstaller",
                    buttons: ["Remove", "Cancel"],
                    defaultButton: 1,
                    cancelButton: 2,
                }
            );
        } catch (e) {
            return;
        }
        selected = [0];
    } else {
        selected = selectInstallations(app, installedApps, "uninstall");
        if (selected.length === 0) return;
    }

    // Confirm
    var confirmMsg =
        "Remove Move-SR-Bridge from " +
        selected.length +
        " installation(s)?\n\n";
    for (var i = 0; i < selected.length; i++) {
        confirmMsg += "  " + installedApps[selected[i]].name + "\n";
    }

    try {
        app.displayDialog(confirmMsg, {
            withTitle: "Move-SR-Bridge Uninstaller",
            buttons: ["Remove", "Cancel"],
            defaultButton: 1,
            cancelButton: 2,
        });
    } catch (e) {
        return;
    }

    // Stop helper processes (harmless no-op if none running -- "|| true"
    // keeps the exit code 0 so this never throws)
    doShell(app, "pkill -x sr_helper_mac 2>/dev/null || true");

    // Remove from each selected installation -- independent per-installation,
    // so a failure on one shouldn't abort the rest of the batch.
    var removed = [];
    var failed = [];
    for (var i = 0; i < selected.length; i++) {
        var live = installedApps[selected[i]];
        var dest = live.scriptsDir + "/" + packageName;
        if (fm.fileExistsAtPath(dest)) {
            try {
                doShell(app, "rm -rf " + shQuote(dest));
                removed.push(live.name);
            } catch (e) {
                failed.push(live.name);
            }
        }
    }

    // Ask about config file. "Keep Config" is also the cancel button, so
    // Escape/Return-on-default and clicking "Keep Config" all take the same
    // safe no-delete path via the catch block below.
    var configDir =
        ObjC.unwrap($.NSHomeDirectory()) + "/.move_sr_bridge";
    if (fm.fileExistsAtPath(configDir)) {
        try {
            var configChoice = app.displayDialog(
                "Also remove the config file?\n" + configDir,
                {
                    withTitle: "Move-SR-Bridge Uninstaller",
                    buttons: ["Remove Config", "Keep Config"],
                    defaultButton: 2,
                    cancelButton: 2,
                }
            );
            if (configChoice.buttonReturned === "Remove Config") {
                doShell(app, "rm -rf " + shQuote(configDir));
            }
        } catch (e) {
            // Keep config (cancelled / "Keep Config" clicked)
        }
    }

    // Success (or partial success)
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
    }

    app.displayDialog(msg, {
        withTitle: "Move-SR-Bridge Uninstaller",
        buttons: ["OK"],
        defaultButton: 1,
    });
}

// ---------------------------------------------------------------------------
//  Helpers
// ---------------------------------------------------------------------------
function getResourcesDir() {
    var bundleURL = $.NSBundle.mainBundle.bundleURL;
    return ObjC.unwrap(bundleURL.path) + "/Contents/Resources";
}

function isLiveRunning(app) {
    try {
        var result = doShell(app, "pgrep -x Live 2>/dev/null || true");
        if (result.trim() !== "") {
            app.displayDialog(
                "Ableton Live is currently running.\n\n" +
                    "Please quit Live before installing or uninstalling\n" +
                    "Move-SR-Bridge.",
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

function detectLiveApps() {
    var fm = $.NSFileManager.defaultManager;
    var appsDir = "/Applications";
    var contents = ObjC.unwrap(
        fm.contentsOfDirectoryAtPathError(appsDir, null)
    );
    var liveApps = [];
    var regex = /^Ableton Live .+\.app$/;

    for (var i = 0; i < contents.length; i++) {
        var name = ObjC.unwrap(contents[i]);
        if (regex.test(name)) {
            var appPath = appsDir + "/" + name;
            var scriptsDir =
                appPath +
                "/Contents/App-Resources/MIDI Remote Scripts";
            if (fm.fileExistsAtPath(scriptsDir)) {
                liveApps.push({
                    name: name.replace(/\.app$/, ""),
                    path: appPath,
                    scriptsDir: scriptsDir,
                });
            }
        }
    }

    // Sort alphabetically
    liveApps.sort(function (a, b) {
        return a.name < b.name ? -1 : a.name > b.name ? 1 : 0;
    });

    return liveApps;
}

function selectInstallations(app, liveApps, action) {
    if (liveApps.length === 1) {
        return [0]; // Auto-select the only one
    }

    var labels = [];
    for (var i = 0; i < liveApps.length; i++) {
        labels.push(liveApps[i].name);
    }

    var prompt =
        action === "install"
            ? "Select which Ableton Live installation(s) to install to:"
            : "Select which installation(s) to remove Move-SR-Bridge from:";

    var chosen;
    try {
        chosen = app.chooseFromList(labels, {
            withPrompt: prompt,
            OKButtonName: action === "install" ? "Install" : "Remove",
            multipleSelectionsAllowed: true,
        });
    } catch (e) {
        return []; // Cancelled
    }

    if (chosen === false) {
        return []; // Cancelled -- chooseFromList returns false, it doesn't throw
    }

    // Match each chosen label to exactly one liveApps entry (consume the
    // label once it's matched) so duplicate display names can't cause a
    // single selection to map to more than one underlying installation.
    var selected = [];
    var remaining = chosen.slice();
    for (var i = 0; i < liveApps.length; i++) {
        var idx = remaining.indexOf(liveApps[i].name);
        if (idx !== -1) {
            selected.push(i);
            remaining.splice(idx, 1);
        }
    }
    return selected;
}

function ensureConfig(app, fm) {
    var configDir =
        ObjC.unwrap($.NSHomeDirectory()) + "/.move_sr_bridge";
    var configFile = configDir + "/config.ini";

    if (fm.fileExistsAtPath(configFile)) {
        return true;
    }

    // Create directory
    try {
        doShell(app, "mkdir -p " + shQuote(configDir));
    } catch (e) {
        return false;
    }

    // Write default config
    var defaultConfig =
        "[debounce]\n" +
        "# Enable debounce for display updates.  When enabled, speech is delayed\n" +
        "# until no display updates occur for 'delay_ms' milliseconds.\n" +
        "# This prevents rapid-fire speech during encoder turns.\n" +
        "enabled = true\n" +
        "\n" +
        "# Milliseconds to wait after the last display update before speaking.\n" +
        "# Lower values feel more responsive; higher values reduce chatter.\n" +
        "# Set to 0 to effectively disable debounce even if enabled = true.\n" +
        "delay_ms = 300\n";

    var nsStr = $.NSString.stringWithString(defaultConfig);
    var ok = nsStr.writeToFileAtomicallyEncodingError(
        configFile,
        true,
        $.NSUTF8StringEncoding,
        null
    );
    return Boolean(ok);
}

// Escape a string for safe embedding as a single-quoted POSIX shell argument.
function shQuote(str) {
    return "'" + String(str).replace(/'/g, "'\\''") + "'";
}

function doShell(app, command) {
    return app.doShellScript(command);
}
