# The PC client

The installer installs the launcher and the player for Windows for one Windows user, with no administrator rights. The
launcher connects to an OpenDMTQ server, signs in with an account its owner made, downloads that server's app, sets the
picture and the sound up for the PC, and starts the game in the player. The installer of a release,
`opendmtq-pc-client-<version>-windows-x64-setup.exe`, asks for the server's address; the one a server's site hands out,
`opendmtq-pc-client-<version>-windows-x64-setup-<address>.exe`, has that server on its end and starts with it. The
build makes it as `OpenDMTQ-Setup.exe`, which the release renames.

| Path | What it is |
|---|---|
| `opendmtq_client/` | The launcher (Python and Tk): `app.py` (the window), `pages.py`, `guide.py` (the first-start guide), `actions.py` (what the buttons do, shared with the command line in `main.py`), `server.py` (the server's `client.php` and `/apk`), `apps.py` (each server's app on this PC), `player.py`, `values.py` (the PC settings), `installer.py` and `setup_window.py` (the installer: what each page does, and its window), `frameless.py` (its window without Windows' title bar: the styles, Windows' own move and minimise, Windows 11's corners and shadow), `maintenance.py` (Help's Repair, Clear game data, Start over and Uninstall, and the launcher's update: the questions and the work under way), `repair.py` and `removal.py` (the files those tools put back and delete), `connection.py` (the connection test), `report.py` (Help's report), `updates.py` (the launcher's own updates: from its server, then the project's releases, each only when signed), `signing.py` (the signature's check, the same file as the server's), `displays.py` (each display's rates) |
| `packaging/windows/` | The Windows build: PyInstaller under Wine, the player beside the launcher, Velopack's packages, the installer |
| `tests/` | Unit tests, the UI screenshots on a virtual screen (`tests/ui`), and the installer to the game under Wine (`tests/windows`) |

What it keeps, per Windows user: the program in `%LOCALAPPDATA%\OpenDMTQ.Client`, the launcher's settings, logs and
each server's app in `%LOCALAPPDATA%\OpenDMTQ\client`, and the game's own data and the player's log in
`%LOCALAPPDATA%\OpenDMTQ\<package>`, as the player keeps them.

## Working on it

```sh
(cd client && python3 -m unittest discover -s tests -t .)   # no screen, no network: a stand-in server and player
client/tests/ui/run.sh OUT_DIR                               # every page, the guide and the dialogs, both languages, three sizes and 200 %
arm32/build.sh && arm32/build_windows.sh player              # the guest's system, the agent and the player for Windows
arm32/bundle_windows.sh                                      # the player packed, as the installer brings it
client/packaging/windows/build.sh OUT_DIR                    # OUT_DIR/releases: the installer and Velopack's packages
TEST_SITE=... TEST_NET=... TEST_APK=... TEST_TOOLS=... ACCOUNT_FILE=... \
  client/tests/windows/e2e.sh OUT_DIR E2E_DIR                # installer to game under Wine, against a test server
```

The unit tests need Python with Tk, Pillow and fontTools; CI runs them in the image of `tests/ui` (`.github/workflows/ci.yml`).
On Windows itself, `client/tests/windows/install.ps1 -Folder OUT_DIR\releases` installs the build silently and checks the
command line, the player, a repair and the uninstall. The first build fetches its build machines (a Windows Python,
Wine, .NET's `vpk`); later builds need no network.

A launcher looks for its updates on the server it plays on first (`/updates/` there), then on the GitHub repository
whose URL `OPENDMTQ_UPDATE_SOURCE` gave its build, and takes only a release whose checksums the OpenDMTQ project signed.
`OPENDMTQ_PREVIOUS_RELEASE`, the previous release's full package, gives a build its delta package too.
`OpenDMTQ-cmd.exe --help` lists what the command line does: the same as the window, each step a flag.
