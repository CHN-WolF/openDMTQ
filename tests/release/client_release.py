"""A made-up release's PC client files for the update tests under Wine (tests/release/update_signed.sh), laid out as
.github/release_assets.py lays out a release's and signed with a test's own key, never the project's.

    python3 tests/release/client_release.py VERSION RELEASES_DIR OUT KEY_FILE

RELEASES_DIR is the releases folder vpk packed VERSION into (client/packaging/windows/build.sh's OUT_DIR/releases, or the
test's own): its full package, the delta package when vpk made one, its feed, and OpenDMTQ-Setup.exe when the build made
it. OUT gets them under the release's names, the feed naming them so and giving the full package's files (FilesSHA256),
the checksums of all of them, and the checksums' signature with the key in KEY_FILE (64 hex digits, as signing.py
new-key writes it). The standard library only, with the repository's own modules.
"""
import importlib.util
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load(name, path):
    """A module of the repository from its file (the release script is in no package)."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


assets = load("release_assets", os.path.join(".github", "release_assets.py"))
signing = assets.signing


def main(argv):
    version, releases, out, key = argv
    names = assets.names(version)
    os.makedirs(out, exist_ok=True)
    built = {"package": assets.BUILT_PACKAGE.format(version=version), "delta": assets.BUILT_DELTA.format(version=version),
             "client": "OpenDMTQ-Setup.exe"}
    laid = []
    for kind, name in built.items():
        source = os.path.join(releases, name)
        if os.path.isfile(source):
            shutil.copyfile(source, os.path.join(out, names[kind]))
            laid.append(names[kind])
    # The feed as vpk wrote it, naming this version's packages by the release's names, with the full package's files.
    with open(os.path.join(releases, assets.FEED), "rb") as f:
        raw = f.read()
    feed = json.loads(raw.decode("utf-8-sig"))
    renamed = {built["package"].lower(): names["package"], built["delta"].lower(): names["delta"]}
    for asset in feed.get("Assets") or []:
        asset["FileName"] = renamed.get(str(asset.get("FileName", "")).lower(), asset.get("FileName"))
        if asset["FileName"] == names["package"]:
            asset[assets.FILES_FIELD] = signing.files_sha256(os.path.join(out, names["package"]))
    with open(os.path.join(out, assets.FEED), "wb") as f:
        f.write((b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b"") + json.dumps(feed, separators=(",", ":")).encode())
    laid.append(assets.FEED)
    # The checksums of all of them, and their signature with the test's key.
    sums = os.path.join(out, names["sums"])
    with open(sums, "w", encoding="utf-8") as f:
        f.write("".join("%s  %s\n" % (assets.sha256(os.path.join(out, n)), n) for n in laid))
    public = signing.sign_file(key, sums)
    print("%s: %s, signed with the test's key %s" % (version, ", ".join(sorted(laid)), public))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
