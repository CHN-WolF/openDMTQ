"""The PC client's updates a server hands out to its launchers (client_updates.py): those of the installer's version,
from beside the code, from data/apk or from the release, each file checked against the release's signed checksums before
the site hands it out at /updates/, what is refused said and the files handed out before kept, a failed fetch tried again
a day later. The releases are made up and signed with a key made for these tests, which the signing module takes in place
of the project's while they run."""

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
import urllib.error
from unittest import mock

from opendmtq_tools import builder, client_updates, signing, windows_client

TEST_SEED = bytes(range(32))
TEST_KEY = signing.public_key(TEST_SEED).hex()


def release_files(version, base=None, seed=TEST_SEED):
    """{name: bytes} of a release's update files as .github/release_assets.py lays them out: the feed (naming the full
    package, the delta package from `base` and that full package), the packages, the checksums and their signature."""
    full = b"PK full package of " + version.encode()
    files = {f"opendmtq.client-{version}-full.nupkg": full}
    assets = [{"PackageId": "OpenDMTQ.Client", "Version": version, "Type": "Full",
               "FileName": f"opendmtq.client-{version}-full.nupkg", "SHA256": hashlib.sha256(full).hexdigest(),
               "Size": len(full)}]
    if base:
        delta = b"PK delta package of " + version.encode()
        files[f"opendmtq.client-{version}-delta.nupkg"] = delta
        assets.append({"PackageId": "OpenDMTQ.Client", "Version": version, "Type": "Delta",
                       "FileName": f"opendmtq.client-{version}-delta.nupkg", "SHA256": hashlib.sha256(delta).hexdigest(),
                       "Size": len(delta)})
        assets.append({"PackageId": "OpenDMTQ.Client", "Version": base, "Type": "Full",
                       "FileName": f"opendmtq.client-{base}-full.nupkg", "SHA256": "ab" * 32, "Size": 10})
    files["releases.win.json"] = b"\xef\xbb\xbf" + json.dumps({"Assets": assets}).encode()
    # The release's other files, which a server's update folder has no use for: in the checksums all the same.
    sums = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in files.items())
    sums += f"{'0' * 64}  opendmtq-pc-client-{version}-windows-x64-setup.exe\n"
    files[signing.sums_name(version)] = sums.encode()
    files[signing.sums_name(version) + ".sig"] = signing.sign(seed, sums.encode())
    return files


def put(folder, files):
    """The files into `folder`."""
    os.makedirs(folder, exist_ok=True)
    for name, data in files.items():
        with open(os.path.join(folder, name), "wb") as f:
            f.write(data)


class Place(unittest.TestCase):
    """data/apk with its out folder, the code's folder with nothing beside the code, the installer of 0.11.1 kept for the
    site (windows.json), no way out to the internet unless a test opens one, the test's key taken."""

    version = "0.11.1"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.apk = tmp.name
        self.out = os.path.join(self.apk, "out")
        self.code = os.path.join(self.apk, "code")
        os.makedirs(self.out)
        os.makedirs(self.code)
        with open(os.path.join(self.out, windows_client.MANIFEST), "w", encoding="utf-8") as f:
            json.dump({"file": windows_client.SETUP_NAME, "size": 1, "sha256": "0", "version": self.version}, f)
        self.asked = []
        self.served = {}
        for patch in (mock.patch.object(client_updates, "HERE", self.code),
                      mock.patch.object(client_updates.urllib.request, "urlopen", self.urlopen),
                      mock.patch.object(signing, "KEYS", (TEST_KEY,)),
                      contextlib.redirect_stdout(io.StringIO())):
            patch.__enter__()
            self.addCleanup(patch.__exit__, None, None, None)

    def urlopen(self, url, timeout=None):
        """The release's files by their names under its tag (self.served), 404 for any other; no way out without any."""
        self.asked.append(url.rsplit("/", 1)[1])
        if not self.served:
            raise urllib.error.URLError("no way out")
        found = self.served.get(url.rsplit("/", 1)[1])
        if found is None or f"/download/v{self.version}/" not in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return io.BytesIO(found)

    def handed_out(self):
        """The files the site hands out (data/apk/out/updates), by name, and updates.json."""
        folder = os.path.join(self.out, client_updates.FOLDER)
        names = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
        return names, client_updates.kept(self.out)


