"""A report for whoever helps with a problem: one zip with what the launcher and the player wrote, the settings, and this
PC's displays, sound devices, Windows and graphics cards, with what names a person or signs in left out (Help's Save a
report, and OpenDMTQ-cmd.exe --report FILE).

  opendmtq-report-<date>-<time>.zip
    about.txt                     the launcher's and the player's versions, Windows, the graphics cards, when it was
                                  made, and what was left out
    launcher/launcher.log         the launcher's log (and the two before it, .1 and .2)
    player/player.log             the end of the game's log for the current server's app: its last games
    settings/settings.json        the launcher's settings, the sign-ins taken out
    settings/player-settings.txt  the settings file the player reads
    system/displays.txt           each display, its size and its rates, as the launcher's log has them
    system/sound.txt              the sound devices the player plays on, the default marked
    system/connection-test.txt    the last connection test (connection.py), step by step, when there was one

What is left out is replaced by a word in angle brackets wherever it is found, in every file: the Windows user's name
and every path with it (the home folder, the temporary folder), the site IDs signed in with or filled in, every server's
address (as written, as host:port, its host, the address its app is built for, its folder's name here) and its own
name, the sign-in cookies, tokens (an API's, a broadcast's upload key, a one-time sign-in link's), this PC's player id
(the game's device id), and the words typed in the game. The list of what was left out, by kind and how often, is in
about.txt and is what the window and the command line say after it is made.
"""

import getpass
import json
import logging
import os
import platform
import re
import sys
import time
import urllib.parse
import zipfile

from opendmtq_client import __version__, apps, displays, player, removal
from opendmtq_client import state as st

log = logging.getLogger("opendmtq_client")

# The report's name: what it is and when it was made, in lower case as every file OpenDMTQ hands a person.
NAME = "opendmtq-report-%s.zip"
# The most of the game's log taken: its end, the last games (the player adds to one file from game to game).
PLAYER_LOG_TAIL = 512 * 1024
# The kinds of what is left out, in the order the list says them (i18n report.left.<kind>).
KINDS = ("user", "account", "server", "server_name", "cookie", "token", "device", "typed")
# The word each kind is replaced by.
WORDS = {"user": "<user>", "account": "<account>", "server": "<server>", "server_name": "<server name>",
         "cookie": "<cookie>", "token": "<token>", "device": "<device id>", "typed": "<typed>"}
# A sign-in cookie of the site as the launcher keeps it (server/portal/auth.php: when it ends, the account in hex, the
# signature), and under its name in a header.
COOKIE_VALUE = re.compile(r"\b\d{10}\.(?:[0-9a-f]{2}){3,40}\.[0-9a-f]{64}\b")
COOKIE_NAMED = re.compile(r"(opendmtq_dl=)[^;\s\"']+")
# An API token (odq_ and its id, then its secret), and what names a secret in an address or a JSON answer: a broadcast's
# upload key, a one-time sign-in link's token, a password.
API_TOKEN = re.compile(r"\bodq_[0-9a-f]{12}_[A-Za-z0-9_-]{43}")
SECRET_PARAM = re.compile(r"(?i)\b((?:token|once|key|secret|password|passwd)=)[^&\s\"'<>]+")
SECRET_JSON = re.compile(r"(?i)(\"(?:token|once|secret|password)\"\s*:\s*\")[^\"]*(\")")
# What the player says the game was typed (its text fields: a name, a message), its words left out.
TYPED = re.compile(r"(typed \")(?:[^\"\\]|\\.)*(\")")


