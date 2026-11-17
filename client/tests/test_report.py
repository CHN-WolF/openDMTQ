"""A report for whoever helps (report.py, Help's Save a report and --report): what goes in, and that nothing that names a
person or signs in comes out, wherever it was written."""

import contextlib
import io
import json
import os
import zipfile
from unittest import mock

from opendmtq_client import apps, i18n, player, report
from opendmtq_client import state as st
from tests.base import Folder

# A server as a launcher keeps one, signed in, and a second it knows: every value here must stay out of the report.
SERVER = "http://192.168.1.10:8791"
OTHER = "https://club.example.test:8443"
ACCOUNT, OTHER_ACCOUNT = "sena", "player"
COOKIE = "1999999999.%s.%s" % (ACCOUNT.encode().hex(), "cd" * 32)
API_TOKEN = "odq_0123456789ab_" + "A" * 43
DEVICE = "9f86d081884c7d65"
PACKAGE = "app.example.stand.in"


class Report(Folder):
    def setUp(self):
        super().setUp()
        self.state = st.LauncherState()
        self.state.add_server(OTHER, "Midnight Club", "club.example.test:8443")
        self.state.server(OTHER).update(account=OTHER_ACCOUNT)
        self.state.add_server(SERVER, "Sena's Room", "192.168.1.10:8791")
        self.state.server().update(account=ACCOUNT, cookie=COOKIE, expires=1999999999)
        self.state.save()
        # The test's own folder as the user's home: the user's name is its folder's name.
        home = mock.patch.dict(os.environ, {"HOME": self.home, "USERPROFILE": self.home, "USERNAME": os.path.basename(self.home)})
        home.start()
        self.addCleanup(home.stop)
        # The launcher's log as a day of playing leaves it: the server, the sign-in, the user's folders, an update's
        # address with a key, and the other server's ID where an ID is a word of the log's own too.
        logs = os.path.dirname(st.launcher_log())
        os.makedirs(logs)
        local = os.path.join(self.home, "AppData", "Local")
        with open(st.launcher_log(), "w", encoding="utf-8") as f:
            f.write("\n".join([
                "2026-11-17 09:00:00 INFO MainThread OpenDMTQ 0.11.0 started: --sign-in %s" % ACCOUNT,
                "2026-11-17 09:00:01 INFO sign-in could not sign in to %s as %s: the ID or the password is wrong" % (SERVER, ACCOUNT),
                "2026-11-17 09:00:02 INFO download downloaded the app of %s (1024 bytes)" % SERVER,
                "2026-11-17 09:00:03 INFO MainThread starting %s" % os.path.join(local, "OpenDMTQ.Client", "OpenDMTQ.exe"),
                "2026-11-17 09:00:04 INFO MainThread the player's folder is %s" % os.path.join(local, "OpenDMTQ", "servers",
                                                                                              "192.168.1.10-8791"),
                "2026-11-17 09:00:05 INFO update-look asked https://updates.example.test/feed?token=s3cr3t&os=win",
                "2026-11-17 09:00:06 INFO MainThread a header Cookie: opendmtq_dl=%s" % COOKIE,
                "2026-11-17 09:00:07 INFO MainThread an API token %s" % API_TOKEN,
                "2026-11-17 09:00:08 INFO MainThread the player said: player: FMOD output: 48000 Hz",
                "2026-11-17 09:00:09 INFO MainThread connected to Midnight Club at club.example.test:8443 (%s)" % OTHER,
            ]) + "\n")
        with open(st.launcher_log() + ".1", "w", encoding="utf-8") as f:
            f.write("an older log, signed in as %s on %s\n" % (ACCOUNT, SERVER))
        # The game's folder with this PC's player id, and the game's log: its address, its device id, what was typed.
        game = player.data_folder(PACKAGE)
        os.makedirs(os.path.join(game, "data"))
        with open(os.path.join(game, "data", "android_id"), "w", encoding="utf-8") as f:
            f.write(DEVICE + "\n")
        apps_folder = apps.folder(SERVER)
        os.makedirs(apps_folder)
        with open(os.path.join(apps_folder, apps.DETAILS), "w", encoding="utf-8") as f:
            json.dump({"file": "opendmtq-phone-app-2026.11.09-android-192.168.1.10-8791.apk", "sha256": "0" * 64,
                       "size": 4, "package": PACKAGE}, f)
        with open(os.path.join(apps_folder, "opendmtq-phone-app-2026.11.09-android-192.168.1.10-8791.apk"), "wb") as f:
            f.write(b"PK\x03\x04")
        with open(os.path.join(apps_folder, apps.CONF), "w", encoding="utf-8") as f:
            f.write("package=%s\n" % PACKAGE)
        with open(player.log_path(PACKAGE), "w", encoding="utf-8") as f:
            f.write("old line\n" * 10 + "player: platform login udid=%s at http://192.168.1.10:8791/api\n" % DEVICE
                    + 'player: typed "Sena Kim"\nplayer: live: upload to http://192.168.1.10:8791/live/up?key=abcdef&n=1\n')
        player.write_settings(self.state.values, "ko")

    def make(self, **kw):
        """The report made into the test's folder, and its files as text."""
        path, left = report.make(self.state, path=os.path.join(self.home, "out", "report.zip"),
                                 devices=[{"id": "{0.0.0.00000000}.{aaaa}", "name": "Speakers (made up)", "default": True}],
                                 **kw)
        with zipfile.ZipFile(path) as z:
            return path, left, {name: z.read(name).decode("utf-8") for name in z.namelist()}

    def test_what_goes_in(self):
        path, _left, files = self.make()
        self.assertEqual(sorted(files), ["about.txt", "launcher/launcher.log", "launcher/launcher.log.1", "player/player.log",
                                         "settings/player-settings.txt", "settings/settings.json", "system/displays.txt",
                                         "system/sound.txt"])
        about = files["about.txt"]
        for line in ("launcher: ", "player: ", "Windows: ", "graphics: ", "Left out, each replaced by a word"):
            self.assertIn(line, about)
        self.assertIn("Speakers (made up) (default)", files["system/sound.txt"])
        self.assertIn("language=ko", files["settings/player-settings.txt"])
        # The PC's settings as they are, the server's sign-in out.
        self.assertEqual(json.loads(files["settings/settings.json"])["values"]["volume"], self.state.values["volume"])

    def test_nothing_that_names_a_person_or_signs_in_comes_out(self):
        _path, left, files = self.make()
        everything = "\n".join(files.values())
        for private in (SERVER, "192.168.1.10", "192.168.1.10-8791", OTHER, "club.example.test", "Sena's Room",
                        "Midnight Club", COOKIE, API_TOKEN, "s3cr3t", "abcdef", DEVICE, "Sena Kim",
                        os.path.basename(self.home), "as " + ACCOUNT, "--sign-in " + ACCOUNT, '"account": "player"'):
            self.assertNotIn(private, everything, private)
        # Each in its place, by the word for it: the log reads as before.
        log = files["launcher/launcher.log"]
        self.assertIn("could not sign in to <server> as <account>: the ID or the password is wrong", log)
        self.assertIn("started: --sign-in <account>", log)
        self.assertIn(os.path.join(os.path.dirname(self.home), "<user>", "AppData", "Local", "OpenDMTQ.Client"), log)
        self.assertIn(os.path.join("servers", "<server>"), log)
        self.assertIn("?token=<token>&os=win", log)
        self.assertIn("opendmtq_dl=<cookie>", log)
        self.assertIn("connected to <server name> at <server> (<server>)", log)
        game = files["player/player.log"]
        self.assertIn("udid=<device id> at <server>/api", game)
        self.assertIn('typed "<typed>"', game)
        self.assertIn("key=<token>&n=1", game)
        # An ID that is a word of the logs' own is left out only where an ID is written: "player:" stays.
        self.assertIn("player: FMOD output", log)
        # The settings' servers in their order: the other one first, then the one signed in, its cookie out.
        other, server = json.loads(files["settings/settings.json"])["servers"]
        self.assertEqual((server["url"], server["account"], server["cookie"], server["expires"], server["name"]),
                         ("<server>", "<account>", "<cookie>", "<cookie>", "<server name>"))
        self.assertEqual((other["url"], other["account"], other["cookie"]), ("<server>", "<account>", None))
        # What was left out, kind by kind, as the window and --report say it.
        self.assertEqual([kind for kind, _n in left], ["user", "account", "server", "server_name", "cookie", "token",
                                                        "device", "typed"])
        self.assertIn("<device id> device: ", files["about.txt"])
        self.assertEqual(report.left_words(i18n.Words("en"), left[:3]),
                         "your Windows user name in paths, your site ID, the servers' addresses")
        self.assertEqual(report.left_words(i18n.Words("ko"), left[:3]), "경로 속 Windows 사용자 이름, 사이트 아이디, 서버 주소")
        self.assertEqual(report.left_words(i18n.Words("en"), []), "nothing of the kind was found")

    def test_only_the_end_of_a_long_game_log(self):
        with open(player.log_path(PACKAGE), "w", encoding="utf-8") as f:
            f.write("an old game's line\n" * 60000 + "the last game's line\n")
        _path, _left, files = self.make()
        game = files["player/player.log"]
        self.assertLessEqual(len(game.encode()), report.PLAYER_LOG_TAIL)
        self.assertTrue(game.endswith("the last game's line\n"))
        # From a line's start: no half line at its top.
        self.assertTrue(game.startswith("an old game's line\n"))

    def test_written_whole_or_not_at_all(self):
        with mock.patch.object(zipfile.ZipFile, "writestr", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(OSError):
                self.make()
        self.assertEqual(os.listdir(os.path.join(self.home, "out")), [])

    def test_its_name_says_what_it_is_and_when_in_lower_case(self):
        name = os.path.basename(report.default_path(now=1795400000))
        self.assertRegex(name, r"^opendmtq-report-\d{8}-\d{6}\.zip$")
        self.assertEqual(name, name.lower())

    def test_without_an_app_or_a_server_it_still_says_what_there_is(self):
        self.state = st.LauncherState()
        path, left, files = self.make()
        self.assertNotIn("player/player.log", files)
        self.assertIn("about.txt", files)
        self.assertIsInstance(left, list)
        self.assertTrue(os.path.isfile(path))

    def run_main(self, args):
        """main() with these arguments; (exit code, what it printed)."""
        from opendmtq_client import main
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = main.main(args)
        return code, out.getvalue()

    def test_the_command_line(self):
        # A folder: the report's own name in it.
        os.makedirs(os.path.join(self.home, "out"))
        code, said = self.run_main(["--report", os.path.join(self.home, "out")])
        self.assertEqual(code, 0, said)
        made = os.listdir(os.path.join(self.home, "out"))
        self.assertEqual(len(made), 1)
        self.assertRegex(made[0], r"^opendmtq-report-\d{8}-\d{6}\.zip$")
        self.assertIn("Saved the report: %s" % os.path.join(self.home, "out", made[0]), said)
        self.assertIn("Left out: your Windows user name in paths, your site ID, the servers' addresses", said)
        # A file named: that file, a zip by its name too.
        code, said = self.run_main(["--report", os.path.join(self.home, "mine.zip")])
        self.assertEqual(code, 0, said)
        self.assertTrue(zipfile.is_zipfile(os.path.join(self.home, "mine.zip")))
        code, said = self.run_main(["--report", os.path.join(self.home, "problem")])
        self.assertTrue(zipfile.is_zipfile(os.path.join(self.home, "problem.zip")), said)
        # Allowed while the window is open: it changes nothing the window keeps.
        with mock.patch("opendmtq_client.main.window_open", lambda: True):
            code, said = self.run_main(["--report", os.path.join(self.home, "again.zip")])
        self.assertEqual(code, 0, said)
        self.assertNotIn("window is open", said)
        # In --help, with the jobs of help and upkeep.
        with self.assertRaises(SystemExit):
            self.run_main(["--help"])