class Sources(Place):
    """DEP-65: the installer's version's updates, from beside the code, from data/apk or from the release, checked."""

    def test_beside_the_code_first(self):
        put(os.path.join(self.code, client_updates.KIT), release_files(self.version, base="0.11.0"))
        about = client_updates.keep(self.out)
        names, kept = self.handed_out()
        self.assertEqual(names, sorted(["releases.win.json", "opendmtq.client-0.11.1-full.nupkg",
                                        "opendmtq.client-0.11.1-delta.nupkg", "opendmtq-0.11.1-sha256sums.txt",
                                        "opendmtq-0.11.1-sha256sums.txt.sig"]))
        self.assertEqual((about["version"], about["source"], about["delta_from"], about["signed_by"]),
                         ("0.11.1", "beside the code", "0.11.0", TEST_KEY))
        self.assertEqual(kept["files"], about["files"])
        self.assertEqual(self.asked, [])
        # Readable by the site, which may run as another user than the builder.
        self.assertEqual(os.stat(os.path.join(self.out, client_updates.FOLDER)).st_mode & 0o777, 0o755)

    def test_a_kit_in_data_apk_is_taken_and_goes(self):
        put(os.path.join(self.apk, client_updates.KIT), release_files(self.version))
        about = client_updates.keep(self.out)
        self.assertEqual((about["source"], about["delta"]), ("data/apk", None))
        self.assertFalse(os.path.exists(os.path.join(self.apk, client_updates.KIT)))
        self.assertEqual(self.asked, [])

    def test_otherwise_the_release_its_checksums_first(self):
        self.served = release_files(self.version, base="0.11.0")
        about = client_updates.keep(self.out)
        self.assertEqual(about["source"], "the release")
        # The checksums and their signature, then the feed, then the packages it names.
        self.assertEqual(self.asked, ["opendmtq-0.11.1-sha256sums.txt", "opendmtq-0.11.1-sha256sums.txt.sig",
                                      "releases.win.json", "opendmtq.client-0.11.1-full.nupkg",
                                      "opendmtq.client-0.11.1-delta.nupkg"])
        self.assertEqual(len(self.handed_out()[0]), 5)
        # Up to date: nothing is asked again.
        self.asked.clear()
        self.assertEqual(client_updates.keep(self.out)["version"], "0.11.1")
        self.assertEqual(self.asked, [])

    def test_they_follow_the_installers_version(self):
        put(os.path.join(self.code, client_updates.KIT), release_files("0.11.2"))
        # Beside the code are 0.11.2's, the installer is 0.11.1: those of 0.11.1 or none.
        self.assertIsNone(client_updates.keep(self.out))
        self.assertEqual(self.handed_out()[0], [])
        # Without an installer's version (one put there by hand, without its version): none.
        with open(os.path.join(self.out, windows_client.MANIFEST), "w", encoding="utf-8") as f:
            json.dump({"file": windows_client.SETUP_NAME, "size": 1, "sha256": "0", "version": ""}, f)
        self.assertIsNone(client_updates.keep(self.out))

    def test_the_builder_keeps_them_after_the_installer(self):
        calls = []
        with mock.patch.object(builder, "OUT", self.out), \
                mock.patch.object(builder.windows_client, "keep", lambda out: calls.append("installer") or "x"), \
                mock.patch.object(builder.client_updates, "keep", lambda out: calls.append("updates")):
            builder.windows_installer()
        self.assertEqual(calls, ["installer", "updates"])
        # Their failure stops nothing.
        with mock.patch.object(builder, "OUT", self.out), mock.patch.object(builder.windows_client, "keep", lambda out: None), \
                mock.patch.object(builder.client_updates, "keep", side_effect=OSError("disk full")):
            builder.windows_installer()


