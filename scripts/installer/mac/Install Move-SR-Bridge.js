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

    // Find the project root (the .app is a sibling to Move_SR_Bridge/)
    var bundlePath = ObjC.unwrap($.NSBundle.mainBundle.bundlePath);
    var projectDir = ObjC.unwrap(
        $.NSString.stringWithString(bundlePath)
            .stringByDeletingLastPathComponent
    );
    var packageSrc = projectDir + "/" + PACKAGE_NAME;

    // Verify source package exists
    var fm = $.NSFileManager.defaultManager;
    if (!fm.fileExistsAtPath(packageSrc)) {
        app.displayDialog(
            "Could not find the Move_SR_Bridge package at:\n" +
                packageSrc +
                "\n\nMake sure this .app is in the same directory as the Move_SR_Bridge folder.",
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

    // Install to each selected Live
    var installed = [];
    for (var i = 0; i < selected.length; i++) {
        var live = liveApps[selected[i]];
        var dest = live.scriptsDir + "/" + packageName;

        // Remove old installation
        if (fm.fileExistsAtPath(dest)) {
            doShell(app, "rm -rf '" + dest + "'");
        }

        // Copy package
        doShell(app, "cp -R '" + packageSrc + "' '" + dest + "'");

        // Make helper executable
        var helperPath = dest + "/sr_helper_mac";
        if (fm.fileExistsAtPath(helperPath)) {
            doShell(app, "chmod +x '" + helperPath + "'");
        }

        installed.push(live.name);
    }

    // Create config if it doesn't exist
    ensureConfig(app, fm);

    // Success
    var msg = "Move-SR-Bridge installed successfully!\n\n";
    if (installed.length > 1) {
        msg += "Installed to:\n";
        for (var i = 0; i < installed.length; i++) {
            msg += "  " + installed[i] + "\n";
        }
        msg += "\n";
    } else {
        msg += "Installed to: " + installed[0] + "\n\n";
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

    // Stop helper processes
    doShell(app, "pkill -x sr_helper_mac 2>/dev/null || true");

    // Remove from each selected installation
    var removed = [];
    for (var i = 0; i < selected.length; i++) {
        var live = installedApps[selected[i]];
        var dest = live.scriptsDir + "/" + packageName;
        if (fm.fileExistsAtPath(dest)) {
            doShell(app, "rm -rf '" + dest + "'");
            removed.push(live.name);
        }
    }

    // Ask about config file
    var configDir =
        ObjC.unwrap($.NSHomeDirectory()) + "/.move_sr_bridge";
    if (fm.fileExistsAtPath(configDir)) {
        try {
            app.displayDialog(
                "Also remove the config file?\n" + configDir,
                {
                    withTitle: "Move-SR-Bridge Uninstaller",
                    buttons: ["Remove Config", "Keep Config"],
                    defaultButton: 2,
                }
            );
            doShell(app, "rm -rf '" + configDir + "'");
        } catch (e) {
            // Keep config
        }
    }

    // Success
    var msg = "Move-SR-Bridge uninstalled successfully!\n\n";
    msg += "Removed from:\n";
    for (var i = 0; i < removed.length; i++) {
        msg += "  " + removed[i] + "\n";
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
function isLiveRunning(app) {
    try {
        var result = doShell(app, "pgrep -x Ableton 2>/dev/null || true");
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
                    name: name.replace(".app", ""),
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

    var selected = [];
    for (var i = 0; i < liveApps.length; i++) {
        for (var j = 0; j < chosen.length; j++) {
            if (liveApps[i].name === chosen[j]) {
                selected.push(i);
                break;
            }
        }
    }
    return selected;
}

function ensureConfig(app, fm) {
    var configDir =
        ObjC.unwrap($.NSHomeDirectory()) + "/.move_sr_bridge";
    var configFile = configDir + "/config.ini";

    if (fm.fileExistsAtPath(configFile)) {
        return;
    }

    // Create directory
    doShell(app, "mkdir -p '" + configDir + "'");

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
    nsStr.writeToFileAtomicallyEncodingError(
        configFile,
        true,
        $.NSUTF8StringEncoding,
        null
    );
}

function doShell(app, command) {
    return app.doShellScript(command);
}
