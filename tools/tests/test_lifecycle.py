"""The Server page and what it does (admin/lifecycle.py): its state on each install, restart and uninstall asked of the
server's program, the repair (repair.py), the data part by part and deleting it (server_data.py), the list of the
program's files (manifest.py), and the same through the API.

Flask is installed in the tools image only; outside it the page's tests are skipped (CI runs them there). The data, the
repair's steps and the list need only the standard library."""

import hashlib
import importlib.util
import io
import json
import os
import sqlite3
import tarfile
import tempfile
import time
import unittest
from unittest import mock

from opendmtq_tools import manifest, owner, repair, server_data

HAVE_FLASK = importlib.util.find_spec("flask") is not None
if HAVE_FLASK:
    from opendmtq_tools import admin
    from tests.test_admin import Install


def write(path, data=b"x"):
    """A file with its folders."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def layout_in(root):
    """The data's layout under root, as a host install has it."""
    return server_data.Layout({"OPENDMTQ_DB": os.path.join(root, "state", "dmtq.db3"), "OPENDMTQ_APK": os.path.join(root, "apk"),
                               "OPENDMTQ_BACKUPS": os.path.join(root, "backups"), "OPENDMTQ_CUSTOM": os.path.join(root, "custom"),
                               "OPENDMTQ_LOGS": os.path.join(root, "state", "logs"),
                               "OPENDMTQ_CONTENT": os.path.join(root, "content")})


def server_with_data(root):
    """A server's data with something in every part: players and plays, an account and a token, a closed recording and one
    still being made, an added song, an app, two backups, logs, the game's files and the signing key."""
    os.makedirs(os.path.join(root, "state"), exist_ok=True)
    con = sqlite3.connect(os.path.join(root, "state", "dmtq.db3"))
    con.executescript("""CREATE TABLE Member (id INTEGER PRIMARY KEY, nickname TEXT);
        CREATE TABLE Play (user_id INTEGER, score INTEGER);
        CREATE TABLE SiteUser (name TEXT PRIMARY KEY COLLATE NOCASE, pass TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
                               admin INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL DEFAULT 0, signed_in_at INTEGER,
                               off INTEGER NOT NULL DEFAULT 0, guid INTEGER);
        CREATE TABLE ApiToken (id TEXT PRIMARY KEY, name TEXT NOT NULL, scope TEXT NOT NULL, hash TEXT NOT NULL,
                               admin TEXT NOT NULL COLLATE NOCASE, owner INTEGER NOT NULL DEFAULT 0, admin_since INTEGER,
                               created_at INTEGER NOT NULL, used_at INTEGER);
        CREATE TABLE BoardStamp (n INTEGER NOT NULL);
        INSERT INTO Member VALUES (1, 'one'), (2, 'two');
        INSERT INTO Play VALUES (1, 900000), (2, 800000);
        INSERT INTO SiteUser (name, pass) VALUES ('player1', 'x');
        INSERT INTO ApiToken (id, name, scope, hash, admin, created_at) VALUES ('000000000001', 'nightly', 'write', 'h', 'admin', 1);
        INSERT INTO BoardStamp VALUES (7);""")
    con.commit()
    con.close()
    write(os.path.join(root, "state", "live-rec", "1", "1800000000", "0.ts"), b"r" * 1000)
    write(os.path.join(root, "state", "live-rec", "2", "1800000100", ".open"), b"")
    write(os.path.join(root, "state", "live-rec", "limits.json"), b'{"cap_gb": 20}')
    write(os.path.join(root, "custom", "songs", "301", "song.json"), json.dumps({"name": "added"}).encode())
    write(os.path.join(root, "custom", "thumbs", "added.jpg"))
    write(os.path.join(root, "custom", "ids.json"), b"{}")
    write(os.path.join(root, "apk", "out", "OpenDMTQ-x.apk"), b"a" * 5000)
    write(os.path.join(root, "apk", "out", "latest.json"), b"{}")
    write(os.path.join(root, "apk", "keystore", "key.jks"), b"k")
    write(os.path.join(root, "backups", "opendmtq-20260101-000000-manual.tar.gz"), b"b" * 300)
    write(os.path.join(root, "backups", "opendmtq-20260102-000000-daily.tar.gz"), b"b" * 300)
    write(os.path.join(root, "state", "logs", "access.log"), b"GET /\n" * 50)
    write(os.path.join(root, "state", "logs", "access.log.1"), b"GET /\n" * 50)
    write(os.path.join(root, "state", "changes.log"), b'{"what": "login:ok"}\n')
    write(os.path.join(root, "content", "web", "patch", "file.csv"), b"g" * 2000)
    write(os.path.join(root, "apk", "base", "client.apk"), b"c" * 3000)


