"""The server's data, part by part: how much each part holds, a backup before any of it goes, and deleting the parts asked
for. The admin pages' Server page, the API and both command lines (./opendmtq delete-data, with Docker Compose and on a host
install) all do it here, so that a part means the same everywhere.

Everything here works while the server runs: the database keeps its tables and loses its rows (the game server and the
admin pages go on with it, empty), a recording still being made stays, and a log that a program has open is emptied rather
than removed (Windows does not let a file in use go). The paths come from the environment, as the admin service and the
tools have them (OPENDMTQ_DB and the rest).

    python -m opendmtq_tools.server_data sizes                  the parts as JSON: their bytes, and whether they can go here
    python -m opendmtq_tools.server_data delete PART... [--backup] [--keep NAME]
"""

import argparse
import datetime
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time

# The parts, in the order the Server page lists them. The words for each are the pages' (data.<part> in strings.py).
PARTS = ("database", "recordings", "songs", "apps", "backups", "logs", "game")

# The database's tables a deletion keeps: the rankings' change number (the server's boards are worked out again past it, as
# after a restore) and the API's tokens (the owner's own keys to these pages; the Accounts page deletes them).
KEPT_TABLES = ("BoardStamp", "ApiToken")

# What a backup holds of the custom folder, as the admin pages' backups have it (admin/backups.py, make_backup).
BACKED_UP = ("songs", "hidden.json", "ids.json")

# What a backup's name starts with, as the admin pages' and the command line's backups are named (admin/backups.py
# BACKUP_PREFIX): what it is, then when it was made and why, all in lower case.
BACKUP_PREFIX = "opendmtq-server-backup-"


class Layout:
    """Where each part lives, from the environment as the admin service and the tools see it: OPENDMTQ_DB (the database,
    with the server's state beside it), OPENDMTQ_APK, OPENDMTQ_BACKUPS, OPENDMTQ_CUSTOM, OPENDMTQ_LOGS and
    OPENDMTQ_CONTENT, each with the admin service's own default."""

    def __init__(self, environ=None):
        e = os.environ if environ is None else environ
        # The database file, and the folder of the server's state it is in (the recordings and the changes' log too).
        self.db = e.get("OPENDMTQ_DB", "/data/dmtq.db3")
        self.state = os.path.dirname(self.db)
        # The apps folder: the client (base/), the apps built (out/), the signing key (keystore/, never deleted here).
        self.apk = e.get("OPENDMTQ_APK", "/apk")
        self.backups = e.get("OPENDMTQ_BACKUPS", "/backups")
        # Songs added on the admin pages, and what is made from them.
        self.custom = e.get("OPENDMTQ_CUSTOM", "/custom")
        # The server's logs (Apache's, PHP's, and on a host install this program's own).
        self.logs = e.get("OPENDMTQ_LOGS", "/data/logs")
        # The client data and the song data the import brought in.
        self.content = e.get("OPENDMTQ_CONTENT", "/srv/content")

    def folders(self, part):
        """The folders (and files) a part is made of, as paths; some may not be there."""
        return {
            "database": [self.db, self.db + "-wal", self.db + "-shm"],
            "recordings": [os.path.join(self.state, "live-rec")],
            "songs": [os.path.join(self.custom, "songs")],
            "apps": [os.path.join(self.apk, "out")],
            "backups": [self.backups],
            "logs": [self.logs, os.path.join(self.state, "changes.log"), os.path.join(self.state, "changes.log.1")],
            "game": [self.content, os.path.join(self.apk, "base")],
        }[part]


def size_of(path, seen=None):
    """The bytes under a path (a file: its own), each file with more than one name counted once; 0 when it is not there."""
    seen = set() if seen is None else seen
    try:
        top = os.lstat(path)
    except OSError:
        return 0
    if not os.path.isdir(path):
        return top.st_size
    total = 0
    for folder, _, names in os.walk(path):
        for name in names:
            try:
                st = os.lstat(os.path.join(folder, name))
            except OSError:
                continue
            # A file linked from two places (a broadcast's piece in its stream and in its recording) counts once.
            if st.st_nlink > 1:
                if (st.st_dev, st.st_ino) in seen:
                    continue
                seen.add((st.st_dev, st.st_ino))
            total += st.st_size
    return total


def can_delete(layout, part):
    """Whether this process may delete the part where it runs: the folder it is in can be written (the admin service of a
    Docker Compose server reads the game's files only, and cannot delete them; its command line can)."""
    for path in layout.folders(part):
        # A path that is there, or else the folder that would hold it.
        where = path if os.path.isdir(path) else os.path.dirname(path)
        if os.path.exists(where) and not os.access(where, os.W_OK):
            return False
    return True


