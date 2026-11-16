"""A release's files: one name for each, saying what it is, for which system and architecture, and which version.

    python3 .github/release_assets.py layout VERSION OUT --runtime ZIP --client DIR --windows ZIP --chart TGZ
    python3 .github/release_assets.py check VERSION DIR
    python3 .github/release_assets.py names VERSION

`layout` copies what the release job built under the release's names into OUT, writes the checksums of all of them, and
checks the result (`check`): exactly these files, each with the version in its name, the programs for Windows built for
x64, and the PC client's update feed naming the package beside it with its size and hash. `names` prints the names. The
release notes' table of files (release_notes.py) is made from the same list. The standard library only: it runs on the
runner's own Python.
"""
import argparse
import hashlib
import json
import shutil
import struct
import sys
import tarfile
import zipfile
from pathlib import Path

# The repository on GitHub and its container registry, for the release notes.
REPO = "https://github.com/kanggu12/openDMTQ"
REGISTRY = "ghcr.io/kanggu12"

# The PC client's update feed: Velopack's names, which the installed launchers look for (Velopack's GitHub source reads
# the asset releases.<channel>.json of each recent release, channel "win", then downloads the asset its FileName names).
# They cannot change without leaving every installed launcher without updates: the package id OpenDMTQ.Client is the
# install folder's name too, and Velopack names the package <id>-<version>-full.nupkg in the install folder as well.
FEED = "releases.win.json"
PACKAGE = "OpenDMTQ.Client-{version}-full.nupkg"

# Every file of a release, in the order the notes list them: (key, name, who it is for, what it runs on). A person
# downloads one of the first three; programs read the others, and the notes say so.
FILES = (
    ("client", "OpenDMTQ-PC-Client-{version}-windows-x64-Setup.exe", "Players on a PC: the PC client's installer",
     "Windows 10 and 11, x64; Linux with Wine"),
    ("server-windows", "OpenDMTQ-Server-{version}-windows-x64.zip", "Server owners on Windows: the whole server",
     "Windows 10 and 11, x64"),
    ("chart", "OpenDMTQ-Server-{version}-helm-chart.tgz", "Server owners on Kubernetes: the Helm chart",
     "Kubernetes, with the images below"),
    ("runtime", "OpenDMTQ-Phone-Runtime-{version}-android-arm64-armv7.zip",
     "the server's app builder adds it to the phone app, for phones that run only 64-bit apps; a server fetches it "
     "itself, and one without internet takes it by hand", "Android"),
    ("feed", FEED, "installed PC clients update themselves from these two", "Windows"),
    ("package", PACKAGE, "", "Windows"),
    ("sums", "OpenDMTQ-{version}-SHA256SUMS.txt", "the SHA-256 of every file here", ""),
)
# The ones a person downloads: the table at the top of the notes.
FOR_PEOPLE = ("client", "server-windows", "chart")

# The images the release pushes, with the platforms each is built for (release.yml's Server image and Tools image).
IMAGES = (
    ("opendmtq-server", "the game server and the players' site", "linux/amd64 and linux/arm64"),
    ("opendmtq-tools", "the server's setup, admin pages and app builder", "linux/amd64 (its 7-Zip is an x86-64 build)"),
)

# The machine type in a Windows program's header for x64 (IMAGE_FILE_MACHINE_AMD64).
X64 = 0x8664


def names(version):
    """{key: file name} of the release `version`."""
    return {key: name.format(version=version) for key, name, _, _ in FILES}


def pe_machine(head):
    """The machine type of a Windows program from its first bytes, or None when they are no Windows program."""
    if head[:2] != b"MZ" or len(head) < 64:
        return None
    # The PE header's place is at 0x3C; the machine type is the two bytes after its "PE\0\0".
    at = struct.unpack_from("<I", head, 0x3C)[0]
    if head[at:at + 4] != b"PE\0\0":
        return None
    return struct.unpack_from("<H", head, at + 4)[0]


