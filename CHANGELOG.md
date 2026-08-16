# Changelog

All notable changes to Move-SR-Bridge are recorded here.

## 1.7.0

Two things the device shows only with light or a glyph are now spoken, and an
audit of the screen interception fixed three defects it turned up.

Everything here follows one rule: **speak only what a sighted user already
gets from the device**. Announcing a menu item's position ("3 of 12") was
designed and then cut, because Live never draws a total -- a sighted user
cannot see it either.

### Added

- **Submenu marker.** Live draws `>` beside a menu item that opens a list and
  `-` beside one that fires immediately; the selected item now reads as
  "Brightness, submenu" or plain "Standalone". This matters: `Standalone`
  switches the Move out of Live's control the instant you press the wheel.
- **Step-button toggles.** A short tap on one of the 16 buttons along the
  bottom row announces "Step 5 on" or "Step 5 off", read back from the
  button's own LED rather than inferred. Holding a step still enters velocity
  editing and announces that instead -- the two never overlap. A tap's
  announcement replaces the velocity overlay rather than queueing behind it.
  The 32 pads are deliberately not announced.
- **`[speech] step_toggles`** (default `true`) turns step announcements off.
  An existing `config.ini` is never rewritten, so add the section by hand.

### Fixed

- **Notifications no longer carry a line break into speech or braille.** Move
  embeds a real newline in its notification text and splits it when drawing,
  so "Notes deleted" was being sent as two lines joined by a raw newline.
- **dB values now match Live's own rounding** (one decimal). The master-volume
  announcement could report more precision than Live displays anywhere.
- **A second display line starting lowercase is no longer mistaken for a
  wrapped sentence.** A lowercase track or device name read as "1-Audio bass"
  instead of "1-Audio, bass". Only one screen on the device genuinely wraps a
  sentence, and it is now named rather than guessed at.

### Development

- Work now lands on a **`dev` branch**, versioned `1.7.0.dev1` and so on, and
  CI builds it. Previously the frozen Windows and macOS artefacts were first
  exercised at the moment of release. Branch builds publish nothing; they
  upload artifacts. Releases are still driven by a `v*` tag.
- **`scripts/bump_version.py`** manages the version string
  (`--show`/`--set`/`--dev`/`--release`).

## 1.6.0

The install location moves to the Ableton User Library on both platforms,
and the release now has real gates behind it: a unit suite, a frozen-binary
smoke test, and a version check against the tag.

### Install location

- **Both platforms now install to the Ableton User Library's
  `Remote Scripts/`** instead of inside Live itself. This needs no
  administrator rights, one copy serves every Live installation, and it
  survives Live updates. Writing into a macOS app bundle also breaks Live's
  code signature, which the old location did.
- The location is **resolved**, not assumed: `MOVE_SR_USER_LIBRARY` first,
  then Live's own `Library.cfg`, then the platform default, then creating
  the default, and only as a last resort inside Live -- which is warned
  about loudly. On Windows the default comes from
  `GetFolderPath('MyDocuments')`, so OneDrive Known Folder redirection is
  followed rather than landing in an empty stub.
- After installing, **every other candidate location is swept**. Two
  same-named packages on Live's search path is ambiguous, and the stale one
  keeps shadowing the new one.
- The Windows installers no longer prompt for a Live version. One install
  serves all of them.

### Fixed

- **A malformed `config.ini` no longer removes Move-SR-Bridge from Live's
  Control Surface dropdown.** The file is read at module import, so a
  failure there made Live skip the script entirely. Two ways in, both now
  handled: saving the file in a non-UTF-8 encoding (Notepad's default ANSI
  save, with any accented character in it) raised `UnicodeDecodeError`,
  which is not a `configparser` error and so escaped the existing handler;
  and a `level =` naming something that is not a log level raised
  `ValueError`. Both now fall back to defaults and say so in the log.
- **`level = notset` no longer silently disables logging.** It meant
  "inherit", which dropped everything below warnings.
- **A failure inside the display hook is now visible in the log.** Both
  catch-alls logged at DEBUG, so at the default level a hook failing on
  every frame produced a completely silent, completely dead bridge. The
  first failure of each kind is now logged as an error.
- **The display hook is uninstalled when Live disconnects.** It was left in
  place, so a frame arriving after teardown could still speak after "Move
  disconnected".
- **The automation indicator is no longer lost** when the redundant track or
  scene name is stripped. An automated parameter on the selected track read
  as a bare "0 dB"; it now reads "automated, 0 dB".
- **The helper no longer dies on a recoverable socket error.** Any
  `accept()` failure other than a timeout ended the process, and nothing on
  the Live side notices -- so speech stopped for the rest of the session
  with only "Helper stopped" to explain it.
- **The helper no longer announces itself before it knows it can start.** A
  second helper started against an occupied port said "helper started" and
  then exited.
- **`config.py`'s own messages reach the log.** The process that creates
  `config.ini` was the one process that could never report having done so.
- **Installing can no longer destroy a working install.** Both installers
  removed the old copy and then copied the new one; if the copy failed --
  which it could inside Live's root-owned app bundle, where the shell
  installer also had no privilege escalation -- the user was left with
  neither. Installs are now staged and swapped into place.
- **A hand-picked install location is remembered.** The graphical installer
  could put the package somewhere no uninstaller would ever look, leaving it
  to shadow every later install.
- The three install-location resolvers agreed on paper but not in practice:
  trailing separators, lone carriage returns, Live app-bundle matching, and
  app ordering are now genuinely identical across all three.
- A stray `CONFIRM` or `YN` environment variable no longer answers a Windows
  installer prompt on the user's behalf -- including the uninstaller's
  destructive one.
- The debounce no longer joins a running timer from Live's display callback,
  where it could stall the Move's screen for up to a second.
- Assorted: a leaked probe socket, a redundant Live API read on the redraw
  path, and Tolk being left loaded when the helper exits early.

### Release process

- `version.py` is the single source of the version, logged at startup by
  both processes, and **CI refuses to publish a release whose tag disagrees
  with it**.
- A **stdlib unit suite** (160 tests, no dependencies, no Live, no hardware)
  runs on Python 3.11 -- Live's own interpreter -- along with `compileall`,
  so 3.12+ syntax cannot reach a release.
- A **smoke test runs the built binary against a real `config.ini`** and
  fails the release if it is ignored. This is the check that would have
  caught `configparser` going missing from every frozen build. It also
  asserts the binary is frozen and reports the right version, so it cannot
  pass against the source it exists to not test.
- `scripts/release_mac.sh` runs both gates too. It previously ran neither,
  and offered a ready-to-paste publish command for a single-architecture
  artefact without saying so.
- The macOS installer bundle is assembled from the package directory rather
  than a hand-written file list, and refuses to build against a helper
  binary older than `version.py`.
- CI asserts the macOS helper really is universal2 rather than just printing
  its architectures.

### Uninstall

- Both uninstallers sweep every location, including legacy
  `C:\ProgramData` copies.
- The Windows uninstaller now offers to remove `~/.move_sr_bridge`, which
  the macOS one already did.

### Known limitations

- The macOS release `.app` is **not signed or notarized**. Gatekeeper blocks
  it on first launch; the README documents both ways round it.
- Loop overview, level meters, pad/LED state and list position ("3 of 12")
  are still not announced.