class DataTest(unittest.TestCase):
    """server_data.py: each part's size, and each part deleted as the Server page and the command lines delete it, while a
    server may run (ADM-110)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        server_with_data(self.root)
        self.layout = layout_in(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def test_every_part_is_counted(self):
        sizes = server_data.sizes(self.layout)
        self.assertEqual(list(sizes), list(server_data.PARTS))
        self.assertEqual(sizes["recordings"]["bytes"], 1000 + len(b'{"cap_gb": 20}'))
        self.assertEqual(sizes["apps"]["bytes"], 5002)
        self.assertEqual(sizes["backups"]["bytes"], 600)
        self.assertEqual(sizes["game"]["bytes"], 5000)
        self.assertTrue(all(info["can_delete"] for info in sizes.values()))

    def test_a_file_linked_twice_counts_once(self):
        # A broadcast's piece is in its stream and in its recording.
        os.link(self.path("state", "live-rec", "1", "1800000000", "0.ts"), self.path("state", "live-rec", "1", "1800000000", "1.ts"))
        self.assertEqual(server_data.sizes(self.layout)["recordings"]["bytes"], 1000 + len(b'{"cap_gb": 20}'))

    def test_the_database_loses_its_rows_and_keeps_its_tables_and_tokens(self):
        done = server_data.delete(self.layout, ["database"], say=lambda line: None)
        self.assertEqual(done, {"database": True})
        con = sqlite3.connect(self.path("state", "dmtq.db3"))
        try:
            counts = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in ("Member", "Play", "SiteUser", "ApiToken", "BoardStamp")}
        finally:
            con.close()
        self.assertEqual(counts, {"Member": 0, "Play": 0, "SiteUser": 0, "ApiToken": 1, "BoardStamp": 1})

    def test_a_recording_being_made_stays_and_so_do_the_limits(self):
        server_data.delete(self.layout, ["recordings"], say=lambda line: None)
        self.assertFalse(os.path.exists(self.path("state", "live-rec", "1")))
        self.assertTrue(os.path.exists(self.path("state", "live-rec", "2", "1800000100", ".open")))
        self.assertTrue(os.path.exists(self.path("state", "live-rec", "limits.json")))

    def test_added_songs_go_with_their_tiles_and_their_ids_stay(self):
        server_data.delete(self.layout, ["songs"], say=lambda line: None, rebuild=False)
        self.assertFalse(os.path.exists(self.path("custom", "songs")))
        self.assertFalse(os.path.exists(self.path("custom", "thumbs", "added.jpg")))
        self.assertTrue(os.path.exists(self.path("custom", "ids.json")))

    def test_apps_go_and_the_signing_key_stays(self):
        server_data.delete(self.layout, ["apps"], say=lambda line: None)
        self.assertEqual(os.listdir(self.path("apk", "out")), [])
        self.assertTrue(os.path.exists(self.path("apk", "keystore", "key.jks")))

    def test_backups_go_but_the_one_kept(self):
        server_data.delete(self.layout, ["backups"], keep=["opendmtq-20260102-000000-daily.tar.gz"], say=lambda line: None)
        self.assertEqual(os.listdir(self.path("backups")), ["opendmtq-20260102-000000-daily.tar.gz"])

    def test_logs_are_emptied_in_place_and_their_old_copies_go(self):
        server_data.delete(self.layout, ["logs"], say=lambda line: None)
        self.assertEqual(os.path.getsize(self.path("state", "logs", "access.log")), 0)
        self.assertFalse(os.path.exists(self.path("state", "logs", "access.log.1")))
        self.assertEqual(os.path.getsize(self.path("state", "changes.log")), 0)

    def test_the_game_files_go_and_their_folders_stay(self):
        server_data.delete(self.layout, ["game"], say=lambda line: None)
        self.assertEqual(os.listdir(self.path("content")), [])
        self.assertEqual(os.listdir(self.path("apk", "base")), [])

    def test_a_part_it_cannot_write_is_left_as_it_is(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root writes anywhere")
        os.chmod(self.path("content"), 0o555)
        try:
            self.assertFalse(server_data.sizes(self.layout)["game"]["can_delete"])
            self.assertEqual(server_data.delete(self.layout, ["game"], say=lambda line: None), {"game": False})
            self.assertTrue(os.path.exists(self.path("content", "web")))
        finally:
            os.chmod(self.path("content"), 0o755)

    def test_no_such_part(self):
        with self.assertRaises(ValueError):
            server_data.delete(self.layout, ["everything"])

    def test_the_backup_holds_the_database_the_key_and_the_added_songs(self):
        name = server_data.backup(self.layout)
        with tarfile.open(self.path("backups", name)) as tar:
            names = tar.getnames()
        self.assertIn("dmtq.db3", names)
        self.assertIn("keystore/key.jks", names)
        self.assertIn("custom/songs/301/song.json", names)
        if os.name == "posix":
            self.assertEqual(os.stat(self.path("backups", name)).st_mode & 0o077, 0)

    def test_the_command_backs_up_first_and_keeps_that_backup(self):
        with mock.patch.dict(os.environ, {"OPENDMTQ_DB": self.layout.db, "OPENDMTQ_APK": self.layout.apk,
                                          "OPENDMTQ_BACKUPS": self.layout.backups, "OPENDMTQ_CUSTOM": self.layout.custom,
                                          "OPENDMTQ_LOGS": self.layout.logs, "OPENDMTQ_CONTENT": self.layout.content}):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                self.assertEqual(server_data.main(["delete", "backups", "--backup"]), 0)
        made = [line.split(" ", 1)[1] for line in out.getvalue().splitlines() if line.startswith("backup ")]
        self.assertEqual(os.listdir(self.path("backups")), made)


class ManifestTest(unittest.TestCase):
    """manifest.py: the list of the program's files, what differs from it, and each one put back from the release's own
    code (SRV-45)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, "OpenDMTQ")
        write(os.path.join(self.root, "opendmtq"), b"#!/usr/bin/env python3\n")
        write(os.path.join(self.root, "host", "opendmtq_host", "cli.py"), b"print('cli')\n")
        write(os.path.join(self.root, "server", "portal", "login.php"), b"<?php\n")
        # What is no program file: the settings, the data, this install's own folder, Python's caches.
        write(os.path.join(self.root, ".env"), b"ADMIN_PASSWORD=x\n")
        write(os.path.join(self.root, "data", "state", "dmtq.db3"), b"db")
        write(os.path.join(self.root, "host", "opendmtq_host", "__pycache__", "cli.cpython-312.pyc"), b"pyc")

    def tearDown(self):
        self._tmp.cleanup()

    def release(self):
        """The release's code as GitHub's archive has it: one folder on top."""
        archive = os.path.join(self._tmp.name, "release.tar.gz")
        with tarfile.open(archive, "w:gz") as tar:
            for rel in ("opendmtq", "host/opendmtq_host/cli.py", "server/portal/login.php"):
                tar.add(os.path.join(self.root, *rel.split("/")), arcname=f"openDMTQ-0.11.0/{rel}")
        return "file://" + archive

    def test_the_list_has_the_program_and_nothing_else(self):
        listed = os.path.join(self.root, ".host", "manifest.sha256")
        manifest.write(self.root, listed)
        entries = manifest.read(listed)
        self.assertEqual(sorted(entries), ["host/opendmtq_host/cli.py", "opendmtq", "server/portal/login.php"])
        self.assertEqual(entries["opendmtq"], hashlib.sha256(b"#!/usr/bin/env python3\n").hexdigest())
        self.assertEqual(manifest.find(self.root), listed)
        self.assertEqual(manifest.check(self.root, entries), ([], []))

    def test_sha256sum_lines_read_the_same(self):
        # What host/get.sh writes: sha256sum's "./path".
        listed = os.path.join(self._tmp.name, "list")
        with open(listed, "w", encoding="utf-8") as f:
            f.write(f"{hashlib.sha256(b'#!/usr/bin/env python3' + bytes([10])).hexdigest()}  ./opendmtq\n")
        self.assertEqual(list(manifest.read(listed)), ["opendmtq"])

    def test_what_is_missing_or_changed_is_found_and_put_back(self):
        url = self.release()
        listed = os.path.join(self.root, ".host", "manifest.sha256")
        manifest.write(self.root, listed)
        entries = manifest.read(listed)
        os.remove(os.path.join(self.root, "server", "portal", "login.php"))
        write(os.path.join(self.root, "host", "opendmtq_host", "cli.py"), b"broken")
        missing, changed = manifest.check(self.root, entries)
        self.assertEqual((missing, changed), (["server/portal/login.php"], ["host/opendmtq_host/cli.py"]))
        put = manifest.put_back(self.root, entries, missing + changed, url)
        self.assertEqual(sorted(put), ["host/opendmtq_host/cli.py", "server/portal/login.php"])
        self.assertEqual(manifest.check(self.root, entries), ([], []))

    def test_the_repair_puts_them_back_from_the_release_or_says_which(self):
        url = self.release()
        manifest.write(self.root, os.path.join(self.root, ".host", "manifest.sha256"))
        write(os.path.join(self.root, "host", "opendmtq_host", "cli.py"), b"broken")
        # No release to ask (no VERSION, no copy given): said by name.
        with mock.patch.dict(os.environ, {"OPENDMTQ_TARBALL": ""}):
            self.assertEqual(repair.files(self.root, ""), ("bad", "host/opendmtq_host/cli.py"))
        with mock.patch.dict(os.environ, {"OPENDMTQ_TARBALL": url}):
            self.assertEqual(repair.files(self.root, "0.11.0"), ("fixed", "host/opendmtq_host/cli.py"))
        self.assertEqual(repair.files(self.root, "0.11.0")[0], "ok")

    def test_an_install_without_a_list_is_skipped(self):
        self.assertEqual(repair.files(self.root, "0.11.0"), ("skip", ""))