class Scrub:
    """What is left out of every file of a report, and how often each kind was found."""

    def __init__(self):
        # (pattern, its replacement, kind, length): the values found on this PC, the longest first.
        self.found = []
        self.counts = dict.fromkeys(KINDS, 0)

    def add(self, kind, value, whole=False):
        """Leave out `value` (a text) as `kind` wherever it is, in any letter case (Windows' paths and names, an
        address's host): as a whole word only with `whole`, neither "a1" in "data1" nor 10.0.0.5 in 110.0.0.5."""
        value = (value or "").strip()
        if len(value) < 2:
            # One letter is in every word: nothing that short names anyone.
            return
        pattern = r"(?<![\w.-])%s(?![\w-])" % re.escape(value) if whole else re.escape(value)
        self.pattern(kind, pattern, WORDS[kind], len(value))

    def pattern(self, kind, pattern, word, length):
        """Leave out what `pattern` (a regular expression, any letter case) finds as `kind`, replaced by `word` (which may
        keep the pattern's groups: \\1)."""
        self.found.append((re.compile(pattern, re.I), word, kind, length))
        # The longest first: a server's whole address before its host alone.
        self.found.sort(key=lambda item: -item[3])

    def __call__(self, text):
        """`text` with everything left out, each kind counted."""
        for pattern, word, kind, _length in self.found:
            text = self._sub(pattern, word, kind, text)
        text = self._sub(COOKIE_NAMED, r"\1" + WORDS["cookie"], "cookie", text)
        text = self._sub(COOKIE_VALUE, WORDS["cookie"], "cookie", text)
        text = self._sub(API_TOKEN, WORDS["token"], "token", text)
        text = self._sub(SECRET_PARAM, r"\1" + WORDS["token"], "token", text)
        text = self._sub(SECRET_JSON, r"\1" + WORDS["token"] + r"\2", "token", text)
        text = self._sub(TYPED, r"\1" + WORDS["typed"] + r"\2", "typed", text)
        return text

    def _sub(self, pattern, word, kind, text):
        """One pattern replaced, its count added to its kind's."""
        text, n = pattern.subn(word, text)
        self.counts[kind] += n
        return text

    def left(self):
        """What was left out: [(kind, how many times)], the kinds found, in the list's order."""
        return [(kind, self.counts[kind]) for kind in KINDS if self.counts[kind]]


def _short_path(path):
    """A path in Windows' short form (C:\\Users\\KANGG~1), as the temporary folder may be written; the path itself
    elsewhere, or when Windows says nothing."""
    if sys.platform != "win32":
        return path
    try:
        import ctypes
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(path, buffer, len(buffer)):
            return buffer.value
    except (AttributeError, OSError):
        pass
    return path


# A folder of a path: what comes before a name that is one (C:\\Users\\<name>, /home/<name>), and what may follow it.
IN_A_PATH = r"(?<=[\\/])%s(?=[\\/\"'\s,;)]|$)"


def _users(scrub):
    """The Windows user's name, in every path that has it (the home folder and every folder in it, the temporary folder
    in Windows' short form too): replaced where it is a folder's name. Anywhere else it may be a word a log uses
    ("player"), which stays."""
    home = os.path.expanduser("~").rstrip("\\/")
    names = {os.environ.get("USERNAME") or "", os.path.basename(home), os.path.basename(_short_path(home))}
    try:
        names.add(getpass.getuser())
    except (OSError, KeyError, ImportError):
        # No name to be had (no environment for it): the home folder's own name stands for it.
        pass
    for name in names - {""}:
        scrub.pattern("user", IN_A_PATH % re.escape(name), WORDS["user"], len(name))


# Where the launcher writes a site ID: a sign-in's line ("as player1", "--sign-in player1", "Signed in as player1"), an
# installer's ("the ID admin"), --status's ("signed in: player1", "no (player1, ended)"), and the settings' fields. A
# whole word elsewhere may be a word of the logs' own (an ID "player").
ACCOUNT_AT = (r"((?:\bas|--sign-in|\bthe ID|\bsigned in:|\bno \()[ =])%s(?![\w.-])",
              r"(\"(?:account|fill)\"\s*:\s*\")%s(?=\")")


def _servers(scrub, state):
    """Every server this launcher knows: its address as written, its host and port, its host, the address its app is
    built for and its folder's name here (host-port), its own name; and the site IDs signed in with or filled in."""
    for server in state.servers:
        url = server.get("url") or ""
        parts = urllib.parse.urlsplit(url)
        scrub.add("server", url)
        scrub.add("server", parts.netloc, whole=True)
        scrub.add("server", (parts.hostname or "").strip("[]"), whole=True)
        address = str(server.get("address") or "")
        scrub.add("server", address, whole=True)
        # The address in a file's or a folder's name: its colon a dash (the app's file, the server's folder here).
        scrub.add("server", address.replace(":", "-"), whole=True)
        scrub.add("server", apps.key(url) if url else "", whole=True)
        if st.has_own_name(server):
            scrub.add("server_name", server.get("name") or "")
        for account in {server.get("account") or "", server.get("fill") or ""} - {""}:
            for at in ACCOUNT_AT:
                scrub.pattern("account", at % re.escape(account), r"\1" + WORDS["account"], len(account))


