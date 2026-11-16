"""The list of the program's own files with their SHA-256, as a release brought them, and the look the repair takes at
them: which are missing, which changed, and (where the install knows its release) each put back from that release.

Where the list is: the Windows bundle's in app/MANIFEST.sha256 (written when the bundle is made, host/windows/build.sh),
a host install's in .host/manifest.sha256 (written by host/get.sh from the code it downloaded). Each line as sha256sum
writes one: the hash, two spaces, the path from the install's folder (with or without a leading ./). A clone of the
repository has none: git knows its files.

Standard library only, and runnable as a script, so a build or an install can write the list before any of this
program's libraries are installed:

    python3 manifest.py write FOLDER [OUT]      the list of every file under FOLDER (OUT: written there, not printed)
    python3 manifest.py check FOLDER [LIST]     what is missing or changed, against LIST (default: the install's own)
"""

import hashlib
import io
import os
import sys
import tarfile
import tempfile
import urllib.request

# Where an install keeps its list, from its folder: the Windows bundle's, then a host install's.
PLACES = (os.path.join("app", "MANIFEST.sha256"), os.path.join(".host", "manifest.sha256"))

# What is never part of the program's files: the settings, the data, this install's own run files and programs, and
# Python's caches, which Python writes as it runs.
NOT_PROGRAM = (".env", "data", ".host", "__pycache__", ".git", "VERSION")

# The release's code, by its tag, as host/get.sh downloads it. OPENDMTQ_TARBALL gives another copy (the tests give their
# own, as they do to get.sh).
RELEASE_URL = "https://github.com/kanggu12/openDMTQ/archive/refs/tags/v{version}.tar.gz"


def digest(path):
    """A file's SHA-256, read in pieces (the bundle's runtime has big files)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def program_files(folder):
    """Every file of the program under folder, by its path from there (with /), leaving out NOT_PROGRAM."""
    out = []
    for top, dirs, names in os.walk(folder):
        rel_top = os.path.relpath(top, folder)
        # Not into the settings, the data or this install's own folders, at the top or (caches) anywhere.
        dirs[:] = sorted(d for d in dirs if not (d in NOT_PROGRAM and (rel_top == "." or d == "__pycache__")))
        for name in sorted(names):
            rel = name if rel_top == "." else f"{rel_top}/{name}".replace(os.sep, "/")
            if rel_top == "." and name in NOT_PROGRAM:
                continue
            # Compiled caches outside a __pycache__ folder are Python's too.
            if name.endswith((".pyc", ".pyo")):
                continue
            out.append(rel)
    return out


def write(folder, out=None, skip=()):
    """The list of folder's program files; written to out when given (not listing itself), else returned as text."""
    skip = set(skip) | ({os.path.relpath(out, folder).replace(os.sep, "/")} if out else set())
    lines = [f"{digest(os.path.join(folder, rel))}  {rel}" for rel in program_files(folder) if rel not in skip]
    text = "\n".join(lines) + "\n"
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return text


def read(path):
    """A list as {path: sha256}; lines that are not "hash  path" are left out."""
    entries = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            sha, sep, rel = line.rstrip("\r\n").partition("  ")
            if sep and len(sha) == 64:
                # sha256sum's "./path" and a plain path are the same file.
                entries[rel[2:] if rel.startswith("./") else rel] = sha.lower()
    return entries


def find(root):
    """The install's own list, or None when it has none."""
    for place in PLACES:
        path = os.path.join(root, place)
        if os.path.isfile(path):
            return path
    return None


def check(root, entries):
    """(missing, changed): the listed files that are not there, and those that are not as listed, by path."""
    missing, changed = [], []
    for rel, sha in sorted(entries.items()):
        path = os.path.join(root, *rel.split("/"))
        if not os.path.isfile(path):
            missing.append(rel)
        else:
            try:
                if digest(path) != sha:
                    changed.append(rel)
            except OSError:
                # A file that cannot be read is as good as missing.
                missing.append(rel)
    return missing, changed


def release_url(version):
    """Where this install's release's code comes from: OPENDMTQ_TARBALL, or the release's tag on GitHub."""
    return os.environ.get("OPENDMTQ_TARBALL") or RELEASE_URL.format(version=version)


def put_back(root, entries, paths, url):
    """The files at paths (as listed) put back from the release's code at url, each only when the release's copy is the
    listed one. Returns the paths put back; raises OSError (and tarfile's errors) when the release cannot be had."""
    wanted = {rel: entries[rel] for rel in paths if rel in entries}
    done = []
    with tempfile.TemporaryFile() as tmp:
        # The whole archive first: a download cut short puts nothing back.
        with urllib.request.urlopen(url, timeout=60) as r:
            for block in iter(lambda: r.read(1024 * 1024), b""):
                tmp.write(block)
        tmp.seek(0)
        with tarfile.open(fileobj=tmp, mode="r:*") as tar:
            for member in tar:
                # GitHub's archives have one folder on top (openDMTQ-0.11.0/): the paths are below it.
                rel = member.name.split("/", 1)[1] if "/" in member.name else ""
                if rel not in wanted or not member.isfile():
                    continue
                data = tar.extractfile(member).read()
                # Only the very file the list names.
                if hashlib.sha256(data).hexdigest() != wanted[rel]:
                    continue
                path = os.path.join(root, *rel.split("/"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                # Beside it, then over it: a program reading it meanwhile never reads half of one.
                with open(path + ".repair", "wb") as f:
                    f.write(data)
                # The release's mode (a script stays one).
                os.chmod(path + ".repair", member.mode & 0o777 or 0o644)
                os.replace(path + ".repair", path)
                done.append(rel)
    return done


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) >= 2 and argv[0] == "write":
        text = write(argv[1], argv[2] if len(argv) > 2 else None)
        if len(argv) == 2:
            sys.stdout.write(text)
        return 0
    if len(argv) >= 2 and argv[0] == "check":
        listed = argv[2] if len(argv) > 2 else find(argv[1])
        if not listed:
            print("no list of the program's files here")
            return 2
        missing, changed = check(argv[1], read(listed))
        for rel in missing:
            print(f"missing  {rel}")
        for rel in changed:
            print(f"changed  {rel}")
        return 1 if missing or changed else 0
    print(__doc__.strip().splitlines()[-2:][0].strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
