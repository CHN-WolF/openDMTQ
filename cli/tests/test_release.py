"""A release's files (.github/release_assets.py): their names, the check before anything is published, the notes' table
of which file is for whom, and every program and guide that names them."""

import hashlib
import importlib.util
import io
import json
import os
import re
import struct
import sys
import tarfile
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# The version the made-up release carries.
V = "1.2.3"


def load(name):
    """A script of .github/ (outside any package) as a module."""
    sys.path.insert(0, os.path.join(ROOT, ".github"))
    try:
        spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, ".github", name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(os.path.join(ROOT, ".github"))


assets = load("release_assets")


def read(*path):
    with open(os.path.join(ROOT, *path), encoding="utf-8") as f:
        return f.read()


def program(machine=assets.X64):
    """The first bytes of a Windows program for `machine` (x64 unless said), as its header has them."""
    head = bytearray(b"MZ" + bytes(0x3E))
    # The PE header right after the DOS header: its place at 0x3C, then "PE\0\0" and the machine type.
    struct.pack_into("<I", head, 0x3C, 0x40)
    return bytes(head) + b"PE\0\0" + struct.pack("<H", machine) + bytes(64)


def made_release(folder, version=V, machine=assets.X64):
    """A release's files as the release job lays them out, small: each with what check() reads of it."""
    names = assets.names(version)
    path = {k: os.path.join(folder, n) for k, n in names.items()}
    with open(path["client"], "wb") as f:
        f.write(program(machine))
    with zipfile.ZipFile(path["server-windows"], "w") as z:
        z.writestr("OpenDMTQ/OpenDMTQ.exe", program(machine))
        z.writestr("OpenDMTQ/runtime/python/python.exe", program(machine))
        z.writestr("OpenDMTQ/app/VERSION", version + "\n")
    with tarfile.open(path["chart"], "w:gz") as t:
        chart = f'apiVersion: v2\nname: opendmtq\nversion: {version}\nappVersion: "{version}"\n'.encode()
        info = tarfile.TarInfo("opendmtq/Chart.yaml")
        info.size = len(chart)
        t.addfile(info, io.BytesIO(chart))
    with zipfile.ZipFile(path["runtime"], "w") as z:
        for member in ("bundle.json", "arm64-v8a/libarm32.so", "armeabi-v7a/libopendmtq.so"):
            z.writestr(member, member)
    # The package: a zip with its manifest at the top, as vpk makes it.
    with zipfile.ZipFile(path["package"], "w") as z:
        z.writestr("OpenDMTQ.Client.nuspec", f"<package><metadata><id>OpenDMTQ.Client</id><version>{version}</version>"
                                             "<rid>win-x64</rid></metadata></package>")
        z.writestr("lib/app/OpenDMTQ.exe", program())
    feed = {"Assets": [{"PackageId": "OpenDMTQ.Client", "Version": version, "Type": "Full", "FileName": names["package"],
                        "SHA256": assets.sha256(path["package"]).upper(), "Size": os.path.getsize(path["package"])}]}
    # vpk writes its feed with a byte-order mark: read as it comes.
    with open(path["feed"], "w", encoding="utf-8-sig") as f:
        json.dump(feed, f)
    with open(path["sums"], "w", encoding="utf-8") as f:
        f.write("".join(f"{assets.sha256(path[k])}  {n}\n" for k, n in names.items() if k != "sums"))
    return path