def _devices(scrub):
    """This PC's player id in each game's folder (the game's device id, which the server knows the PC by)."""
    for folder in removal.game_folders():
        try:
            with open(os.path.join(folder, removal.ID_FOLDER, removal.ID_FILE), encoding="utf-8-sig",
                      errors="replace") as f:
                found = f.read().strip()
        except OSError:
            continue
        scrub.add("device", found)


def scrubber(state):
    """What every file of a report leaves out, for this launcher's state on this PC."""
    scrub = Scrub()
    _users(scrub)
    _servers(scrub, state)
    _devices(scrub)
    return scrub


def _settings(text):
    """The launcher's settings without the sign-ins: each server's cookie and when it ends taken out (its address and
    the IDs go as everywhere else)."""
    try:
        data = json.loads(text)
    except ValueError:
        return text
    for server in data.get("servers") or []:
        if isinstance(server, dict):
            for key in ("cookie", "expires"):
                if server.get(key):
                    server[key] = WORDS["cookie"]
    return json.dumps(data, indent=2, ensure_ascii=False)


def _read(path, tail=None):
    """A text file as text (None when it is not there), its last `tail` bytes alone when given, from a line's start."""
    try:
        with open(path, "rb") as f:
            if tail:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - tail))
                data = f.read()
                if size > tail:
                    # A line cut by the start is no line: from the next one.
                    data = data.split(b"\n", 1)[-1]
            else:
                data = f.read()
    except OSError:
        return None
    # The player writes UTF-8; Windows' own words may come in its code page: a byte that is not UTF-8 is no reason to fail.
    return data.decode("utf-8-sig", errors="replace")


def windows():
    """Windows as Python's platform module and Windows itself say it: its name, release, build and edition."""
    if sys.platform != "win32":
        return "%s %s (%s)" % (platform.system(), platform.release(), platform.version())
    try:
        release, version, service, _kind = platform.win32_ver()
        edition = platform.win32_edition() or ""
        build = sys.getwindowsversion()
        return "Windows %s %s%s, build %d.%d.%d%s" % (release, edition, " " + service if service else "", build.major,
                                                    build.minor, build.build, " (%s)" % version if version else "")
    except (AttributeError, OSError, ValueError):
        return "Windows (it did not say which)"


def graphics():
    """The graphics cards' names, as Windows lists its display adapters ("NVIDIA GeForce RTX 4090"); [] where it says
    nothing (off Windows, or nothing to ask)."""
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class Device(ctypes.Structure):
            # DISPLAY_DEVICEW: its size, the output's name, the adapter's own name, flags, ids.
            _fields_ = (("size", wintypes.DWORD), ("name", wintypes.WCHAR * 32), ("string", wintypes.WCHAR * 128),
                        ("flags", wintypes.DWORD), ("id", wintypes.WCHAR * 128), ("key", wintypes.WCHAR * 128))

        user32 = ctypes.WinDLL("user32")
        found, index = [], 0
        # At most a few dozen outputs: the loop ends at the first missing one.
        while index < 64:
            device = Device()
            device.size = ctypes.sizeof(Device)
            if not user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
                break
            index += 1
            # Each adapter once, whatever the number of its outputs (a card with three displays is one card).
            if device.string and device.string not in found:
                found.append(device.string)
        return found
    except (AttributeError, OSError, ValueError):
        return []


def player_version():
    """The player's version, as its folder says it (player\\bundle.json beside it: its build and when it was made), or
    None without a player."""
    path = player.player_path()
    if not path:
        return None
    try:
        with open(os.path.join(os.path.dirname(path), "bundle.json"), encoding="utf-8-sig") as f:
            made = json.load(f)
        return "%s (built %s)" % (made.get("version") or "?", made.get("built_at") or "?")
    except (OSError, ValueError, AttributeError):
        # A player without its note (a developer's build): there, without a version to say.
        return "beside the launcher, its version not said"


def left_words(w, left):
    """What a report left out (make()'s list of kinds) as one line in the words of `w` (an i18n.Words)."""
    return ", ".join(w("report.left." + kind) for kind, _count in left) or w("report.left.none")


