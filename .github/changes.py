"""Whether a change touches anything but the guides, for CI (ci.yml's changes job): prints code=true or code=false.

    python3 .github/changes.py <base commit> <head commit>      what the commits between them change
    python3 .github/changes.py - < <paths, one a line>          those paths

A change to the guides alone (README.md, CONTRIBUTING.md, docs/ and the other pages of words below) runs CI's test job,
whose repository checks read them, and skips the heavy jobs, whose builds, programs and tests read none of them. Anything
else is code: a path outside the guides, a guide a heavy job's test reads all the same, no paths at all, or a base that
cannot be told (a new branch, a release's tag, a history written again). Then everything runs.
"""

import fnmatch
import subprocess
import sys

# The pages of words for people: none of them is built into anything, served, or read by the heavy jobs' checks.
GUIDES = (
    "README.md",
    "CONTRIBUTING.md",
    "docs/*",
    "arm32/README.md",
    "client/README.md",
    ".github/CODE_OF_CONDUCT.md",
    ".github/SECURITY.md",
    ".github/pull_request_template.md",
    ".github/ISSUE_TEMPLATE/*",
)
# Guides a heavy job reads all the same: the PC client's unit tests hold the launcher's defaults to this one's table.
READ = ("docs/windows-player.md",)


def is_guide(path):
    """A path of the guides alone (fnmatch's * goes into folders too)."""
    return path not in READ and any(fnmatch.fnmatchcase(path, pattern) for pattern in GUIDES)


def changed(base, head):
    """The paths the commits from base to head change, or None when that cannot be told."""
    # No base (a release's tag, a run started by hand) or the zeros of a branch pushed for the first time.
    if not base or not base.strip("0"):
        return None
    try:
        result = subprocess.run(["git", "diff", "--name-only", base, head], capture_output=True, text=True)
    except OSError:
        # No git here to ask.
        return None
    return result.stdout.splitlines() if result.returncode == 0 else None


def code(paths):
    """True unless every path is one of the guides; no paths is code too (nothing to go by)."""
    return not paths or not all(is_guide(p) for p in paths)


def main():
    if sys.argv[1:] == ["-"]:
        paths = [line.strip() for line in sys.stdin if line.strip()]
    elif len(sys.argv) == 3:
        paths = changed(sys.argv[1], sys.argv[2])
    else:
        sys.exit(__doc__)
    print(f"code={'true' if code(paths) else 'false'}")


if __name__ == "__main__":
    main()