class RepairStepsTest(unittest.TestCase):
    """repair.py's steps that need no admin pages: the folders, the database, the owner's sign-in, the app (SRV-46)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        server_with_data(self.root)
        self.layout = layout_in(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_folders_are_made_again(self):
        import shutil
        shutil.rmtree(os.path.join(self.root, "backups"))
        state, detail = repair.folders(self.layout)
        self.assertEqual(state, "fixed")
        self.assertIn("backups", detail)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "backups")))
        self.assertEqual(repair.folders(self.layout), ("ok", ""))

    def test_a_damaged_database_is_said(self):
        self.assertEqual(repair.database(self.layout), ("ok", ""))
        with open(self.layout.db, "r+b") as f:
            f.seek(100)
            f.write(b"\xff" * 4000)
        self.assertEqual(repair.database(self.layout)[0], "bad")

    def test_the_owner_sign_in_is_written_from_the_password(self):
        self.assertEqual(repair.owner_file(self.layout, "admin", "pw"), ("fixed", ""))
        self.assertEqual(repair.owner_file(self.layout, "admin", "pw"), ("ok", ""))
        with open(os.path.join(self.root, "state", "owner.pass"), encoding="utf-8") as f:
            name, stored = f.read().splitlines()
        self.assertEqual(name, "admin")
        self.assertTrue(owner.password_ok(stored, "pw"))
        self.assertEqual(repair.owner_file(self.layout, "admin", ""), ("skip", ""))

    def test_the_app_for_this_address_or_not(self):
        write(os.path.join(self.root, "apk", "out", "latest.json"), json.dumps({"file": "OpenDMTQ-x.apk", "host": "192.168.1.10"}).encode())
        self.assertEqual(repair.app(self.layout, "192.168.1.10"), ("ok", "OpenDMTQ-x.apk"))
        self.assertEqual(repair.app(self.layout, "192.168.1.20"), ("bad", "other_address"))
        os.remove(os.path.join(self.root, "apk", "out", "OpenDMTQ-x.apk"))
        self.assertEqual(repair.app(self.layout, "192.168.1.10"), ("bad", "missing"))
        os.remove(os.path.join(self.root, "apk", "base", "client.apk"))
        self.assertEqual(repair.app(self.layout, "192.168.1.10"), ("skip", ""))


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class ServerPageTest(unittest.TestCase):
    """The Server page on each install, and what it asks of the server's program (ADM-108, ADM-109, ADM-111)."""

    def host(self, inst):
        """These pages as a host install has them: the run folder the server's program reads."""
        run = inst.path("run")
        os.makedirs(run, exist_ok=True)
        return mock.patch.multiple(admin.setup, HOST_INSTALL=True, RUN_DIR=run)

    def test_in_containers_it_says_the_commands(self):
        with Install() as inst:
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
        self.assertIn("./opendmtq down", page)
        self.assertIn("./opendmtq restart", page)
        self.assertIn("./opendmtq uninstall", page)
        self.assertNotIn('action="/opendmtq/admin/server/restart"', page)
        self.assertNotIn('action="/opendmtq/admin/server/uninstall"', page)
        # The one address, on the server's own port: never another.
        self.assertIn("http://192.168.0.10/opendmtq/admin/", page)

    def test_on_a_host_install_it_restarts_stops_and_uninstalls(self):
        with Install() as inst, self.host(inst):
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            for action in ("restart", "stop", "uninstall", "repair", "data"):
                self.assertIn(f'action="/opendmtq/admin/server/{action}"', page, action)
            # Restart: asked of the program, and the page waits for the pages to answer again.
            with inst.client.session_transaction("/opendmtq/admin/") as s:
                token = s["csrf"]
            r = inst.client.post("/opendmtq/admin/server/restart", data={"csrf": token})
            self.assertEqual(r.status_code, 200)
            self.assertIn('id="restart-wait"', r.get_data(as_text=True))
            self.assertTrue(os.path.exists(inst.path("run/restart.request")))

    def test_an_uninstall_needs_the_word(self):
        with Install() as inst, self.host(inst):
            inst.sign_in()
            with inst.client.session_transaction("/opendmtq/admin/") as s:
                token = s["csrf"]
            r = inst.client.post("/opendmtq/admin/server/uninstall", data={"csrf": token, "confirm": "yes"})
            self.assertEqual(r.status_code, 302)
            self.assertFalse(os.path.exists(inst.path("run/uninstall.request")))
            r = inst.client.post("/opendmtq/admin/server/uninstall", data={"csrf": token, "confirm": "제거", "keep": "yes"})
            self.assertEqual(r.status_code, 200)
            self.assertIn('id="stop-wait"', r.get_data(as_text=True))
            with open(inst.path("run/uninstall.request"), encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"keep_data": True})

    def test_in_containers_restart_and_uninstall_are_not_there(self):
        with Install() as inst:
            inst.sign_in()
            with inst.client.session_transaction("/opendmtq/admin/") as s:
                token = s["csrf"]
            self.assertEqual(inst.client.post("/opendmtq/admin/server/restart", data={"csrf": token}).status_code, 404)
            self.assertEqual(inst.client.post("/opendmtq/admin/server/uninstall", data={"csrf": token, "confirm": "uninstall"}).status_code, 404)

    def test_the_stopped_page_names_the_one_address_and_follows_the_stop(self):
        with Install() as inst, self.host(inst):
            inst.sign_in()
            with inst.client.session_transaction("/opendmtq/admin/") as s:
                token = s["csrf"]
            page = inst.client.post("/opendmtq/admin/server/stop", data={"csrf": token}).get_data(as_text=True)
        self.assertIn('id="stop-wait"', page)
        self.assertIn("http://192.168.0.10/", page)
        self.assertIn('data-ping="/opendmtq/admin/setup/ping"', page)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class PortMoveTest(unittest.TestCase):
    """Moving the server to another port from the Server page and the API (API-43): .env's LISTEN_PORT and the port in
    PUBLIC_HOST, from the next start; refused in words for a port another program holds, the one it is on, no port, and
    where the command line does it (the command named)."""

    def host(self, inst):
        """A host install's pages, with its .env as a server set up on 8791 has it."""
        env_file = inst.path(".env")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("PUBLIC_HOST=192.168.0.10:8791\nLISTEN_PORT=8791\nADMIN_PASSWORD=pw\n")
        return mock.patch.multiple(admin.setup, HOST_INSTALL=True, RUN_DIR=inst.path("run"), ENV_FILE=env_file)

    def token(self, inst):
        """A token for the API, on a server's database (the tokens' table is in it)."""
        server_with_data(inst.root)
        with admin.app.test_request_context():
            _, token = admin.tokens.make("test", "write", ("admin", True, None))
        return {"Authorization": f"Bearer {token}"}

    def test_a_move_from_the_page_takes_effect_at_the_next_start(self):
        with Install() as inst, self.host(inst), mock.patch.object(admin.core, "PUBLIC_HOST", "192.168.0.10:8791"), \
                mock.patch.object(admin.lifecycle, "port_free", lambda port: True):
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            self.assertIn("Port 8791 carries everything", page)
            self.assertIn('action="/opendmtq/admin/server/port"', page)
            with inst.client.session_transaction("/opendmtq/admin/") as s:
                csrf = s["csrf"]
            r = inst.client.post("/opendmtq/admin/server/port", data={"csrf": csrf, "port": "8792"})
            self.assertEqual(r.status_code, 302)
            with open(inst.path(".env"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "PUBLIC_HOST=192.168.0.10:8792\nLISTEN_PORT=8792\nADMIN_PASSWORD=pw\n")
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            # Said, and kept in sight until the next start: where it will be.
            self.assertIn("From the server's next start it answers here: http://192.168.0.10:8792/", page)
            self.assertIn("From the next start: http://192.168.0.10:8792/", page)

    def test_what_is_refused_is_said(self):
        with Install() as inst, self.host(inst), mock.patch.object(admin.core, "PUBLIC_HOST", "192.168.0.10:8791"):
            headers = self.token(inst)
            with mock.patch.object(admin.lifecycle, "port_free", lambda port: False):
                taken = inst.client.post("/opendmtq/api/v1/server/port", json={"port": 8792}, headers=headers)
            self.assertEqual((taken.status_code, taken.get_json()["error"]["code"]), (409, "port_taken"))
            self.assertIn("Port 8792 is taken on this computer by another program", taken.get_json()["error"]["message"])
            same = inst.client.post("/opendmtq/api/v1/server/port", json={"port": 8791}, headers=headers)
            self.assertEqual(same.get_json()["error"]["code"], "same_port")
            bad = inst.client.post("/opendmtq/api/v1/server/port", json={"port": 70000}, headers=headers)
            self.assertEqual((bad.status_code, bad.get_json()["error"]["code"]), (400, "bad_port"))
            # Nothing written by any of them.
            with open(inst.path(".env"), encoding="utf-8") as f:
                self.assertIn("LISTEN_PORT=8791", f.read())
            with mock.patch.object(admin.lifecycle, "port_free", lambda port: True):
                moved = inst.client.post("/opendmtq/api/v1/server/port", json={"port": 8792}, headers=headers)
            self.assertEqual(moved.get_json(), {"port": 8792, "address": "http://192.168.0.10:8792/", "from_next_start": True})
            self.assertEqual(inst.client.get("/opendmtq/api/v1/server", headers=headers).get_json()["next_address"], "192.168.0.10:8792")

    def test_in_containers_the_command_line_does_it(self):
        with Install() as inst:
            r = inst.client.post("/opendmtq/api/v1/server/port", json={"port": 8792}, headers=self.token(inst))
            self.assertEqual((r.status_code, r.get_json()["error"]["code"]), (409, "by_command"))
            self.assertIn("./opendmtq port <port>", r.get_json()["error"]["message"])
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
            self.assertIn("./opendmtq port &lt;port&gt;", page)
            self.assertNotIn('action="/opendmtq/admin/server/port"', page)


class DeleteAndRepairTest(unittest.TestCase):
    """Deleting the data and the repair from the page and the API, as jobs (ADM-110, ADM-112, API-45, API-46)."""

    def setUp(self):
        self.inst = Install().__enter__()
        server_with_data(self.inst.root)
        # The admin pages' paths onto this test's data (Install's own patch covers the database, the apps and backups).
        self.extra = mock.patch.dict(os.environ, {"OPENDMTQ_DB": self.inst.path("state/dmtq.db3"), "OPENDMTQ_APK": self.inst.path("apk"),
                                                  "OPENDMTQ_BACKUPS": self.inst.path("backups"),
                                                  "OPENDMTQ_CUSTOM": self.inst.path("custom"),
                                                  "OPENDMTQ_LOGS": self.inst.path("state/logs"),
                                                  "OPENDMTQ_CONTENT": self.inst.path("content")})
        self.extra.start()
        self.inst.sign_in()
        with self.inst.client.session_transaction("/opendmtq/admin/") as s:
            self.csrf = s["csrf"]

    def tearDown(self):
        self.extra.stop()
        self.inst.__exit__(None, None, None)
        # The jobs are the service's, kept in memory: the other tests start with none.
        for job in list(admin.jobs._jobs.values()):
            job["ended"].wait(30)
        admin.jobs._jobs.clear()

    def wait(self, job_id):
        job = admin.jobs._jobs[job_id]
        self.assertTrue(job["ended"].wait(30))
        return job

    def test_the_page_lists_each_part_with_its_size(self):
        page = self.inst.client.get("/opendmtq/admin/server").get_data(as_text=True)
        for part in server_data.PARTS:
            self.assertIn(f'value="{part}"', page)
        self.assertIn("4.9 KB", page)

    def test_without_the_word_nothing_goes(self):
        r = self.inst.client.post("/opendmtq/admin/server/data", data={"csrf": self.csrf, "part": "apps", "backup": "yes"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(os.path.exists(self.inst.path("apk/out/OpenDMTQ-x.apk")))

    def test_a_backup_first_then_the_parts_ticked(self):
        r = self.inst.client.post("/opendmtq/admin/server/data", data={"csrf": self.csrf, "part": ["database", "backups"],
                                                                     "backup": "yes", "confirm": "delete"})
        self.assertEqual(r.status_code, 302)
        backups = os.listdir(self.inst.path("backups"))
        # The backup made first stays; the two before it went.
        self.assertEqual(len(backups), 1)
        self.assertIn("before-delete", backups[0])
        con = sqlite3.connect(self.inst.path("state/dmtq.db3"))
        try:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM Member").fetchone()[0], 0)
        finally:
            con.close()
        with open(self.inst.path("state/changes.log"), encoding="utf-8") as f:
            self.assertIn("server:delete-data", f.read())

    def test_the_api_deletes_with_the_word_and_counts_the_parts(self):
        with admin.app.test_request_context():
            _, token = admin.tokens.make("test", "write", ("admin", True, None))
        headers = {"Authorization": f"Bearer {token}"}
        listed = self.inst.client.get("/opendmtq/api/v1/server/data", headers=headers).get_json()
        self.assertEqual([p["part"] for p in listed["items"]], list(server_data.PARTS))
        refused = self.inst.client.post("/opendmtq/api/v1/server/data/delete", json={"parts": ["apps"], "confirm": "no"}, headers=headers)
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.get_json()["error"]["code"], "not_confirmed")
        answer = self.inst.client.post("/opendmtq/api/v1/server/data/delete", json={"parts": ["apps"], "backup": False, "confirm": "delete"},
                                       headers=headers)
        self.assertEqual(answer.status_code, 202)
        self.assertEqual(self.wait(answer.get_json()["job"]["id"])["state"], "done")
        self.assertEqual(os.listdir(self.inst.path("apk/out")), [])
        state = self.inst.client.get("/opendmtq/api/v1/server", headers=headers).get_json()
        self.assertEqual(state["install"], "docker")
        self.assertFalse(state["runs_itself"])
        self.assertEqual(state["commands"]["uninstall"], "./opendmtq uninstall")
        self.assertEqual(self.inst.client.post("/opendmtq/api/v1/server/uninstall", json={"confirm": "uninstall"}, headers=headers).status_code, 404)

    def test_the_repair_makes_folders_and_the_owner_sign_in_again(self):
        import shutil
        shutil.rmtree(self.inst.path("backups"))
        os.makedirs(self.inst.path("backups"))
        shutil.rmtree(self.inst.path("state/live-rec"))
        with mock.patch.object(admin.apps, "start_build", return_value=("job1", "192.168.0.10")) as build:
            r = self.inst.client.post("/opendmtq/admin/server/repair", data={"csrf": self.csrf})
            self.assertEqual(r.status_code, 302)
            job = max(admin.jobs.listing(), key=lambda j: j["started"])
            self.wait(job["id"])
        said = " ".join(words for _, words in job["said"])
        self.assertIn("made again", said)
        self.assertTrue(os.path.isdir(self.inst.path("state/live-rec")))
        self.assertTrue(os.path.exists(self.inst.path("state/owner.pass")))
        # latest.json names no app: built again, as the App page builds it.
        build.assert_called_once()


if __name__ == "__main__":
    unittest.main()
