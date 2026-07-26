# Changelog

All notable changes to Move-SR-Bridge are recorded here.

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
