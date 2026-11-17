"""The previous release's full update package, kept in the build's releases folder so that vpk makes a delta package
from it (build.sh, step 4): what a launcher of that version downloads instead of the whole package.

    python3 client/packaging/windows/previous.py RELEASES_DIR VERSION [FOLDER_OR_PACKAGE...]

Leaves in RELEASES_DIR the newest full package of a version before VERSION, found there (the last build into the same
folder) or among the folders and packages given (the release before, downloaded: a release names its package
opendmtq.client-<version>-full.nupkg, 0.10.0 OpenDMTQ.Client-0.10.0-full.nupkg), under the name it has, and nothing
else: the other files there are an earlier build's (its installer, its feed, its other packages), which vpk would list
in the new feed. vpk lists the package kept as the full package the delta is made from, and a launcher of that version
is the one that takes the delta (client/opendmtq_client/updates.py). Prints the version kept, or "none".
"""

import os
import re
import shutil
import sys

# A full package's file name in any case, as vpk names it (OpenDMTQ.Client-1.2.3-full.nupkg) or a release does
# (opendmtq.client-1.2.3-full.nupkg).
FULL = re.compile(r"^opendmtq\.client-(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)-full\.nupkg$", re.IGNORECASE)


def order(version):
    """A version as Semantic Versioning orders it (a pre-release before its release, its parts compared number by
    number and word by word), as something Python compares."""
    core, _, pre = version.partition("+")[0].partition("-")
    numbers = tuple(int(n) for n in core.split("."))
    if not pre:
        # A release comes after every pre-release of its version.
        return numbers, (1,)
    # Numbers come before words, and compare as numbers.
    parts = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return numbers, (0,) + parts


def candidates(places):
    """{version: path} of the full packages in these folders and among these files (the first found of a version)."""
    found = {}
    for place in places:
        paths = ([os.path.join(place, name) for name in sorted(os.listdir(place))] if os.path.isdir(place)
                 else [place] if os.path.isfile(place) else [])
        for path in paths:
            match = FULL.match(os.path.basename(path))
            if match:
                found.setdefault(match.group("version"), path)
    return found


def keep_previous(releases, version, sources=()):
    """Leave in `releases` only the newest full package before `version`, from there or from `sources`; returns its
    version, or None."""
    os.makedirs(releases, exist_ok=True)
    found = candidates([releases] + list(sources))
    usable = [v for v in found if order(v) < order(version)]
    kept = max(usable, key=order) if usable else None
    keep_name = None
    if kept is not None:
        keep_name = os.path.basename(found[kept])
        if os.path.dirname(os.path.abspath(found[kept])) != os.path.abspath(releases):
            # From the release before: copied in beside where the new one goes.
            shutil.copyfile(found[kept], os.path.join(releases, keep_name))
    for name in os.listdir(releases):
        path = os.path.join(releases, name)
        if name != keep_name and os.path.isfile(path):
            # An earlier build's file: its installer, its feed, another package.
            os.remove(path)
    return kept


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip().splitlines()[3].strip(), file=sys.stderr)
        return 2
    kept = keep_previous(argv[0], argv[1], argv[2:])
    print(kept or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
