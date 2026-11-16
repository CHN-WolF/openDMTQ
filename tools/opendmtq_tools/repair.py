"""The repair: a look at everything the server can make again by itself, and each thing put back that is not right. The
admin pages' Server page and the API run it (with what only they can do besides), and both command lines run it as
`python -m opendmtq_tools.repair` (./opendmtq repair).

Each step answers (state, detail): "ok" (as it should be), "fixed" (it was not, and now is), "bad" (it is not, and this
cannot put it back: detail says what was found), or "skip" (nothing to look at here). The pages say each in their words
(repair.<step>.<state>); this module's own lines, for the command lines, are in English.

The steps: the server's folders; the database's integrity; the owner's sign-in for the players' site (owner.pass); the
song list, made again from what was imported and added; the phone app (is there one built for this address); and the
program's own files against the install's list of them (manifest.py), each one put back from the install's release where
it knows it.
"""

import json
import os
import sqlite3
import subprocess
import sys

from . import manifest, owner, server_data

# The steps, in the order they run and are shown.
STEPS = ("folders", "database", "owner", "songs", "app", "files")


def folders(layout):
    """The folders the server keeps its state in, made where they are missing (a folder deleted by hand)."""
    wanted = [layout.state, os.path.join(layout.state, "live"), os.path.join(layout.state, "live-rec"),
              os.path.join(layout.apk, "out"), layout.custom, layout.backups, layout.logs]
    made = []
    for folder in wanted:
        if not os.path.isdir(folder):
            try:
                os.makedirs(folder, exist_ok=True)
                made.append(folder)
            except OSError:
                # One that cannot be made: said as such, the rest goes on.
                return "bad", folder
    return ("fixed", ", ".join(made)) if made else ("ok", "")


def database(layout):
    """SQLite's own full check of the database. A damaged one cannot be put back here: a backup can (the Backups page)."""
    if not os.path.isfile(layout.db):
        # A new server: the game server makes it at its start.
        return "skip", ""
    try:
        con = sqlite3.connect(f"file:{layout.db}?mode=ro", uri=True, timeout=30)
        try:
            found = [r[0] for r in con.execute("PRAGMA integrity_check(5)")]
        finally:
            con.close()
    except sqlite3.Error as e:
        return "bad", str(e)
    return ("ok", "") if found == ["ok"] else ("bad", "; ".join(found))


def owner_file(layout, user, password):
    """The owner's sign-in for the players' site, beside the database, as the admin pages write it at their start."""
    if not password:
        # Nothing to write it from here (the Docker tools see no password): the admin pages write it at their start.
        return "skip", ""
    done = owner.write_file(os.path.join(layout.state, "owner.pass"), user or "admin", password)
    return {"kept": ("ok", ""), "written": ("fixed", ""), "removed": ("fixed", "")}.get(done, ("bad", done))


def song_list(layout):
    """The game's song list made again from the imported song data and the songs added, as at every start."""
    try:
        from . import songs
    except ImportError as e:
        return "skip", str(e)
    if not songs.has_game_data():
        # Nothing to make it from: the import brings the client data.
        return "skip", ""
    try:
        songs.rebuild()
    except (songs.SongError, OSError, ValueError) as e:
        return "bad", str(e)
    return "fixed", ""


def app(layout, public_host):
    """The phone app on offer: one built for this server's address, its file there. Not built here (that takes minutes):
    "bad" with what is wrong, and the caller starts the build (the admin pages' App build, the command lines' builder)."""
    base = os.path.join(layout.apk, "base")
    if not any(n.lower().endswith(".apk") for n in (os.listdir(base) if os.path.isdir(base) else [])):
        # No client to build from: the import brings one.
        return "skip", ""
    try:
        with open(os.path.join(layout.apk, "out", "latest.json"), encoding="utf-8") as f:
            made = json.load(f)
    except (OSError, ValueError):
        return "bad", "missing"
    if not os.path.isfile(os.path.join(layout.apk, "out", os.path.basename(str(made.get("file", ""))))):
        return "bad", "missing"
    if public_host and made.get("host") != public_host:
        return "bad", "other_address"
    return "ok", str(made.get("file", ""))


def files(root, version=""):
    """The program's own files against the install's list: missing or changed ones put back from the release the install
    came from (its VERSION) when there is one to ask; else said, by name. ("skip", "") without a list (a clone, Docker)."""
    listed = manifest.find(root) if root else None
    if not listed:
        return "skip", ""
    entries = manifest.read(listed)
    missing, changed = manifest.check(root, entries)
    bad = missing + changed
    if not bad:
        return "ok", str(len(entries))
    put = []
    # The release's code, by its number: the very files the list names, or none.
    if version or os.environ.get("OPENDMTQ_TARBALL"):
        try:
            put = manifest.put_back(root, entries, bad, manifest.release_url(version))
        except Exception:  # noqa: BLE001 - no network, no such release: what was found is said instead
            put = []
    left = [rel for rel in bad if rel not in put]
    if not left:
        return "fixed", ", ".join(put)
    return "bad", ", ".join(left[:8]) + (f" (+{len(left) - 8})" if len(left) > 8 else "")


def run(layout, root="", version="", user="", password="", public_host="", say=print):
    """Every step, in order: {step: (state, detail)}, each said as it ends (an English line)."""
    results = {}
    for step in STEPS:
        if step == "folders":
            result = folders(layout)
        elif step == "database":
            result = database(layout)
        elif step == "owner":
            result = owner_file(layout, user, password)
        elif step == "songs":
            result = song_list(layout)
        elif step == "app":
            result = app(layout, public_host)
        else:
            result = files(root, version)
        results[step] = result
        say(f"{step}: {result[0]}" + (f" ({result[1]})" if result[1] else ""))
    return results


def install_root():
    """The install's folder (where its list of files is), as the host program says it; empty in a container."""
    return os.environ.get("OPENDMTQ_ROOT", "")


def install_version(root):
    """The release the install came from (its VERSION file), or ""."""
    for place in (os.path.join(root, "VERSION"), os.path.join(root, "app", "VERSION")) if root else ():
        try:
            with open(place, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            continue
    return ""


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = install_root()
    results = run(server_data.Layout(), root=root, version=install_version(root),
                  user=os.environ.get("ADMIN_USER", ""), password=os.environ.get("ADMIN_PASSWORD", ""),
                  public_host=os.environ.get("PUBLIC_HOST", ""), say=lambda line: print(line, flush=True))
    # --build (the command lines): the app built now when it has to be, as ./opendmtq apk builds it.
    if "--build" in argv and results["app"][0] == "bad":
        print("app: building it again", flush=True)
        built = subprocess.run([sys.executable, "-m", "opendmtq_tools.builder", "--force"]).returncode == 0
        results["app"] = ("fixed", "") if built else ("bad", "the build failed (see above)")
        print(f"app: {results['app'][0]}", flush=True)
    # What was found, as the last line, for whatever runs this.
    print("result " + json.dumps({step: state for step, (state, _) in results.items()}), flush=True)
    # A step that is still not right: the command says so with its status.
    return 1 if any(state == "bad" for state, _ in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