def sizes(layout):
    """Each part: {part: {"bytes": n, "can_delete": bool}}, in PARTS' order."""
    out = {}
    for part in PARTS:
        # One count of linked files per part: a recording's pieces may be the live view's too.
        seen = set()
        out[part] = {"bytes": sum(size_of(p, seen) for p in layout.folders(part)), "can_delete": can_delete(layout, part)}
    return out


def backup(layout, reason="before-delete"):
    """A backup as the admin pages make one (the database, the signing key, the songs added, their hidden flags and ids),
    in the backups folder; returns its file name, or None when there is no database to back up. For the host install's
    command line, which has no admin pages of its own to ask."""
    if not os.path.isfile(layout.db):
        return None
    os.makedirs(layout.backups, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(layout.backups, f"{BACKUP_PREFIX}{stamp}-{reason}.tar.gz")
    n = 1
    # Two in one second must not overwrite each other.
    while os.path.exists(path):
        n += 1
        path = os.path.join(layout.backups, f"{BACKUP_PREFIX}{stamp}-{reason}-{n}.tar.gz")
    partial = path + ".part"
    with tempfile.TemporaryDirectory() as tmp:
        snap = os.path.join(tmp, "dmtq.db3")
        # SQLite's online backup: consistent while the server writes.
        src, dst = sqlite3.connect(layout.db, timeout=30), sqlite3.connect(snap)
        try:
            with dst:
                src.backup(dst)
        finally:
            src.close()
            dst.close()
        # Readable by its owner only: it holds the signing key.
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as f, tarfile.open(fileobj=f, mode="w:gz") as tar:
                tar.add(snap, arcname="dmtq.db3")
                keystore = os.path.join(layout.apk, "keystore")
                if os.path.isdir(keystore):
                    tar.add(keystore, arcname="keystore")
                # The custom folder itself even when empty: a restore then knows this server had no added songs.
                folder = tarfile.TarInfo("custom")
                folder.type, folder.mode, folder.mtime = tarfile.DIRTYPE, 0o755, int(time.time())
                tar.addfile(folder)
                for name in BACKED_UP:
                    item = os.path.join(layout.custom, name)
                    if os.path.exists(item):
                        tar.add(item, arcname=f"custom/{name}")
        except BaseException:
            if os.path.exists(partial):
                os.remove(partial)
            raise
    # Under its own name only when whole: half an archive must never be listed as a backup.
    os.replace(partial, path)
    return os.path.basename(path)


def _empty_database(layout, say):
    """Every row of the database goes but those of KEPT_TABLES; its tables stay, so the game server and the admin pages
    go on with it as with a new server. Then it is made small again."""
    if not os.path.isfile(layout.db):
        say("database: none yet")
        return True
    con = sqlite3.connect(layout.db, timeout=30)
    try:
        # As long as a save of the game server's takes, at most.
        con.execute("PRAGMA busy_timeout = 30000")
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        # All of it in one change: either every table is empty afterwards or none was touched.
        with con:
            for table in tables:
                if table not in KEPT_TABLES:
                    con.execute(f'DELETE FROM "{table}"')
        try:
            # Its pages given back to the disk. Not being able to (a long read elsewhere) loses nothing.
            con.execute("VACUUM")
        except sqlite3.OperationalError:
            pass
    finally:
        con.close()
    say(f"database: emptied ({len([t for t in tables if t not in KEPT_TABLES])} tables)")
    return True


def _remove(path):
    """A file or a folder gone; True when it is gone."""
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        elif os.path.lexists(path):
            os.remove(path)
        return True
    except OSError:
        return False


def _empty_file(path):
    """A file made empty in place: a log that a program has open keeps writing to it (it appends), and Windows lets an
    open file be emptied but not removed."""
    try:
        with open(path, "r+b") as f:
            f.truncate(0)
        return True
    except OSError:
        return False


def _delete_recordings(layout, say):
    """Every recording but one still being made (its phone still writes to it); the limits the owner set stay."""
    root = os.path.join(layout.state, "live-rec")
    gone = kept = 0
    for player in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        folder = os.path.join(root, player)
        # One folder per player, named by a number; limits.json and anything else of the owner's are no player.
        if not (player.isdigit() and os.path.isdir(folder)):
            continue
        for rec in sorted(os.listdir(folder)):
            path = os.path.join(folder, rec)
            if os.path.exists(os.path.join(path, ".open")):
                kept += 1
                continue
            gone += _remove(path)
        # The player's folder with their last recording.
        try:
            os.rmdir(folder)
        except OSError:
            pass
    say(f"recordings: {gone} deleted" + (f", {kept} still being made kept" if kept else ""))
    return True


def _delete_songs(layout, say, rebuild=True):
    """The songs added on the admin pages, with their tiles; the ids handed out stay (a new song never takes an old one's,
    to which old plays point). The song list is made again without them, when this process can make it."""
    folder = os.path.join(layout.custom, "songs")
    names = []
    for song in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        try:
            with open(os.path.join(folder, song, "song.json"), encoding="utf-8") as f:
                names.append(str(json.load(f).get("name", "")))
        except (OSError, ValueError, AttributeError):
            pass
    gone = _remove(folder)
    for name in names:
        # Its tile beside the list, made from its jacket.
        if name:
            _remove(os.path.join(layout.custom, "thumbs", name + ".jpg"))
    if not gone:
        say("songs: could not be deleted")
        return False
    say(f"songs: {len(names)} added songs deleted")
    if rebuild:
        try:
            # The game's song list without them, now: phones get it at their next start.
            from . import songs
            if songs.has_game_data():
                songs.rebuild()
        except Exception as e:  # noqa: BLE001 - the songs are gone either way; the next start makes the list
            say(f"songs: the song list is made again at the next start ({e.__class__.__name__})")
    return True


def _delete_apps(layout, say):
    """The apps built (and what was made with them: the QR code, the PC installer's copy). The signing key stays: the next
    app installs over the phones' old one. The next start builds the app again."""
    folder = os.path.join(layout.apk, "out")
    gone = 0
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        gone += _remove(os.path.join(folder, name))
    say(f"apps: {gone} files deleted")
    return True


def _delete_backups(layout, say, keep=()):
    """Every backup but those in keep (the one made just before, when one was)."""
    gone = 0
    for name in sorted(os.listdir(layout.backups)) if os.path.isdir(layout.backups) else []:
        if name in keep or not (name.endswith(".tar.gz") or name.endswith(".part")):
            continue
        gone += _remove(os.path.join(layout.backups, name))
    say(f"backups: {gone} deleted" + (f", {', '.join(keep)} kept" if keep else ""))
    return True


def _delete_logs(layout, say):
    """The logs emptied: the ones being written in place, their older copies (.1, .2) removed."""
    done = 0
    files = [os.path.join(layout.logs, n) for n in sorted(os.listdir(layout.logs))] if os.path.isdir(layout.logs) else []
    files += [os.path.join(layout.state, "changes.log"), os.path.join(layout.state, "changes.log.1")]
    for path in files:
        if not os.path.isfile(path):
            continue
        # An older copy goes; one a program writes to is emptied (and an older copy that cannot go is emptied too).
        old = path.rsplit(".", 1)[-1].isdigit()
        done += (old and _remove(path)) or _empty_file(path)
    say(f"logs: {done} emptied")
    return True


def _delete_game(layout, say):
    """The client data, the song data and the client the import brought in: what is in their folders, the folders
    themselves stay for the next import."""
    gone = 0
    for folder in (layout.content, os.path.join(layout.apk, "base")):
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            gone += _remove(os.path.join(folder, name))
    say(f"game files: {gone} deleted")
    return True


def delete(layout, parts, keep=(), say=print, rebuild=True):
    """Deletes the parts asked for, in PARTS' order; keep: backups' names that stay (the one made just before). Returns
    {part: True when it is done}. A part this process cannot delete here (can_delete) is left as it is, False."""
    unknown = [p for p in parts if p not in PARTS]
    if unknown:
        raise ValueError(f"no such part: {', '.join(unknown)}")
    done = {}
    for part in PARTS:
        if part not in parts:
            continue
        if not can_delete(layout, part):
            say(f"{part}: not here (read-only)")
            done[part] = False
            continue
        try:
            if part == "database":
                done[part] = _empty_database(layout, say)
            elif part == "recordings":
                done[part] = _delete_recordings(layout, say)
            elif part == "songs":
                done[part] = _delete_songs(layout, say, rebuild=rebuild)
            elif part == "apps":
                done[part] = _delete_apps(layout, say)
            elif part == "backups":
                done[part] = _delete_backups(layout, say, keep)
            elif part == "logs":
                done[part] = _delete_logs(layout, say)
            else:
                done[part] = _delete_game(layout, say)
        except (OSError, sqlite3.Error) as e:
            say(f"{part}: {e}")
            done[part] = False
    return done


def main(argv=None):
    p = argparse.ArgumentParser(prog="server_data", description="The server's data, part by part.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sizes", help="each part's bytes, as JSON")
    d = sub.add_parser("delete", help="delete these parts")
    d.add_argument("parts", nargs="+", choices=PARTS)
    d.add_argument("--backup", action="store_true", help="make a backup first, and keep it")
    d.add_argument("--keep", action="append", default=[], help="a backup's file name that stays")
    args = p.parse_args(argv)
    layout = Layout()
    if args.cmd == "sizes":
        print(json.dumps(sizes(layout)))
        return 0
    keep = list(args.keep)
    if args.backup:
        made = backup(layout)
        if made:
            print(f"backup {made}", flush=True)
            keep.append(made)
    done = delete(layout, args.parts, keep=keep, say=lambda line: print(line, flush=True))
    return 0 if all(done.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
