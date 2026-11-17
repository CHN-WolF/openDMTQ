"""The connection test (connection.py, Online's Test connection, --test-server): each step against a stand-in for what a
player meets, a server that works, a port nobody listens on, another service there, an OpenDMTQ too old, a sign-in that
ended, a certificate this PC does not trust, a server that moved to 8791; and the command line's twin."""

import contextlib
import io
import os
import socket
import socketserver
import threading
from unittest import mock

from opendmtq_client import connection, i18n, main
from opendmtq_client import server as srv
from opendmtq_client import state as st
from tests import stub
from tests.base import Folder

EN, KO = i18n.Words("en"), i18n.Words("ko")


def closed_port():
    """A port of this machine that nothing listens on (taken a moment, then given back)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Other(socketserver.ThreadingTCPServer):
    """Another service on a port: it answers anything with a line that is no HTTP, as a mail or a shell server does."""

    allow_reuse_address = True

    def __init__(self):
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.sendall(b"SSH-2.0-OpenSSH_9.6\r\n")

        super().__init__(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.serve_forever, kwargs={"poll_interval": stub.POLL}, daemon=True).start()


class ConnectionTest(Folder):
    def setUp(self):
        super().setUp()
        self.site = stub.Site().start()
        self.state = st.LauncherState()
        self.state.add_server(self.site.url, "Stand-in")

    def tearDown(self):
        self.site.stop()
        super().tearDown()

    def run_test(self, address=None, signed=True):
        """The test of `address` (the stand-in's by default), with the launcher's sign-in to it or none: (the result,
        its steps by key, the steps as they were told)."""
        if signed:
            from opendmtq_client import actions
            actions.sign_in(self.state, stub.ACCOUNT, stub.PASSWORD)
        told = []
        result = connection.run(address or self.site.url, self.state.server(address or self.site.url), report=told.append)
        return result, {s.key: s for s in result.steps}, told

    def said(self, step, words=EN):
        return words.say(step.said)

    def test_a_server_that_works(self):
        result, steps, told = self.run_test()
        self.assertEqual([s.key for s in told], list(connection.STEPS))
        self.assertEqual({k: s.state for k, s in steps.items()},
                         dict.fromkeys(connection.STEPS, "ok") | {"version": "warn"})
        self.assertFalse(result.failed())
        host, port = srv.host_port(self.site.url)
        self.assertEqual(self.said(steps["address"]), "%s: http, host 127.0.0.1, port %d." % (self.site.url, port))
        self.assertEqual(self.said(steps["lookup"]), "127.0.0.1 is an address: nothing to look up.")
        self.assertEqual(self.said(steps["port"]), "Port %d of 127.0.0.1 takes the connection." % port)
        self.assertEqual(self.said(steps["server"]), "Stand-in, OpenDMTQ 0.8.0.")
        self.assertEqual(self.said(steps["signin"]), "Signed in as player1 until 2033-05-18.")
        self.assertEqual(self.said(steps["game"]), "The game server answers: patch 1.003.005.")
        self.assertEqual(self.said(steps["broadcasts"]), "Broadcasts are off for the server.")
        self.assertRegex(self.said(steps["downloads"]),
                         r"^The app \(0\.1 MB\) and the client data's list \(3 KB\) are there to download\.$")
        self.assertRegex(self.said(steps["round_trip"]), r"^5 of 5 asks answered: \d+ ms in the middle, from \d+ to \d+ ms\.$")
        # Heads alone for the downloads: nothing downloaded whole.
        self.assertNotIn(("GET", "/apk", self.site.cookie), self.site.requests)
        self.assertIn(("HEAD", "/apk", self.site.cookie), self.site.requests)
        # The version: the launcher's own against the server's, said with both.
        self.assertIn("The server runs 0.8.0", self.said(steps["version"]))
        # The verdict: the server answers, and the first thing not as it should be.
        self.assertTrue(EN.say(result.verdict()).startswith("The server answers. Version: The server runs 0.8.0"))
        # Each step's time, the copy's text with every step, in both languages.
        self.assertTrue(all(s.ms is not None for s in result.steps))
        text = result.text(EN)
        self.assertIn("Connection test of %s" % self.site.url, text)
        self.assertEqual(len(text.splitlines()), 2 + len(connection.STEPS))
        self.assertIn("게임 서버가 답합니다(패치 1.003.005).", result.text(KO))

    def test_the_same_version_and_broadcasts_on(self):
        from opendmtq_client import __version__
        self.site.version, self.site.broadcasts = __version__, True
        result, steps, _ = self.run_test()
        self.assertEqual(steps["version"].state, "ok")
        self.assertEqual(self.said(steps["broadcasts"]), "Broadcasts are on for the server.")
        self.assertEqual(EN.say(result.verdict()), "The server answers, and so does everything the game uses.")
        self.assertEqual(KO.say(result.verdict()), "서버도, 게임이 쓰는 것도 모두 답합니다.")

    def test_a_port_nobody_listens_on(self):
        port, probed = closed_port(), (closed_port(),)
        with mock.patch.object(connection, "PORTS", probed):
            result, steps, _ = self.run_test("http://127.0.0.1:%d" % port, signed=False)
        self.assertEqual(steps["port"].state, "bad")
        self.assertEqual(self.said(steps["port"]),
                         "127.0.0.1 refuses the connection on port %d, and no OpenDMTQ server answers on ports %d to %d "
                         "either." % (port, probed[0], probed[-1]))
        # What comes after a port that does not answer is not tried, and says so.
        self.assertEqual([steps[k].state for k in connection.STEPS[3:]], ["skip"] * 7)
        self.assertEqual(self.said(steps["round_trip"]), "Not tried: a step before it did not get through.")
        self.assertTrue(result.failed())
        self.assertIsNone(result.moved)

    def test_a_server_moved_to_8791_is_found(self):
        # A launcher set up for port 80 of a server updated to 0.11.0, which moved to 8791 (here the stand-in's port, among
        # the ports a new server takes).
        host, port = srv.host_port(self.site.url)
        old = closed_port()
        with mock.patch.object(connection, "PORTS", (closed_port(), port)):
            result, steps, _ = self.run_test("http://127.0.0.1:%d" % old, signed=False)
        self.assertEqual(result.moved, self.site.url)
        self.assertEqual(self.said(steps["port"]), "127.0.0.1 refuses the connection on port %d. An OpenDMTQ server "
                                                   "answers at %s." % (old, self.site.url))
        self.assertEqual(EN.say(result.verdict()), "Nothing answers at http://127.0.0.1:%d. An OpenDMTQ server answers at "
                                                   "%s." % (old, self.site.url))
        self.assertEqual(KO.say(result.verdict()), "http://127.0.0.1:%d에서는 답이 없고, %s에서 OpenDMTQ 서버가 답합니다."
                         % (old, self.site.url))
        # The ports a new server takes: 8791 and the next ones, never 80.
        self.assertEqual(connection.PORTS, tuple(range(8791, 8800)))

    def test_moving_to_the_server_found_keeps_the_sign_in(self):
        from opendmtq_client import actions, apps
        # A launcher that knows the server at its old address alone, signed in there.
        old = "http://127.0.0.1:%d" % closed_port()
        self.state = st.LauncherState()
        self.state.add_server(old, "Stand-in")
        self.state.server(old).update(account=stub.ACCOUNT, cookie=self.site.cookie, expires=1999999999)
        os.makedirs(apps.folder(old))
        actions.move_server(self.state, old, self.site.url)
        self.assertEqual(self.state.current, self.site.url)
        self.assertTrue(self.state.signed_in())
        self.assertEqual(self.state.server()["account"], stub.ACCOUNT)
        # Its app was built for the old address: it goes.
        self.assertFalse(os.path.exists(apps.folder(old)))
        self.assertEqual([s["url"] for s in self.state.servers], [self.site.url])

    def test_another_service_on_the_port(self):
        other = Other()
        try:
            result, steps, _ = self.run_test("http://127.0.0.1:%d" % other.server_address[1], signed=False)
        finally:
            other.shutdown()
            other.server_close()
        self.assertEqual(steps["port"].state, "ok")
        self.assertEqual((steps["server"].state, self.said(steps["server"])),
                         ("bad", "Something answers on the port, and it is no OpenDMTQ server for PCs."))
        self.assertTrue(result.failed())

    def test_an_opendmtq_too_old_for_pcs(self):
        self.site.old = True
        result, steps, _ = self.run_test(signed=False)
        self.assertEqual(self.said(steps["server"]), "An OpenDMTQ older than 0.8 answers, without the part for PCs.")
        self.assertEqual(steps["version"].state, "skip")

    def test_a_sign_in_that_ended(self):
        from opendmtq_client import actions
        actions.sign_in(self.state, stub.ACCOUNT, stub.PASSWORD)
        self.site.signed_cookies.clear()
        result, steps, _ = self.run_test(signed=False)
        self.assertEqual(steps["signin"].state, "bad")
        self.assertEqual(self.said(steps["signin"]), "The server no longer takes the sign-in of player1.")
        self.assertEqual(self.said(steps["signin"], KO), "서버가 player1 계정의 로그인을 더 이상 받지 않습니다.")
        # Nothing of the launcher's is changed by a test: the sign-in it keeps stays until the window's own look.
        self.assertEqual(self.state.server()["cookie"], self.site.cookie)
        # Not signed in at all: said, and the app's download waits for one.
        self.state.forget_sign_in()
        result, steps, _ = self.run_test(signed=False)
        self.assertEqual((steps["signin"].state, self.said(steps["signin"])), ("warn", "Not signed in to this server on this PC."))
        self.assertEqual(self.said(steps["downloads"]), "The client data's list (3 KB) is there to download; the app "
                                                        "downloads after a sign-in.")

    def test_the_game_under_maintenance_and_down(self):
        self.site.health = {"ok": True, "patch": "1.003.005", "maintenance": True}
        _, steps, _ = self.run_test()
        self.assertEqual((steps["game"].state, self.said(steps["game"])),
                         ("warn", "The game server answers, under maintenance: patch 1.003.005."))
        self.site.health = {"ok": False, "patch": "1.003.005", "maintenance": False, "problem": "no client data"}
        _, steps, _ = self.run_test()
        self.assertEqual(self.said(steps["game"]), "The game server answers that it cannot serve the game: no client data.")

    def test_not_an_address_and_a_name_that_leads_nowhere(self):
        result, steps, _ = self.run_test("not an address", signed=False)
        self.assertEqual(self.said(steps["address"]), "not an address is not an address.")
        self.assertEqual(steps["lookup"].state, "skip")
        with mock.patch.object(socket, "getaddrinfo", side_effect=socket.gaierror(-2, "Name or service not known")):
            result, steps, _ = self.run_test("http://no-such-server.example:8791", signed=False)
        self.assertEqual(self.said(steps["lookup"]),
                         "no-such-server.example leads to no address ([Errno -2] Name or service not known).")
        self.assertEqual(self.said(steps["lookup"], KO),
                         "no-such-server.example에 해당하는 주소가 없습니다([Errno -2] Name or service not known).")

    def test_the_last_result_is_kept_for_the_report(self):
        result, _, _ = self.run_test()
        kept = connection.last()
        self.assertEqual(kept.url, self.site.url)
        self.assertEqual(kept.text(EN), result.text(EN))
        from opendmtq_client import report
        path, _left = report.make(self.state, path=os.path.join(self.home, "r.zip"), devices=[])
        import zipfile
        with zipfile.ZipFile(path) as z:
            kept_text = z.read("system/connection-test.txt").decode()
        # In the report, the server's address left out as everywhere.
        self.assertIn("Connection test of <server>", kept_text)
        self.assertIn("[ok  ] Game server", kept_text)

    def test_the_command_line(self):
        def run_main(args):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = main.main(args)
            return code, out.getvalue()

        self.state.save()
        code, said = run_main(["--test-server"])
        self.assertEqual(code, 0, said)
        for line in ("[ok  ] Address: %s: http" % self.site.url, "[ok  ] Game server: The game server answers: patch 1.003.005.",
                     "[warn] Sign-in: Not signed in to this server on this PC."):
            self.assertIn(line, said)
        # A port nobody listens on: the steps after it skipped, the exit code 1.
        with mock.patch.object(connection, "PORTS", (closed_port(),)):
            code, said = run_main(["--test-server", "127.0.0.1:%d" % closed_port()])
        self.assertEqual(code, 1, said)
        self.assertIn("[skip] Round trip: Not tried", said)
        self.assertIn("[fail] Port: 127.0.0.1 refuses the connection", said)
        # No server known and none given: said, 2.
        st.LauncherState().save()
        code, said = run_main(["--test-server"])
        self.assertEqual(code, 2)
        self.assertIn("No server to test", said)


class Certificate(Folder):
    """Over HTTPS: the server's own authority trusted for it alone, or a certificate this PC does not trust."""

    def setUp(self):
        super().setUp()
        from tests.test_server import OwnAuthority
        self.https = OwnAuthority("test_its_own_authority_is_trusted_for_it")
        self.https.setUp()

    def tearDown(self):
        self.https.tearDown()
        super().tearDown()

    def test_a_certificate_this_pc_does_not_trust(self):
        result = connection.run(self.https.base, None)
        step = result.step("server")
        self.assertEqual((step.state, step.said.key), ("bad", "test.server.certificate"))
        self.assertIn("This PC does not trust the certificate the server answers HTTPS with", EN.say(step.said))
        self.assertIn("CERTIFICATE_VERIFY_FAILED", EN.say(step.said))

    def test_the_servers_own_authority(self):
        srv.trust(self.https.base, self.https.authority(self.https.mine))
        result = connection.run(self.https.base, None)
        self.assertEqual(EN.say(result.step("server").said), "Over HTTPS, OpenDMTQ 0.8.0, over HTTPS with the server's own "
                                                             "certificate, trusted for this server alone.")