def default_path(now=None):
    """Where Help's Save a report puts it: the user's Downloads folder, under the report's name for this moment."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    return os.path.join(downloads(), NAME % stamp)


def downloads():
    """The user's Downloads folder (Windows' own, wherever it was moved to), else Downloads in the home folder; the
    launcher's own folder where neither is there."""
    if sys.platform == "win32":
        try:
            import ctypes
            import uuid
            from ctypes import wintypes
            # FOLDERID_Downloads, asked of the shell: the folder a person finds downloads in, moved or not.
            folder = uuid.UUID("{374DE290-123F-4565-9164-39C4925E467B}")
            guid = (ctypes.c_byte * 16).from_buffer_copy(folder.bytes_le)
            found = wintypes.LPWSTR()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(found)) == 0:
                path = found.value
                ctypes.windll.ole32.CoTaskMemFree(found)
                if path and os.path.isdir(path):
                    return path
        except (AttributeError, OSError, ValueError):
            pass
    home = os.path.join(os.path.expanduser("~"), "Downloads")
    return home if os.path.isdir(home) else st.config_dir()


def make(state, path=None, devices=None, now=None):
    """The report, written whole or not at all; returns (its path, what was left out: [(kind, how many times)]).
    `devices`: the sound devices when the caller has them (the window's Sound page asked already), else the player is
    asked here (up to its time limit)."""
    path = path or default_path(now)
    scrub = scrubber(state)
    made = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
    files = {}
    # The launcher's own log, the two before it too.
    logs = os.path.dirname(st.launcher_log())
    for name in removal.LOG_NAMES:
        text = _read(os.path.join(logs, name))
        if text is not None:
            files["launcher/" + name] = text
    # The game's log for the current server's app: its end, the last games.
    server = state.server()
    game_log = player.app_log(apps.local(server["url"]) if server else None)
    text = _read(game_log, tail=PLAYER_LOG_TAIL) if game_log else None
    if text is not None:
        files["player/player.log"] = text
    # The settings, the sign-ins out of the launcher's.
    text = _read(st.LauncherState.path())
    if text is not None:
        files["settings/settings.json"] = _settings(text)
    text = _read(player.settings_path())
    if text is not None:
        files["settings/player-settings.txt"] = text
    # The displays, as the launcher's log has them at each start, and the sound devices.
    files["system/displays.txt"] = "\n".join(displays.describe(displays.connected())) + "\n"
    listed = devices if devices is not None else player.audio_devices()
    files["system/sound.txt"] = "".join("%s%s\n    %s\n" % (d["name"], " (default)" if d["default"] else "", d["id"])
                                        for d in listed) or "The player listed no sound devices.\n"
    # The last connection test, as Copy gives it, in English.
    from opendmtq_client import connection, i18n
    tested = connection.last()
    if tested is not None:
        files["system/connection-test.txt"] = tested.text(i18n.Words("en"))
    # Every file with what is left out taken out, about.txt last: it says what was.
    written = {name: scrub(text) for name, text in files.items()}
    cards = graphics()
    about = ["OpenDMTQ report, made %s" % made, "",
             "launcher: %s" % __version__, "player: %s" % (player_version() or "none beside the launcher"),
             "Windows: %s" % windows(), "graphics: %s" % (", ".join(cards) if cards else "not said"), "",
             "Left out, each replaced by a word in angle brackets:"]
    about += ["  %s %s: %d" % (WORDS[kind], kind, n) for kind, n in scrub.left()] or ["  nothing found to leave out"]
    written["about.txt"] = scrub("\n".join(about) + "\n")
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    part = path + ".part"
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            for name in ["about.txt"] + sorted(n for n in written if n != "about.txt"):
                z.writestr(name, written[name])
        os.replace(part, path)
    finally:
        # Whatever stopped it (a full disk): nothing half made stays under the report's name or beside it.
        if os.path.exists(part):
            os.remove(part)
    left = scrub.left()
    # The launcher's own log names it as it is (a later report leaves the user's name out of that line too).
    log.info("saved a report: %s (left out: %s)", path, ", ".join("%s %d" % (kind, n) for kind, n in left) or "nothing")
    return path, left
