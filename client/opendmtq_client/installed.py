"""The installed program, seen from the launcher that runs inside it.

Velopack's setup lays the program out like this, in %LOCALAPPDATA%\\OpenDMTQ.Client of the Windows user:

  OpenDMTQ.exe    the stub the shortcuts start: it runs the current version
  Update.exe      Velopack's updater and uninstaller
  current\\        the program: OpenDMTQ.exe, OpenDMTQ-cmd.exe, the player, and sq.version with the version it is
  packages\\       the package the installed version came from

A launcher run from a checkout or from a copied folder has none of this: root() answers None there, and repairing and
uninstalling say that they work in the installed launcher. Windows' entry for the program (Settings, Apps; Control
Panel's Programs) is Velopack's, made OpenDMTQ's own by own_entry().
"""

import logging
import os
import sys

log = logging.getLogger("opendmtq_client")

# Velopack's package id: the install folder's name and the first part of its packages' names.
PACKAGE_ID = "OpenDMTQ.Client"
# Velopack's updater and uninstaller, in the install folder.
UPDATER = "Update.exe"
# Windows' entry for the program in Settings, Apps, under the current user's part of the registry: Velopack's setup
# writes it, and each update writes it again.
UNINSTALL_KEY = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + PACKAGE_ID


def root():
    """The folder this program is installed in (the one above current\\), or None when OpenDMTQ-Setup.exe did not
    install it. OPENDMTQ_INSTALL_ROOT names a folder laid out like one for the tests."""
    named = os.environ.get("OPENDMTQ_INSTALL_ROOT")
    if named:
        return named if os.path.isdir(named) else None
    if not getattr(sys, "frozen", False):
        # Run from a checkout: nothing was installed.
        return None
    here = os.path.dirname(os.path.abspath(sys.executable))
    # Velopack's layout: the program in current\, the version it is in the file beside it.
    if os.path.basename(here).lower() != "current" or not os.path.isfile(os.path.join(here, "sq.version")):
        return None
    return os.path.dirname(here)


def updater(folder):
    """Velopack's Update.exe of an install folder, or None when it is not there."""
    path = os.path.join(folder, UPDATER)
    return path if os.path.isfile(path) else None


# The launcher's argument that opens the installer's own uninstall from Windows' Settings, Apps (main.py).
UNINSTALL_WINDOW = "--uninstall-window"


def entry_commands(folder):
    """What Windows' entry for the program in `folder` runs, as (UninstallString, QuietUninstallString): the launcher's
    own uninstall, which asks whether the data stays and says how much (installer.py, in a copy of the launcher outside
    the program's folder), and Velopack's uninstaller with nothing on screen for a tool that uninstalls quietly (the data
    stays then)."""
    window = '"%s" %s' % (os.path.join(folder, "current", "OpenDMTQ.exe"), UNINSTALL_WINDOW)
    quiet = '"%s" --uninstall --silent' % os.path.join(folder, UPDATER)
    return window, quiet


def own_entry(folder=None):
    """Windows' Settings, Apps (and Control Panel's Programs) uninstall OpenDMTQ with the launcher's own uninstall
    (entry_commands): Velopack writes the entry with its own uninstaller at the install and again at each update, whose
    window asks nothing and keeps the data. The entry is made OpenDMTQ's here, by the installer once its setup is done,
    by the update's hook, and at each start of the launcher. `folder` is the install folder (this launcher's own when
    None). True when the entry was changed."""
    if sys.platform != "win32":
        # Windows' registry only.
        return False
    folder = folder or root()
    if not folder or not updater(folder):
        # Not installed by OpenDMTQ-Setup.exe: there is no entry of Velopack's to change.
        return False
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE)
    except OSError:
        # No entry (an install in a folder of its own, or one being removed): nothing to change.
        return False
    changed = False
    with key:
        for name, wanted in zip(("UninstallString", "QuietUninstallString"), entry_commands(folder)):
            try:
                now = str(winreg.QueryValueEx(key, name)[0])
            except OSError:
                now = ""
            if now != wanted:
                # Written only when it says something else: an earlier start, or the update's hook, made it already.
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, wanted)
                changed = True
    if changed:
        log.info("Windows' Apps uninstall OpenDMTQ with its own uninstall now: %s", entry_commands(folder)[0])
    return changed
