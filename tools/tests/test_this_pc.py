"""Tests for Play on this PC (admin/this_pc.py): who sees it (a visit from the server PC alone), what it says on each kind
of server, the installer it runs (this server's, with the ID on its end) and the launcher it opens, on the App page, the
setup's last step and the API.

Flask is installed in the tools image only; outside it these tests are skipped (CI runs them there).
"""

import errno
import json
import os
import re
import struct
import time
import unittest
from unittest import mock

from tests.test_admin import HAVE_FLASK, HOST, Install, old_game_database

if HAVE_FLASK:
    from opendmtq_tools import admin, windows_client
    from opendmtq_tools.admin import this_pc

BASE = "/opendmtq/admin"
# A visit from another computer on the network, and the server PC's own addresses.
ELSEWHERE, LOOPBACK = "192.168.0.50", "127.0.0.1"


def end_of(path):
    """The server's details on an installer's end, as the PC client reads them (client/opendmtq_client/preset.py)."""
    with open(path, "rb") as f:
        data = f.read()
    assert data[-16:] == windows_client.MAGIC
    length = struct.unpack("<I", data[-20:-16])[0]
    return json.loads(data[-20 - length:-20].decode("utf-8"))


class Process:
    """A stand-in for a program the job starts: it notes what it was started with (and the installer's end, read while the
    copy is still there), and ends with `code`."""

    def __init__(self, seen, code):
        self.seen, self.code = seen, code

    def __call__(self, command, cwd):
        self.seen.append({"command": command, "cwd": cwd,
                          "end": end_of(command[0]) if command[0].endswith(".exe") and "--silent" in command else None})
        return self

    def wait(self, timeout=None):
        return self.code

    def kill(self):
        pass


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class PlayHereTest(unittest.TestCase):
    """The App page and the setup's last step on each kind of server, and what pressing it does."""

    def server(self, kind="windows", installer=True, installed=None, code=0):
        """A server of this kind (lifecycle.install_kind), its installer for Windows kept or not, the PC client installed
        for this Windows user at a version or not, and the programs it starts standing in (ending with `code`)."""
        inst = Install().__enter__()
        self.addCleanup(inst.__exit__, None, None, None)
        old_game_database(inst.path("state/dmtq.db3"), [])
        # The phone app built for this server: the setup's last step shows what to do with it, Play on this PC with it.
        inst.app_for(HOST)
        local = inst.path("local")
        os.makedirs(local)
        if installer:
            # The installer as the builder keeps it for the site, with what it is beside it.
            with open(inst.path("apk/out/OpenDMTQ-Setup.exe"), "wb") as f:
                f.write(b"MZ" + b"\0" * (1 << 20))
            inst.write("apk/out/windows.json", json.dumps({"file": "OpenDMTQ-Setup.exe", "size": (1 << 20) + 2,
                                                           "sha256": "0", "version": "0.11.0"}))
        if installed is not None:
            os.makedirs(os.path.join(local, "OpenDMTQ.Client", "current"))
            with open(os.path.join(local, "OpenDMTQ.Client", "OpenDMTQ.exe"), "wb") as f:
                f.write(b"MZ")
            if installed:
                with open(os.path.join(local, "OpenDMTQ.Client", "current", "sq.version"), "w", encoding="utf-8") as f:
                    f.write("<package><version>%s</version></package>" % installed)
        self.started = []
        for patch in (mock.patch.object(admin.lifecycle, "install_kind", lambda: kind),
                      mock.patch.object(admin.setup, "HOST_INSTALL", kind in ("windows", "host")),
                      mock.patch.dict(os.environ, {"LOCALAPPDATA": local}),
                      mock.patch.object(this_pc, "start_program", Process(self.started, code)),
                      # The site over plain HTTP, as on a local network.
                      mock.patch.object(admin.apps, "installer_scheme", lambda: "http")):
            patch.start()
            self.addCleanup(patch.stop)
        inst.sign_in()
        self.inst, self.local = inst, local
        return inst

    def page(self, path, remote=LOOPBACK):
        """A page as a browser at `remote` sees it."""
        r = self.inst.client.get(BASE + path, environ_base={"REMOTE_ADDR": remote})
        self.assertEqual(r.status_code, 200, path)
        return r.get_data(as_text=True)

    def press(self, back="app", remote=LOOPBACK):
        """Play on this PC, as its form sends it from a page; the page it returns to, with what it says."""
        page = self.inst.client.get(BASE + ("/setup?step=app" if back == "setup" else "/app"),
                                    environ_base={"REMOTE_ADDR": remote}).get_data(as_text=True)
        csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
        r = self.inst.client.post(BASE + "/app/play-here", data={"csrf": csrf, "back": back},
                                  environ_base={"REMOTE_ADDR": remote})
        self.assertEqual(r.status_code, 302)
        return r.headers["Location"], self.inst.client.get(r.headers["Location"], environ_base={"REMOTE_ADDR": remote}).get_data(as_text=True)

    def test_a_visit_from_another_pc_never_sees_it(self):
        self.server()
        for path in ("/app", "/setup?step=app"):
            self.assertNotIn('id="this-pc"', self.page(path, remote=ELSEWHERE), path)
        # Sent all the same: refused in words, nothing run.
        _, said = self.press(remote=ELSEWHERE)
        self.assertIn("Play on this PC works from the server PC itself, in its own browser.", said)
        self.assertEqual(self.started, [])

    def test_the_windows_bundle_installs_the_pc_client_set_up_for_this_server(self):
        self.server()
        shown = self.page("/app")
        self.assertIn('id="this-pc"', shown)
        self.assertIn("Installs the PC client on this PC, set up for this server, and opens it with your ID (admin)", shown)
        self.assertRegex(shown, r'<button class="btn"[^>]*>Play on this PC</button>')
        where, said = self.press()
        self.assertEqual(where, BASE + "/app")
        self.assertIn("Installed the PC client. Its launcher opens with this server and your ID (admin) filled in.", said)
        # The installer this server keeps, under the name the site hands it out by, run with --silent, with this server
        # and the ID on its end (never a password), then gone.
        [run] = self.started
        target, flag = run["command"]
        self.assertEqual(flag, "--silent")
        self.assertEqual(os.path.basename(target), "opendmtq-pc-client-0.11.0-windows-x64-setup-%s.exe" % HOST)
        self.assertEqual(run["end"], {"version": 1, "url": "http://" + HOST, "name": HOST, "account": "admin"})
        self.assertFalse(os.path.exists(os.path.dirname(target)))
        # In the log of changes, by who pressed it.
        r = self.inst.client.get(BASE + "/logs?tab=changes")
        self.assertIn("Played on the server PC (the PC client installed or opened there)", r.get_data(as_text=True))

    def test_installed_already_it_opens_the_launcher_with_the_server_and_the_id(self):
        self.server(installed="0.11.0")
        shown = self.page("/setup?step=app")
        self.assertIn("OpenDMTQ 0.11.0 is installed on this PC. It opens set up for this server, with your ID (admin)", shown)
        where, said = self.press(back="setup")
        self.assertEqual(where, BASE + "/setup?step=app")
        self.assertIn("The launcher opens with this server and your ID (admin) filled in.", said)
        # The launcher's stub, started; the server and the ID where an installer leaves them for it.
        [run] = self.started
        self.assertEqual(run["command"], [os.path.join(self.local, "OpenDMTQ.Client", "OpenDMTQ.exe")])
        with open(os.path.join(self.local, "OpenDMTQ", "client", "preset.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"version": 1, "url": "http://" + HOST, "name": HOST, "account": "admin"})
        # Installed without saying its version: said without one.
        os.remove(os.path.join(self.local, "OpenDMTQ.Client", "current", "sq.version"))
        self.assertIn("The PC client is installed on this PC.", self.page("/app"))

    def test_without_an_installer_and_not_installed_it_says_so_and_offers_nothing(self):
        self.server(installer=False)
        with mock.patch.object(windows_client, "HERE", self.inst.path("nowhere")):
            shown = self.page("/app")
        self.assertIn("this server keeps no installer for Windows", shown)
        self.assertNotRegex(shown, r'>Play on this PC</button>')

    def test_before_the_app_is_built_the_installer_beside_the_code_is_used(self):
        # The site hands its copy out once the app is built; the Windows bundle brings one beside its code from the start.
        self.server(installer=False)
        os.makedirs(self.inst.path("code"))
        with open(self.inst.path("code/OpenDMTQ-Setup.exe"), "wb") as f:
            f.write(b"MZ" + b"\0" * (1 << 20))
        self.inst.write("code/OpenDMTQ-Setup.exe.version", "0.11.0\n")
        with mock.patch.object(windows_client, "HERE", self.inst.path("code")):
            self.assertIn("Installs the PC client on this PC", self.page("/app"))
            _, said = self.press()
        self.assertIn("Installed the PC client.", said)
        [run] = self.started
        self.assertEqual(os.path.basename(run["command"][0]), "opendmtq-pc-client-0.11.0-windows-x64-setup-%s.exe" % HOST)
        self.assertEqual(run["end"]["account"], "admin")

    def test_an_installer_that_fails_or_meets_a_game_says_why(self):
        self.server(code=2)
        _, said = self.press()
        self.assertIn("The PC client was not installed: the installer ended with 2.", said)
        self.assertIn("OpenDMTQ-setup.log", said)
        self.server(code=this_pc.GAME_OPEN)
        _, said = self.press()
        self.assertIn("The game is open on this PC, and the installer installs nothing under it.", said)

    def test_a_program_that_cannot_start_is_said_in_the_pages_words(self):
        # The system's own words are in its language, which may not be the page's: the usual reasons are said in the
        # page's words, in both languages, and any other as the system says it (ADM-192).
        def refused(error):
            def start(command, cwd):
                raise error
            return start
        windows = OSError(errno.EINVAL, "%1 is not a valid Win32 application")
        windows.winerror = 193
        for error, words in ((PermissionError(errno.EACCES, "Permission denied"), "this PC did not let it run"),
                             (FileNotFoundError(errno.ENOENT, "No such file or directory"), "its file is not there"),
                             (OSError(errno.ENOSPC, "No space left on device"), "the disk is full"),
                             (windows, "its file is damaged"),
                             (OSError(errno.EIO, "Input/output error"), "Input/output error")):
            self.server()
            with mock.patch.object(this_pc, "start_program", refused(error)):
                _, said = self.press()
            self.assertIn("The PC client did not start: " + words, said)
        self.server(installed="0.11.0")
        self.inst.client.set_cookie("opendmtq_lang", "ko", path="/")
        with mock.patch.object(this_pc, "start_program", refused(PermissionError(errno.EACCES, "Permission denied"))):
            _, said = self.press()
        self.assertIn("PC 클라이언트를 시작하지 못했습니다: 이 PC에서 실행이 허용되지 않았습니다", said)
        self.assertNotIn("Permission denied", said)

    def test_linux_and_macos_show_nothing_and_the_api_says_why(self):
        # No card of how to play from a Windows PC on the pages (the docs say it, play.md): nothing on the App page or the
        # setup's last step; a press through the form or the API is refused with the words of where to play (ADM-201).
        for kind in ("host", "docker"):
            self.server(kind=kind)
            for path in ("/app", "/setup?step=app"):
                shown = self.page(path)
                self.assertNotIn('id="this-pc"', shown)
                self.assertNotIn("Play on a Windows PC", shown)
            _, said = self.press()
            self.assertIn("The PC client runs on Windows.", said)
            self.assertEqual(self.started, [])

    def test_kubernetes_has_no_pc_of_its_own(self):
        self.server(kind="kubernetes")
        with mock.patch.object(admin.setup, "IN_KUBERNETES", True):
            self.assertNotIn('id="this-pc"', self.page("/app"))

    def test_this_pcs_own_address_and_the_servers_word_count_as_this_pc(self):
        self.server()
        # A browser on the server PC that opened its address on the network: one of this computer's own addresses.
        with mock.patch.object(this_pc, "own_addresses", lambda: frozenset({HOST})):
            self.assertIn('id="this-pc"', self.page("/app", remote=HOST))
            self.assertNotIn('id="this-pc"', self.page("/app", remote=ELSEWHERE))
        # The same header from a visitor of its own, not through the server: nobody's word (the server sets it no more).
        r = self.inst.client.get(BASE + "/app", environ_base={"REMOTE_ADDR": ELSEWHERE}, headers={"X-Server-PC": "yes"})
        self.assertNotIn('id="this-pc"', r.get_data(as_text=True))

    def through_the_server(self, real_ip, forwarded_for=None, **more):
        """The App page as the server's Apache passes a visit on to these pages (read from the real server image: the
        address it took the visit from as X-Real-IP, added to X-Forwarded-For after any a proxy before it gave, and the
        Host it came with as X-Forwarded-Host), from the server's own address 172.18.0.2."""
        headers = {"X-Real-IP": real_ip, "X-Forwarded-For": forwarded_for or real_ip, "X-Forwarded-Host": "localhost:8791",
                   "X-Forwarded-Server": HOST, "X-Forwarded-Proto": "http", **more}
        return self.inst.client.get(BASE + "/app", environ_base={"REMOTE_ADDR": "172.18.0.2"}, headers=headers).get_data(as_text=True)

    def kind_through_the_server(self, real_ip):
        """What Play on this PC is for a visit the server's Apache passes on as through_the_server() does: "windows",
        "elsewhere" (the server PC of another install) or None (another PC)."""
        headers = {"X-Real-IP": real_ip, "X-Forwarded-For": real_ip, "X-Forwarded-Host": "localhost:8791",
                   "X-Forwarded-Server": HOST, "X-Forwarded-Proto": "http"}
        with admin.app.test_request_context(BASE + "/app", environ_base={"REMOTE_ADDR": "172.18.0.2"}, headers=headers):
            return this_pc.here_kind()

    def test_with_docker_engine_a_visit_from_the_stack_gateway_is_this_pcs(self):
        # Docker Compose on Linux: a browser on the server PC reaches the server from the stack network's gateway, which
        # the server takes for the server PC's (ADMIN_LOCAL=gateway): Play on this PC shows, with how to play from a
        # Windows PC (ADM-177; main waited for a header the server no longer sets, and never showed it there).
        self.server(kind="docker")
        with mock.patch.object(admin.auth, "server_addresses", lambda: {"172.18.0.2"}), \
                mock.patch.object(admin.auth, "stack_gateway", lambda: "172.18.0.1"):
            with mock.patch.dict(os.environ, {"ADMIN_LOCAL": "gateway"}):
                # The server PC's visit counts as the server PC's (the page has no card of how to play from a Windows PC
                # to show it with, ADM-201: the server's own word for the visit says it).
                self.assertEqual(self.kind_through_the_server("172.18.0.1"), "elsewhere")
                # Another address of the network: not the server PC.
                self.assertIsNone(self.kind_through_the_server("192.168.0.50"))
            # Docker Desktop and rootless Docker pass every visit from such an address: none counts there.
            with mock.patch.dict(os.environ, {"ADMIN_LOCAL": "none"}):
                self.assertNotIn('id="this-pc"', self.through_the_server("172.18.0.1"))

    def test_a_visit_a_proxy_on_the_server_pc_passes_on_is_from_elsewhere(self):
        # A reverse proxy or tunnel on the server PC passes on visits from elsewhere from loopback or the gateway: with
        # the hop it adds to X-Forwarded-For before the server's own, or with Forwarded or Via, the visit is not this PC's
        # (ADM-178; main showed Play on this PC through it on a local network address). Headers as the real Apache passes
        # them, the proxy's in front.
        self.server()
        with mock.patch.object(admin.auth, "server_addresses", lambda: {"127.0.0.1"}):
            def host_visit(**headers):
                return self.inst.client.get(BASE + "/app", environ_base={"REMOTE_ADDR": "127.0.0.1"},
                                            headers={"X-Real-IP": "127.0.0.1", "X-Forwarded-For": "127.0.0.1",
                                                     "X-Forwarded-Host": "127.0.0.1:8791", **headers}).get_data(as_text=True)
            # The browser on the server PC, through the server's Apache alone.
            self.assertIn('id="this-pc"', host_visit())
            for headers in ({"X-Forwarded-For": "203.0.113.9, 127.0.0.1"}, {"Via": "1.1 proxy"}, {"Forwarded": "for=203.0.113.9"},
                            {"X-Forwarded-Host": "game.example.com, 127.0.0.1:8791"}):
                self.assertNotIn('id="this-pc"', host_visit(**headers), headers)
            # Pressed all the same: refused in words, nothing run.
            page = self.inst.client.get(BASE + "/app", environ_base={"REMOTE_ADDR": "127.0.0.1"}).get_data(as_text=True)
            csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
            r = self.inst.client.post(BASE + "/app/play-here", data={"csrf": csrf, "back": "app"},
                                      environ_base={"REMOTE_ADDR": "127.0.0.1"},
                                      headers={"X-Real-IP": "127.0.0.1", "X-Forwarded-For": "203.0.113.9, 127.0.0.1"})
            said = self.inst.client.get(r.headers["Location"], environ_base={"REMOTE_ADDR": "127.0.0.1"}).get_data(as_text=True)
            self.assertIn("Play on this PC works from the server PC itself, in its own browser.", said)
            self.assertEqual(self.started, [])
        # Docker Engine: the same through a proxy in front of the gateway.
        self.server(kind="docker")
        with mock.patch.object(admin.auth, "server_addresses", lambda: {"172.18.0.2"}), \
                mock.patch.object(admin.auth, "stack_gateway", lambda: "172.18.0.1"), \
                mock.patch.dict(os.environ, {"ADMIN_LOCAL": "gateway"}):
            self.assertNotIn('id="this-pc"', self.through_the_server("172.18.0.1", "203.0.113.9, 172.18.0.1"))
            self.assertNotIn('id="this-pc"', self.through_the_server("172.18.0.1", Via="1.1 proxy"))

    def test_a_second_press_while_the_first_runs_waits(self):
        self.server()
        self.assertTrue(this_pc._running.acquire(blocking=False))
        try:
            _, said = self.press()
            self.assertIn("Play on this PC is under way already.", said)
        finally:
            this_pc._running.release()

    def test_a_longer_install_is_followed_on_the_page(self):
        # Longer than a form waits: the page follows it in its log box, then says what came of it.
        self.server()
        with mock.patch.object(admin.jobs, "PAGE_WAIT", 0):
            release = __import__("threading").Event()
            slow = Process(self.started, 0)
            slow.wait = lambda timeout=None: (release.wait(10), 0)[1]
            with mock.patch.object(this_pc, "start_program", slow):
                where, said = self.press()
                self.assertRegex(where, r"/app\?here=[0-9a-f]{12}$")
                self.assertIn('id="here-log"', said)
                self.assertRegex(said, r'<button class="btn"[^>]*disabled>Installing…</button>')
                release.set()
                job = where.rsplit("=", 1)[1]
                for _ in range(200):
                    if admin.jobs._jobs[job]["state"] != "running":
                        break
                    time.sleep(0.02)
                said = self.inst.client.get(where).get_data(as_text=True)
                self.assertIn("Installed the PC client.", said)
                self.assertNotIn('id="here-log"', said)

    def test_the_korean_words(self):
        self.server()
        self.inst.client.set_cookie("opendmtq_lang", "ko", path="/")
        shown = self.page("/app")
        self.assertIn("이 서버에 맞춘 PC 클라이언트를 이 PC에 설치하고, 로그인할 아이디(admin)를 채운 채로 엽니다.", shown)
        self.assertRegex(shown, r'>이 PC에서 플레이</button>')


if __name__ == "__main__":
    unittest.main()