class Refusals(Place):
    """DEP-66: what does not check out against the release's signed checksums is refused, said, and the files handed out
    before stay; a fetch that failed is tried again a day later."""

    def handed_out_before(self):
        """0.11.0's updates handed out already (the installer of 0.11.0 kept before)."""
        self.version = "0.11.0"
        put(os.path.join(self.code, client_updates.KIT), release_files("0.11.0"))
        with open(os.path.join(self.out, windows_client.MANIFEST), "w", encoding="utf-8") as f:
            json.dump({"file": windows_client.SETUP_NAME, "size": 1, "sha256": "0", "version": "0.11.0"}, f)
        client_updates.keep(self.out)
        os.remove(os.path.join(self.code, client_updates.KIT, "releases.win.json"))
        self.version = "0.11.1"
        with open(os.path.join(self.out, windows_client.MANIFEST), "w", encoding="utf-8") as f:
            json.dump({"file": windows_client.SETUP_NAME, "size": 1, "sha256": "0", "version": "0.11.1"}, f)

    def test_a_package_that_is_not_the_file_the_release_signed(self):
        self.handed_out_before()
        files = release_files(self.version)
        files["opendmtq.client-0.11.1-full.nupkg"] = b"PK another package of 0.11.1"
        put(os.path.join(self.apk, client_updates.KIT), files)
        self.assertEqual(client_updates.keep(self.out)["version"], "0.11.0")
        self.assertEqual(client_updates.failure(self.apk), "opendmtq.client-0.11.1-full.nupkg is not the file the release signed")
        # Left where it was put, for whoever put it there to see.
        self.assertTrue(os.path.isdir(os.path.join(self.apk, client_updates.KIT)))

    def test_checksums_signed_by_another_key_or_not_at_all(self):
        self.served = release_files(self.version, seed=bytes(32))
        self.assertIsNone(client_updates.keep(self.out))
        self.assertEqual(client_updates.failure(self.apk), "opendmtq-0.11.1-sha256sums.txt is not signed by the OpenDMTQ project")
        # The packages were never asked for.
        self.assertNotIn("opendmtq.client-0.11.1-full.nupkg", self.asked)
        self.assertEqual(self.handed_out()[0], [])

    def test_a_feed_that_is_not_the_one_the_checksums_sum(self):
        files = release_files(self.version)
        files["releases.win.json"] = files["releases.win.json"].replace(b'"Size"', b'"size"')
        put(os.path.join(self.apk, client_updates.KIT), files)
        self.assertIsNone(client_updates.keep(self.out))
        self.assertEqual(client_updates.failure(self.apk), "releases.win.json is not the file the release signed")

    def test_a_feed_naming_its_packages_otherwise_is_refused(self):
        files = release_files(self.version)
        feed = json.loads(files["releases.win.json"].decode("utf-8-sig"))
        feed["Assets"][0]["FileName"] = "../../Update.exe"
        files["releases.win.json"] = json.dumps(feed).encode()
        sums = files[signing.sums_name(self.version)].decode().splitlines()
        sums = [line for line in sums if not line.endswith("releases.win.json")]
        sums.append(f"{hashlib.sha256(files['releases.win.json']).hexdigest()}  releases.win.json")
        files[signing.sums_name(self.version)] = ("\n".join(sums) + "\n").encode()
        files[signing.sums_name(self.version) + ".sig"] = signing.sign(TEST_SEED, files[signing.sums_name(self.version)])
        put(os.path.join(self.apk, client_updates.KIT), files)
        self.assertIsNone(client_updates.keep(self.out))
        self.assertIn("no release does", client_updates.failure(self.apk))

    def test_a_fetch_that_failed_waits_a_day(self):
        self.assertIsNone(client_updates.keep(self.out))
        self.assertIn("no way out", client_updates.failure(self.apk))
        self.asked.clear()
        client_updates.keep(self.out)
        self.assertEqual(self.asked, [])
        # A day later it is tried again, and the note goes once it works.
        when = os.path.getmtime(os.path.join(self.apk, client_updates.FAILED)) - 25 * 3600
        os.utime(os.path.join(self.apk, client_updates.FAILED), (when, when))
        self.served = release_files(self.version)
        self.assertEqual(client_updates.keep(self.out)["version"], "0.11.1")
        self.assertEqual(client_updates.failure(self.apk), "")


class Served(Place):
    """DEP-67: updates.json names what the site hands out, at the sizes of the files there; nothing else is."""

    def test_a_file_gone_or_of_another_size_hands_nothing_out(self):
        put(os.path.join(self.code, client_updates.KIT), release_files(self.version))
        client_updates.keep(self.out)
        self.assertIsNotNone(client_updates.kept(self.out))
        with open(os.path.join(self.out, client_updates.FOLDER, "releases.win.json"), "ab") as f:
            f.write(b" ")
        self.assertIsNone(client_updates.kept(self.out))

    def test_the_site_serves_only_what_updates_json_names(self):
        # The site's page (server/portal/updates.php) and this module agree on the folder, the manifest and its fields.
        portal = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "server", "portal", "updates.php")
        if not os.path.isfile(portal):
            portal = "/server/portal/updates.php"
        if not os.path.isfile(portal):
            # The tools alone, without the server's code beside them (CI mounts it at /server/portal).
            self.skipTest("the site's code is not here")
        with open(portal, encoding="utf-8") as f:
            page = f.read()
        self.assertIn("APK_DIR . '/updates.json'", page)
        self.assertIn("APK_DIR . '/updates/' . $name", page)
        self.assertIn("$made['files'][$name]", page)
        self.assertIn("filesize($path) !== (int)($about['size'] ?? -1)", page)
        self.assertEqual((client_updates.FOLDER, client_updates.MANIFEST), ("updates", "updates.json"))


if __name__ == "__main__":
    unittest.main()