def sha256(path):
    """The file's SHA-256, read in pieces: the installer and the bundle are tens of megabytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check(version, folder):
    """What is wrong with the release's files in `folder`: a list of sentences, empty when nothing is."""
    folder = Path(folder)
    want = names(version)
    problems = []
    have = sorted(p.name for p in folder.iterdir())
    # Exactly the release's files: nothing missing, and nothing a person would have to ask about.
    for name in sorted(set(want.values()) - set(have)):
        problems.append(f"{name} is missing")
    for name in sorted(set(have) - set(want.values())):
        problems.append(f"{name} is not one of the release's files")
    if problems:
        return problems
    # The installer: a Windows program for x64.
    with open(folder / want["client"], "rb") as f:
        machine = pe_machine(f.read(4096))
    if machine != X64:
        problems.append(f"{want['client']} is not a Windows program for x64 (machine {machine})")
    # The Windows server: its starter and its Python for x64, under the bundle's one folder.
    with zipfile.ZipFile(folder / want["server-windows"]) as z:
        for member in ("OpenDMTQ/OpenDMTQ.exe", "OpenDMTQ/runtime/python/python.exe"):
            try:
                machine = pe_machine(z.read(member)[:4096])
            except KeyError:
                machine = "absent"
            if machine != X64:
                problems.append(f"{want['server-windows']}: {member} is not a Windows program for x64 ({machine})")
        try:
            said = z.read("OpenDMTQ/app/VERSION").decode().strip()
        except KeyError:
            said = "absent"
        if said != version:
            problems.append(f"{want['server-windows']} says version {said}")
    # The chart: its own version and the app's.
    with tarfile.open(folder / want["chart"]) as t:
        chart = t.extractfile("opendmtq/Chart.yaml").read().decode()
    for line in (f"version: {version}", f"appVersion: {version}"):
        if line not in chart.replace('"', ""):
            problems.append(f"{want['chart']}'s Chart.yaml has no '{line}'")
    # The runtime: both of its Android parts, and its description.
    with zipfile.ZipFile(folder / want["runtime"]) as z:
        listed = set(z.namelist())
    for member in ("bundle.json", "arm64-v8a/libarm32.so", "armeabi-v7a/libopendmtq.so"):
        if member not in listed:
            problems.append(f"{want['runtime']} has no {member}")
    # The update feed: one full package of this version, the one beside it, at its size and hash.
    feed = json.loads((folder / want["feed"]).read_text(encoding="utf-8-sig"))
    assets = feed.get("Assets") or []
    package = folder / want["package"]
    if [(a.get("PackageId"), a.get("Version"), a.get("Type"), a.get("FileName")) for a in assets] != \
            [("OpenDMTQ.Client", version, "Full", want["package"])]:
        problems.append(f"{want['feed']} does not name {want['package']} alone: {assets}")
    elif assets[0].get("Size") != package.stat().st_size or str(assets[0].get("SHA256", "")).lower() != sha256(package):
        problems.append(f"{want['feed']} gives {want['package']} another size or hash")
    # The checksums: every other file, as sha256sum writes them.
    sums = (folder / want["sums"]).read_text(encoding="utf-8").splitlines()
    expected = [f"{sha256(folder / n)}  {n}" for k, n in want.items() if k != "sums"]
    if sums != expected:
        problems.append(f"{want['sums']} is not the checksums of the other files")
    return problems


def layout(version, out, runtime, client, windows, chart):
    """The built files under the release's names in `out` (emptied first), with their checksums; then check()."""
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    want = names(version)
    client = Path(client)
    # From each build's own output: the installer and Velopack's feed and package (client/packaging/windows/build.sh's
    # releases folder), the Windows server bundle (host/windows/build.sh), the chart (helm package), the runtime.
    sources = {
        "client": client / "OpenDMTQ-Setup.exe",
        "server-windows": Path(windows),
        "chart": Path(chart),
        "runtime": Path(runtime),
        "feed": client / FEED,
        "package": client / want["package"],
    }
    for key, source in sources.items():
        shutil.copyfile(source, out / want[key])
    # One file of checksums for all, in the order the notes list the files.
    lines = [f"{sha256(out / want[k])}  {want[k]}" for k in want if k != "sums"]
    (out / want["sums"]).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return check(version, out)


def notes_head(version):
    """The release notes' first part, in Markdown: which file a person downloads, what the others are, the images."""
    want = names(version)
    rows = ["## Which file is for you", "", "| Who | File | Runs on |", "| --- | --- | --- |"]
    for key, _, who, where in FILES:
        if key in FOR_PEOPLE:
            rows.append(f"| {who} | `{want[key]}` | {where} |")
    # Linux and macOS servers have no file: the repository and the images are what they install.
    rows.append(f"| Server owners on Linux or macOS | No file: the [install guide]({REPO}/blob/v{version}/docs/install.md) "
                f"(one command, or Docker Compose) | Debian 12, Ubuntu 24.04, macOS, Docker |")
    rows += ["", "Read by programs, nothing to download by hand:", ""]
    described = [(key, who) for key, _, who, _ in FILES if key not in FOR_PEOPLE]
    for i, (key, who) in enumerate(described):
        # A file with no words of its own goes with the one before (the update feed and its package).
        if not who:
            continue
        files = [f"`{want[key]}`"] + [f"`{want[k]}`" for k, w in described[i + 1:i + 2] if not w]
        rows.append(f"- {' and '.join(files)}: {who}")
    rows += ["", f"Images on GHCR, tagged `{version}` and `latest`:", ""]
    for image, what, platforms in IMAGES:
        rows.append(f"- `{REGISTRY}/{image}`: {what}; {platforms}")
    rows.append(f"- The chart also as `oci://{REGISTRY}/charts/opendmtq`, version `{version}`")
    return "\n".join(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    lay = sub.add_parser("layout", help="the built files under the release's names, checked")
    lay.add_argument("version")
    lay.add_argument("out")
    lay.add_argument("--runtime", required=True, help="runtime.py --pack's zip")
    lay.add_argument("--client", required=True, help="client/packaging/windows/build.sh's OUT_DIR/releases")
    lay.add_argument("--windows", required=True, help="host/windows/build.sh's OpenDMTQ-windows.zip")
    lay.add_argument("--chart", required=True, help="helm package's .tgz")
    chk = sub.add_parser("check", help="what is wrong with a folder of release files")
    chk.add_argument("version")
    chk.add_argument("folder")
    nam = sub.add_parser("names", help="the release's file names")
    nam.add_argument("version")
    args = parser.parse_args(argv)
    if args.command == "names":
        print("\n".join(names(args.version).values()))
        return 0
    if args.command == "layout":
        problems = layout(args.version, args.out, args.runtime, args.client, args.windows, args.chart)
        folder = Path(args.out)
    else:
        problems = check(args.version, args.folder)
        folder = Path(args.folder)
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        # The list as it will be published, with each file's size, for the job's log.
        for name in names(args.version).values():
            print(f"{(folder / name).stat().st_size:>12,}  {name}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
