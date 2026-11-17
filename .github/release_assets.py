"""A release's files: one name for each, saying what it is, for which system and architecture, and which version.

    OPENDMTQ_SIGNING_KEY=<key file> python3 .github/release_assets.py layout VERSION OUT --runtime ZIP --client DIR \
        --windows ZIP --chart TGZ [--unsigned]
    python3 .github/release_assets.py check VERSION DIR [--unsigned]
    python3 .github/release_assets.py names VERSION

`layout` copies what the release job built under the release's names into OUT, writes the checksums of all of them,
signs the checksums with the project's key (the file OPENDMTQ_SIGNING_KEY names, which never enters the repository:
tools/opendmtq_tools/signing.py), and checks the result (`check`): exactly these files, each with the version in its
name, the programs for Windows built for x64, the PC client's update feed naming the packages beside it with their
sizes and hashes and the full package's files (FilesSHA256), the package's launcher taking no test's key, and the
checksums signed by a key the launchers and the servers take. Without a key it lays out nothing: --unsigned makes a
rehearsal, which no release publishes. `names` prints the names. The release notes' table of files (release_notes.py)
is made from the same list. The standard library only: it runs on the runner's own Python.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import sys
import tarfile
import zipfile
from pathlib import Path


def _signing():
    """The signing module of the server's tools (tools/opendmtq_tools/signing.py), loaded from its file alone: it needs
    nothing but the standard library, where the tools' package needs its own libraries."""
    path = Path(__file__).resolve().parent.parent / "tools" / "opendmtq_tools" / "signing.py"
    spec = importlib.util.spec_from_file_location("opendmtq_signing", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


signing = _signing()

# The repository on GitHub and its container registry, for the release notes.
REPO = "https://github.com/kanggu12/openDMTQ"
REGISTRY = "ghcr.io/kanggu12"

# The PC client's update feed: Velopack's name, which the installed launchers look for. Velopack's GitHub source (its
# sources/github.rs and sources/mod.rs, 1.2.161, the version 0.10.0's launchers carry) reads the asset
# releases.<channel>.json of each of the ten newest releases, channel "win", so that name stays as it is.
FEED = "releases.win.json"
# The update package, under a name of the release's own. The feed says it (FileName), and nothing else reads it: the
# GitHub source finds the asset of that name ignoring case, the download goes to the install folder's packages\ under
# it and is checked by its SHA-256 and size, Update.exe applies the file it is given and takes the program's id and
# version from the package's own manifest, and Velopack finds a package on the disk by *-full.nupkg and that manifest.
# The id inside stays OpenDMTQ.Client, the install folder's name (client/packaging/windows/build.sh's --packId).
PACKAGE = "opendmtq.client-{version}-full.nupkg"
# The package as vpk names it, from that id: what layout() takes and renames.
BUILT_PACKAGE = "OpenDMTQ.Client-{version}-full.nupkg"
# The delta package vpk makes from the previous release's full package (client/packaging/windows/build.sh keeps that
# beside the new one): what a launcher of that version downloads instead of the whole package.
BUILT_DELTA = "OpenDMTQ.Client-{version}-delta.nupkg"
# The field of the feed's full package that gives the SHA-256 of the files it holds (signing.files_sha256): Velopack
# reads the fields it knows and leaves this one, and a launcher checks a package put together from a delta by it.
FILES_FIELD = "FilesSHA256"
# Where a test build's public keys sit in the launcher, which a release's must not have (signing.TEST_KEYS_FILE).
TEST_KEYS_ENTRY = "opendmtq_client/update-test-keys.txt"
# The id the package's manifest must carry: an installed launcher takes another id's package for another program.
PACKAGE_ID = "OpenDMTQ.Client"

# Every file of a release: (key, name, who it is for, what it runs on), as docs/install.md describes them. A person
# downloads one of the first three; programs read the others. Every name in lower case.
FILES = (
    ("client", "opendmtq-pc-client-{version}-windows-x64-setup.exe", "Players on a PC: the PC client's installer",
     "Windows 10 and 11, x64; Linux with Wine"),
    ("server-windows", "opendmtq-server-{version}-windows-x64.zip", "Server owners on Windows: the whole server",
     "Windows 10 and 11, x64"),
    ("chart", "opendmtq-server-{version}-helm-chart.tgz", "Server owners on Kubernetes: the Helm chart",
     "Kubernetes, with the images below"),
    ("runtime", "opendmtq-phone-runtime-{version}-android-arm64-armv7.zip",
     "the server's app builder adds it to the phone app, for phones that run only 64-bit apps; a server fetches it "
     "itself, and one without internet takes it by hand", "Android"),
    ("feed", FEED, "installed PC clients update themselves from these", "Windows"),
    ("package", PACKAGE, "", "Windows"),
    ("delta", "opendmtq.client-{version}-delta.nupkg", "", "Windows"),
    ("sums", "opendmtq-{version}-sha256sums.txt", "the SHA-256 of every file here, and the project's signature over them",
     ""),
    ("sig", "opendmtq-{version}-sha256sums.txt.sig", "", ""),
)
# The ones a release may be without: the delta package, when there is no release before it to make it from.
OPTIONAL = ("delta",)
# The ones the checksums do not list: the checksums themselves, and their signature.
NOT_SUMMED = ("sums", "sig")

# The machine type in a Windows program's header for x64 (IMAGE_FILE_MACHINE_AMD64).
X64 = 0x8664


def names(version):
    """{key: file name} of the release `version`."""
    return {key: name.format(version=version) for key, name, _, _ in FILES}


def expected(version, delta):
    """{key: file name} of the files a release `version` has: all of them, the delta package only when it has one."""
    return {k: n for k, n in names(version).items() if delta or k not in OPTIONAL}


def manifest_of(path):
    """The text of a package's own manifest (its .nuspec at the top), or "" when it has none."""
    with zipfile.ZipFile(path) as z:
        nuspec = [n for n in z.namelist() if n.endswith(".nuspec") and "/" not in n]
        return z.read(nuspec[0]).decode("utf-8", "replace") if nuspec else ""


def test_keys_in(path):
    """The test keys a package's launcher takes besides the project's (its update-test-keys.txt), as text: "" for a
    release's, whose file is empty or absent."""
    with zipfile.ZipFile(path) as z:
        found = [n for n in z.namelist() if n.replace("\\", "/").endswith(TEST_KEYS_ENTRY)]
        return "".join(z.read(n).decode("ascii", "replace") for n in found).strip()


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


def feed_of(path):
    """The update feed's JSON, as vpk writes it (with a byte-order mark or without)."""
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def check(version, folder, signed=True):
    """What is wrong with the release's files in `folder`: a list of sentences, empty when nothing is. `signed` False
    for a rehearsal, whose checksums carry no signature (a signature that is there is checked all the same)."""
    folder = Path(folder)
    have = sorted(p.name for p in folder.iterdir())
    every = names(version)
    problems = []
    # The feed first: whether the release has a delta package is what the feed says.
    try:
        feed = feed_of(folder / every["feed"])
    except (OSError, ValueError) as e:
        return [f"{every['feed']} cannot be read ({e})"]
    assets = feed.get("Assets") or []
    ours = [a for a in assets if a.get("Version") == version]
    want = expected(version, any(a.get("Type") == "Delta" for a in ours))
    if not signed:
        # A rehearsal's checksums are not signed: the signature is no file it must have.
        want.pop("sig")
    # Exactly the release's files: nothing missing, and nothing a person would have to ask about.
    for name in sorted(set(want.values()) - set(have)):
        problems.append(f"{name} is missing")
    allowed = set(want.values()) | ({every["sig"]} if not signed else set())
    for name in sorted(set(have) - allowed):
        problems.append(f"{name} is not one of the release's files")
    # Every name in lower case: one way of writing them, whatever the version says.
    for name in have:
        if name != name.lower():
            problems.append(f"{name} is not all lower case")
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
    # The update feed: this version's full package and its delta package when it has one, each the file beside it at
    # its size and hash; any other entry is a full package of an earlier version (the one the delta is made from, in
    # its own release).
    packages = [("Full", want["package"])] + ([("Delta", want["delta"])] if "delta" in want else [])
    if [(a.get("PackageId"), a.get("Version"), a.get("Type"), a.get("FileName")) for a in ours] != \
            [(PACKAGE_ID, version, kind, name) for kind, name in packages]:
        problems.append(f"{want['feed']} does not name {' and '.join(n for _, n in packages)} alone for {version}: {ours}")
        return problems
    for asset in ours:
        path = folder / asset["FileName"]
        if asset.get("Size") != path.stat().st_size or str(asset.get("SHA256", "")).lower() != sha256(path):
            problems.append(f"{want['feed']} gives {asset['FileName']} another size or hash")
    for asset in assets:
        if asset not in ours and (asset.get("Type") != "Full" or asset.get("PackageId") != PACKAGE_ID
                                  or version_key(str(asset.get("Version"))) >= version_key(version)):
            problems.append(f"{want['feed']} names {asset.get('FileName')}, which is no earlier full package")
    # The full package's files, by which a launcher checks one put together from the delta package.
    if str(ours[0].get(FILES_FIELD, "")).lower() != signing.files_sha256(folder / want["package"]):
        problems.append(f"{want['feed']} does not give the files of {want['package']} ({FILES_FIELD})")
    # Each package's own manifest: the program's id, this version and Windows on x64, whatever the file is called.
    for _, name in packages:
        manifest = manifest_of(folder / name)
        for line in (f"<id>{PACKAGE_ID}</id>", f"<version>{version}</version>", "<rid>win-x64</rid>"):
            if line not in manifest:
                problems.append(f"{name}'s manifest has no {line}")
    # A launcher built for a test takes that test's own key: a release's takes the project's alone.
    if test_keys_in(folder / want["package"]):
        problems.append(f"{want['package']}'s launcher takes a test's key: it is a test build, not a release")
    # The checksums: every other file, as sha256sum writes them.
    sums = (folder / want["sums"]).read_text(encoding="utf-8").splitlines()
    summed = [f"{sha256(folder / n)}  {n}" for k, n in want.items() if k not in NOT_SUMMED]
    if sums != summed:
        problems.append(f"{want['sums']} is not the checksums of the other files")
    # And their signature, by a key the launchers and the servers take (signing.KEYS).
    sig = folder / every["sig"]
    if sig.exists():
        data, signature = (folder / want["sums"]).read_bytes(), sig.read_bytes()
        if signing.signed_by(data, signature) is None:
            problems.append(f"{every['sig']} is not the OpenDMTQ project's signature of {want['sums']}")
    return problems


def version_key(version):
    """A version as numbers to compare (1.2.3 -> (1, 2, 3)); a part that is no number counts as 0."""
    return tuple(int(p) if p.isdigit() else 0 for p in version.split("-")[0].split("."))


def signing_key():
    """The file of the project's signing key, as OPENDMTQ_SIGNING_KEY names it (nowhere else: no path is tried by
    itself), or None when it names none. A name that is not a file stops the layout: a mistake, never a quiet release
    without its signature."""
    key = os.environ.get("OPENDMTQ_SIGNING_KEY", "").strip()
    if not key:
        return None
    if not os.path.isfile(key):
        raise SystemExit(f"no signing key at {key} (OPENDMTQ_SIGNING_KEY)")
    return key


def layout(version, out, runtime, client, windows, chart, signed=True):
    """The built files under the release's names in `out` (emptied first), with their checksums, signed with the key
    OPENDMTQ_SIGNING_KEY names; then check(). `signed` False lays out a rehearsal without a signature; True without a
    key stops before anything is laid out."""
    key = signing_key()
    if signed and key is None:
        raise SystemExit("the release's files are not signed: OPENDMTQ_SIGNING_KEY names no key here (a release is "
                         "laid out and published on the machine that holds the key; --unsigned lays out a rehearsal)")
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    client = Path(client)
    built, built_delta = BUILT_PACKAGE.format(version=version), BUILT_DELTA.format(version=version)
    # The delta package is there when the build had the previous release's full package beside the new one.
    want = expected(version, (client / built_delta).is_file())
    # From each build's own output: the installer and Velopack's feed and packages (client/packaging/windows/build.sh's
    # releases folder), the Windows server bundle (host/windows/build.sh), the chart (helm package), the runtime.
    sources = {
        "client": client / "OpenDMTQ-Setup.exe",
        "server-windows": Path(windows),
        "chart": Path(chart),
        "runtime": Path(runtime),
        "package": client / built,
        "delta": client / built_delta,
    }
    for key_name, source in sources.items():
        if key_name in want:
            shutil.copyfile(source, out / want[key_name])
    # The feed as vpk wrote it, naming this version's packages by the release's names instead (the same bytes, size
    # and hashes), and giving the full package's files.
    raw = (client / FEED).read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    feed = json.loads(raw.decode("utf-8-sig"))
    renamed = {built.lower(): want["package"], built_delta.lower(): want.get("delta")}
    for asset in feed.get("Assets") or []:
        name = renamed.get(str(asset.get("FileName", "")).lower())
        if name:
            asset["FileName"] = name
        if asset.get("FileName") == want["package"]:
            asset[FILES_FIELD] = signing.files_sha256(out / want["package"])
    # Written as vpk writes it: compact, and with the byte-order mark when vpk's had one.
    text = json.dumps(feed, separators=(",", ":"))
    (out / want["feed"]).write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    # One file of checksums for all, in the order the notes list the files.
    lines = [f"{sha256(out / want[k])}  {want[k]}" for k in want if k not in NOT_SUMMED]
    (out / want["sums"]).write_text("\n".join(lines) + "\n", encoding="utf-8")
    if key is not None:
        # The signature beside them: what every launcher and server checks before it uses a file of the release.
        signer = signing.sign_file(key, str(out / want["sums"]))
        if signer not in signing.KEYS:
            # A key no launcher takes signs nothing worth publishing: the signature goes again.
            (out / want["sig"]).unlink()
            raise SystemExit(f"the key in {key} is not the project's (its public key {signer} is not in signing.KEYS)")
    return check(version, out, signed=key is not None)


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
    lay.add_argument("--unsigned", action="store_true", help="a rehearsal: no key, no signature, nothing to publish")
    chk = sub.add_parser("check", help="what is wrong with a folder of release files")
    chk.add_argument("version")
    chk.add_argument("folder")
    chk.add_argument("--unsigned", action="store_true", help="a rehearsal's folder, whose checksums carry no signature")
    nam = sub.add_parser("names", help="the release's file names")
    nam.add_argument("version")
    args = parser.parse_args(argv)
    if args.command == "names":
        print("\n".join(names(args.version).values()))
        return 0
    if args.command == "layout":
        problems = layout(args.version, args.out, args.runtime, args.client, args.windows, args.chart,
                          signed=not args.unsigned)
        folder = Path(args.out)
    else:
        problems = check(args.version, args.folder, signed=not args.unsigned)
        folder = Path(args.folder)
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        # The list as it will be published, with each file's size, for the job's log: the files there are, a release
        # without a delta package or a rehearsal without a signature having fewer.
        for name in names(args.version).values():
            if (folder / name).exists():
                print(f"{(folder / name).stat().st_size:>12,}  {name}")
        if not (folder / names(args.version)["sig"]).exists():
            print("NOT SIGNED: a rehearsal, which no release publishes")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