class NamesTest(unittest.TestCase):
    """DEP-50: one scheme, saying what each file is, for which system and architecture, and which version, all in lower
    case."""

    def test_each_name_says_its_version_and_what_it_runs_on(self):
        names = assets.names(V)
        self.assertEqual(names["client"], "opendmtq-pc-client-1.2.3-windows-x64-setup.exe")
        self.assertEqual(names["server-windows"], "opendmtq-server-1.2.3-windows-x64.zip")
        self.assertEqual(names["chart"], "opendmtq-server-1.2.3-helm-chart.tgz")
        self.assertEqual(names["runtime"], "opendmtq-phone-runtime-1.2.3-android-arm64-armv7.zip")
        self.assertEqual(names["package"], "opendmtq.client-1.2.3-full.nupkg")
        self.assertEqual(names["sums"], "opendmtq-1.2.3-sha256sums.txt")
        for key, name in names.items():
            # One way of writing them: no capital letter anywhere.
            self.assertEqual(name, name.lower(), key)
            # The feed's name is Velopack's, fixed by the launchers already installed; every other has the version.
            if key != "feed":
                self.assertIn(V, name, key)
        # Seven files: what the last release had and nobody needs (the player alone, the bundle's own .sha256, the
        # installer's .version, Velopack's RELEASES and assets.win.json) is gone.
        self.assertEqual(len(names), 7)

    def test_the_update_feed_keeps_the_name_installed_launchers_look_for(self):
        # Velopack's GitHub source reads releases.<channel>.json, channel win, and the package its FileName gives, under
        # any name; the package id inside is the install folder's name (client/opendmtq_client/installed.py).
        self.assertEqual(assets.names(V)["feed"], "releases.win.json")
        self.assertEqual(assets.PACKAGE_ID, "OpenDMTQ.Client")
        self.assertEqual(assets.BUILT_PACKAGE.format(version=V), "OpenDMTQ.Client-1.2.3-full.nupkg")
        # The launcher's repair finds the installed package in any case: the installer's as the id is written, an
        # update's as the release names it.
        self.assertIn("n.lower() == want", read("client", "opendmtq_client", "repair.py"))
        build = read("client", "packaging", "windows", "build.sh")
        self.assertIn("--packId OpenDMTQ.Client ", build)
        self.assertNotIn("--channel", build)
        self.assertIn('rm -f "$OUT/releases/RELEASES" "$OUT/releases/assets.win.json"', build)
        self.assertIn('PACKAGE_ID = "OpenDMTQ.Client"', read("client", "opendmtq_client", "installed.py"))
        self.assertIn("velopack.GithubSource(source, None, False)", read("client", "opendmtq_client", "updates.py"))

    def test_the_servers_fetch_and_take_them_by_the_same_names(self):
        names = assets.names("{version}")
        self.assertIn(f'RELEASE_NAME = "{names["runtime"]}"', read("tools", "opendmtq_tools", "runtime.py"))
        self.assertIn(f'RELEASE_NAME = "{names["client"]}"', read("tools", "opendmtq_tools", "windows_client.py"))
        install = read("host", "install.sh")
        self.assertIn("'" + names["runtime"].format(version="*") + "'", install)
        self.assertIn("'" + names["client"].format(version="*") + "'", install)

    def test_the_guides_name_the_files_as_a_release_has_them(self):
        guides = ["README.md", "docs/install.md", "docs/windows-player.md", "docs/closed-network.md", "CONTRIBUTING.md",
                  "docs/admin.md", "docs/faq.md", "host/windows/README.txt"]
        text = {g: read(*g.split("/")) for g in guides}
        # The old names a person could look for in a release and not find.
        for old in ("OpenDMTQ-windows.zip", "opendmtq-player-windows.zip", "OpenDMTQ-Setup.exe.version`",
                    "`opendmtq-arm32-runtime.zip`", "RELEASES`", "assets.win.json", "releases/latest/download/"):
            for guide, body in text.items():
                self.assertNotIn(old, body, f"{guide} names {old}")
        # The release's names of 0.11.0's first builds, in capitals, which no release has.
        for old in ("OpenDMTQ-PC-Client", "OpenDMTQ-Server-", "OpenDMTQ-Phone-", "SHA256SUMS", "OpenDMTQ.Client-<",
                    "OpenDMTQ.Client-1"):
            for guide, body in text.items():
                self.assertNotIn(old, body, f"{guide} names {old}")
        # The quick start downloads the server for Windows by the latest release's number, which its name carries.
        for guide in ("README.md", "docs/install.md"):
            self.assertIn('opendmtq-server-$v-windows-x64.zip"', text[guide])
            self.assertIn("-replace '.*/v'", text[guide])
        self.assertIn("opendmtq-pc-client-<version>-windows-x64-setup.exe", text["docs/windows-player.md"])
        self.assertIn("opendmtq-<version>-sha256sums.txt", text["docs/install.md"])


class CheckTest(unittest.TestCase):
    """DEP-51: the check before anything is published finds what a person or a program would trip over."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = self._tmp.name

    def test_a_whole_release_passes(self):
        made_release(self.folder)
        self.assertEqual(assets.check(V, self.folder), [])

    def test_a_missing_file_and_one_more_are_said(self):
        path = made_release(self.folder)
        os.remove(path["runtime"])
        open(os.path.join(self.folder, "RELEASES"), "w").close()
        problems = assets.check(V, self.folder)
        self.assertIn("opendmtq-phone-runtime-1.2.3-android-arm64-armv7.zip is missing", problems)
        self.assertIn("RELEASES is not one of the release's files", problems)

    def test_programs_for_another_machine_are_said(self):
        # 32-bit x86 (IMAGE_FILE_MACHINE_I386): a name that says x64 must hold x64.
        made_release(self.folder, machine=0x14C)
        problems = assets.check(V, self.folder)
        self.assertTrue(any("setup.exe is not a Windows program for x64" in p for p in problems), problems)
        self.assertTrue(any("OpenDMTQ/OpenDMTQ.exe is not a Windows program for x64" in p for p in problems), problems)

    def test_another_version_inside_is_said(self):
        made_release(self.folder, version="1.2.2")
        # Named for 1.2.2 throughout: under 1.2.3 every name is wrong.
        self.assertTrue(assets.check(V, self.folder))
        for name in os.listdir(self.folder):
            os.rename(os.path.join(self.folder, name), os.path.join(self.folder, name.replace("1.2.2", V)))
        problems = assets.check(V, self.folder)
        self.assertTrue(any("says version 1.2.2" in p for p in problems), problems)
        self.assertTrue(any("Chart.yaml has no 'version: 1.2.3'" in p for p in problems), problems)

    def test_a_feed_that_does_not_name_the_package_beside_it_is_said(self):
        path = made_release(self.folder)
        with open(path["package"], "ab") as f:
            f.write(b" changed after the feed was written")
        problems = assets.check(V, self.folder)
        self.assertIn("releases.win.json gives opendmtq.client-1.2.3-full.nupkg another size or hash", problems)

    def test_a_name_with_a_capital_letter_is_said(self):
        path = made_release(self.folder)
        # The same file under the name as vpk writes it: one too many, and not in lower case.
        os.rename(path["package"], os.path.join(self.folder, "OpenDMTQ.Client-1.2.3-full.nupkg"))
        problems = assets.check(V, self.folder)
        self.assertIn("opendmtq.client-1.2.3-full.nupkg is missing", problems)
        self.assertIn("OpenDMTQ.Client-1.2.3-full.nupkg is not all lower case", problems)

    def test_a_package_of_another_program_or_machine_is_said(self):
        path = made_release(self.folder)
        with zipfile.ZipFile(path["package"], "w") as z:
            z.writestr("Other.App.nuspec", "<package><metadata><id>Other.App</id><version>1.2.3</version>"
                                           "<rid>win-arm64</rid></metadata></package>")
        problems = assets.check(V, self.folder)
        self.assertIn("opendmtq.client-1.2.3-full.nupkg's manifest has no <id>OpenDMTQ.Client</id>", problems)
        self.assertIn("opendmtq.client-1.2.3-full.nupkg's manifest has no <rid>win-x64</rid>", problems)

    def test_layout_names_the_built_files_and_checks_them(self):
        # The builds' own outputs, under the names they are built with: the installer as PyInstaller makes it, the
        # package and the feed as vpk writes them (the package named after the program's id, the feed naming it so).
        built = os.path.join(self.folder, "built")
        client = os.path.join(built, "client")
        os.makedirs(client)
        path = made_release(built)
        os.rename(path["client"], os.path.join(client, "OpenDMTQ-Setup.exe"))
        os.rename(path["package"], os.path.join(client, "OpenDMTQ.Client-1.2.3-full.nupkg"))
        with open(path["feed"], encoding="utf-8-sig") as f:
            feed = json.load(f)
        feed["Assets"][0]["FileName"] = "OpenDMTQ.Client-1.2.3-full.nupkg"
        with open(os.path.join(client, "releases.win.json"), "w", encoding="utf-8") as f:
            json.dump(feed, f)
        # What vpk also writes, which the release leaves out.
        open(os.path.join(client, "RELEASES"), "w").close()
        out = os.path.join(self.folder, "release")
        self.assertEqual(assets.layout(V, out, path["runtime"], client, path["server-windows"], path["chart"]), [])
        self.assertEqual(sorted(os.listdir(out)), sorted(assets.names(V).values()))
        # The feed names the package by the release's name, with the same hashes and size: the bytes did not change.
        with open(os.path.join(out, "releases.win.json"), encoding="utf-8") as f:
            laid = json.load(f)["Assets"][0]
        self.assertEqual(laid["FileName"], "opendmtq.client-1.2.3-full.nupkg")
        self.assertEqual({k: v for k, v in laid.items() if k != "FileName"},
                         {k: v for k, v in feed["Assets"][0].items() if k != "FileName"})


class NotesTest(unittest.TestCase):
    """DEP-52: the release notes open with which file is for whom, then the images and their platforms."""

    def test_the_head_says_who_downloads_what_and_what_programs_read(self):
        head = assets.notes_head(V)
        lines = head.splitlines()
        self.assertEqual(lines[0], "## Which file is for you")
        # Every file is in it, by its name.
        for name in assets.names(V).values():
            self.assertIn(f"`{name}`", head)
        # A person finds their row by who they are, before any file a program reads.
        table = [line for line in lines if line.startswith("| ")][2:]
        self.assertEqual([row.split("|")[1].strip().split(":")[0] for row in table],
                         ["Players on a PC", "Server owners on Windows", "Server owners on Kubernetes",
                          "Server owners on Linux or macOS"])
        self.assertIn("No file: the [install guide](https://github.com/kanggu12/openDMTQ/blob/v1.2.3/docs/install.md)", head)
        self.assertLess(head.index("Players on a PC"), head.index("Read by programs"))
        self.assertLess(head.index("Read by programs"), head.index("`releases.win.json`"))

    def test_the_images_platforms_are_the_ones_release_yml_builds(self):
        head = assets.notes_head(V)
        workflow = read(".github", "workflows", "release.yml")
        for image, _, platforms in assets.IMAGES:
            # The platforms the workflow's build step of that image names, as the notes write them.
            step = re.search(rf"context: (\w+)\n\s+platforms: ([\w/,]+)\n(?:.*\n){{0,4}}.*/{image}:", workflow)
            self.assertIsNotNone(step, image)
            self.assertEqual(platforms.split(" (")[0], " and ".join(step.group(2).split(",")), image)
            self.assertIn(f"`ghcr.io/kanggu12/{image}`", head)

    def test_release_notes_print_the_head_then_the_changelog(self):
        notes = load("release_notes")
        chart, _ = notes.chart_versions(notes.ROOT)
        out = io.StringIO()
        from contextlib import redirect_stdout
        with redirect_stdout(out):
            self.assertEqual(notes.main(["v" + chart, "--root", ROOT]), 0)
        text = out.getvalue()
        self.assertTrue(text.startswith("## Which file is for you\n"))
        self.assertIn(f"\n## What changed in {chart}\n", text)
        self.assertLess(text.index("Which file"), text.index("What changed"))


class WorkflowTest(unittest.TestCase):
    """DEP-53: release.yml lays the files out and checks them before it pushes anything, and publishes those alone."""

    def test_the_files_are_checked_before_the_first_push_and_published_alone(self):
        workflow = read(".github", "workflows", "release.yml")
        layout = workflow.index("python3 .github/release_assets.py layout")
        self.assertLess(layout, workflow.index("push: true"))
        self.assertLess(layout, workflow.index("helm push"))
        self.assertIn('gh release create "$GITHUB_REF_NAME" dist/release/* \\', workflow)
        # Nothing else on the release: the old names are not handed to gh any more.
        release = workflow[workflow.index("gh release create"):]
        for old in ("opendmtq-player-windows.zip", "OpenDMTQ-windows.zip.sha256", "dist/client/*"):
            self.assertNotIn(old, release)

    def test_the_rehearsal_names_the_same_steps(self):
        # The update proof under Wine (tests/release/update.sh) reads both sides as release_assets.py lays them out.
        script = read("tests", "release", "update.sh")
        self.assertIn("releases.win.json", script)
        self.assertIn("GithubSource(", script)
        stub = read("tests", "release", "github_stub.py")
        self.assertIn("/api/v3/repos/", stub)


if __name__ == "__main__":
    unittest.main()
