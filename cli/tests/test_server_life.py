"""The server's life on the command line, as the admin pages' Server page names it: with Docker Compose ./opendmtq
delete-data, repair and uninstall (cli/opendmtq_cli/app.py), and the host install's own removal of itself
(host/opendmtq_host/remove.py), which its uninstall and the Server page's Uninstall both use."""

import importlib
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from opendmtq_cli import app

from .sandbox import Sandbox, done

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DeleteDataTest(unittest.TestCase):
    """./opendmtq delete-data (SRV-48)."""

    def sizes(self, args, env):
        """The tools container's count of the parts, as opendmtq_tools.server_data prints it."""
        return done(0, json.dumps({p: {"bytes": 1048576, "can_delete": True} for p in app.DATA_PARTS}) + "\n")

    def test_without_parts_it_lists_them_with_their_size(self):
        with Sandbox() as sb:
            sb.tools["server_data"] = self.sizes
            self.assertEqual(sb.call(app.cmd_delete_data, parts=[], yes=False, no_backup=False), 0, sb.output())
            for part in app.DATA_PARTS:
                self.assertIn(part, sb.output())
            self.assertIn("1.0 MB", sb.output())
            self.assertEqual([c[1] for c in sb.tool_calls], [("sizes",)])

    def test_a_part_there_is_not_is_refused(self):
        with Sandbox() as sb:
            self.assertEqual(sb.call(app.cmd_delete_data, parts=["everything"], yes=True, no_backup=False), 1)
            self.assertIn("no such part: everything", sb.output())
            self.assertEqual(sb.tool_calls, [])

    def test_without_a_terminal_to_answer_nothing_goes(self):
        with Sandbox() as sb:
            self.assertEqual(sb.call(app.cmd_delete_data, parts=["logs"], yes=False, no_backup=False), 1)
            self.assertIn("--yes", sb.output())
            self.assertEqual(sb.tool_calls, [])

    def test_a_backup_first_kept_then_the_parts_in_the_tools_container(self):
        with Sandbox() as sb:
            sb.write("data/state/dmtq.db3", b"db")
            self.assertEqual(sb.call(app.cmd_delete_data, parts=["logs", "apps"], yes=True, no_backup=False), 0, sb.output())
            made = sb.backups()
            self.assertEqual(len(made), 1)
            self.assertIn("before-delete", made[0])
            module, args, env = sb.tool_calls[0]
            self.assertEqual((module, args), ("server_data", ("delete", "logs", "apps", "--keep", made[0])))
            # Where the tools container sees the data (compose.yaml, service tools).
            self.assertEqual(env["OPENDMTQ_DB"], "/data/state/dmtq.db3")
            self.assertEqual(env["OPENDMTQ_CONTENT"], "/data/content")
            self.assertIn("deleted: logs, apps", sb.output())


class RepairTest(unittest.TestCase):
    """./opendmtq repair (SRV-49)."""

    def test_the_images_the_data_and_every_part_again(self):
        with Sandbox("PUBLIC_HOST=192.168.0.10\nADMIN_PASSWORD=pw\n") as sb:
            # No git here: the program's files are not looked at.
            sb.programs[("git", "-C")] = done(128)
            self.assertEqual(sb.call(app.cmd_repair), 0, sb.output())
            module, args, env = next(c for c in sb.tool_calls if c[0] == "repair")
            self.assertEqual(env["OPENDMTQ_DB"], "/data/state/dmtq.db3")
            self.assertEqual(env["ADMIN_PASSWORD"], "pw")
            self.assertIn(("up", "-d", "--force-recreate", "server", "admin", "edge"), sb.compose_calls)
            self.assertIn(("up", "-d", "builder"), sb.compose_calls)
            self.assertIn("the server runs again", sb.output())

    def test_changed_program_files_are_named(self):
        with Sandbox("PUBLIC_HOST=192.168.0.10\nADMIN_PASSWORD=pw\n") as sb:
            sb.programs[("git", "-C")] = done(0, " M server/portal/login.php\n")
            self.assertEqual(sb.call(app.cmd_repair), 0, sb.output())
            self.assertIn("files changed from this folder's commit: server/portal/login.php", sb.output())


class UninstallTest(unittest.TestCase):
    """./opendmtq uninstall (DEP-49)."""

    def server(self, sb):
        """The copy of OpenDMTQ inside the sandbox that is uninstalled: its program, its data and .env."""
        root = os.path.join(sb.root, "OpenDMTQ")
        for rel in ("opendmtq", "compose.yaml", "cli/opendmtq_cli/app.py", "data/state/dmtq.db3", ".env"):
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("x")
        sb.programs[("docker", "image", "rm")] = done(0)
        return root, mock.patch.multiple(app, ROOT=root, DATA=os.path.join(root, "data"))

    def test_without_a_terminal_to_answer_nothing_goes(self):
        with Sandbox() as sb:
            root, paths = self.server(sb)
            with paths:
                self.assertEqual(sb.call(app.cmd_uninstall, keep_data=False, yes=False), 1)
            self.assertTrue(os.path.isfile(os.path.join(root, "opendmtq")))
            self.assertEqual(sb.compose_calls, [])

    def test_keeping_the_data_the_folder_keeps_data_and_env(self):
        with Sandbox() as sb:
            root, paths = self.server(sb)
            with paths:
                self.assertEqual(sb.call(app.cmd_uninstall, keep_data=True, yes=True), 0, sb.output())
            self.assertEqual(sorted(os.listdir(root)), [".env", "data"])
            self.assertTrue(os.path.isfile(os.path.join(root, "data", "state", "dmtq.db3")))
            self.assertIn(("--profile", "tools", "down", "--volumes", "--remove-orphans"), sb.compose_calls)
            self.assertIn("removed the image", sb.output())

    def test_whole_the_folder_goes(self):
        with Sandbox() as sb:
            root, paths = self.server(sb)
            with paths:
                self.assertEqual(sb.call(app.cmd_uninstall, keep_data=False, yes=True), 0, sb.output())
            self.assertFalse(os.path.exists(root))

    def test_under_wsl_a_firewall_rule_that_is_not_there_asks_windows_nothing(self):
        with Sandbox(wsl=True) as sb:
            sb.windows_reachable()
            root, paths = self.server(sb)
            with paths:
                self.assertEqual(sb.call(app.cmd_uninstall, keep_data=True, yes=True), 0, sb.output())
            # Only the look, without administrator rights: no elevated PowerShell.
            self.assertTrue(sb.scripts)
            self.assertFalse([s for s in sb.scripts if "RunAs" in s])


class HostRemoveTest(unittest.TestCase):
    """host/opendmtq_host/remove.py: the host install's removal of itself (DEP-48)."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(REPO, "host"))
        cls.remove = importlib.import_module("opendmtq_host.remove")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, "OpenDMTQ")
        for rel in ("opendmtq", "host/opendmtq_host/cli.py", ".host/venv/bin/python", "data/state/dmtq.db3", ".env"):
            path = os.path.join(self.root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("x")
        self.paths = mock.patch.multiple(self.remove, ROOT=self.root, WINDOWS=False, MAC=False)
        self.paths.start()

    def tearDown(self):
        self.paths.stop()
        self._tmp.cleanup()

    def test_keeping_the_data(self):
        with mock.patch("builtins.print"):
            self.remove.remove_folder(True)
        self.assertEqual(sorted(os.listdir(self.root)), [".env", "data"])

    def test_whole(self):
        with mock.patch("builtins.print"):
            self.remove.remove_folder(False)
        self.assertFalse(os.path.exists(self.root))

    def test_the_command_on_the_path_when_it_is_this_folders(self):
        home = os.path.join(self._tmp.name, "home")
        os.makedirs(os.path.join(home, ".local", "bin"))
        mine = os.path.join(home, ".local", "bin", "opendmtq")
        os.symlink(os.path.join(self.root, "opendmtq"), mine)
        with mock.patch.dict(os.environ, {"HOME": home}), mock.patch("builtins.print"):
            self.remove.remove_link()
        self.assertFalse(os.path.lexists(mine))
        # Another install's stays.
        os.symlink("/opt/other/opendmtq", mine)
        with mock.patch.dict(os.environ, {"HOME": home}), mock.patch("builtins.print"):
            self.remove.remove_link()
        self.assertTrue(os.path.lexists(mine))

    def test_the_windows_script_waits_and_keeps_what_is_kept(self):
        whole = self.remove.remover_script(r"C:\Users\someone\Desktop\OpenDMTQ", False)
        self.assertIn('set "D=C:\\Users\\someone\\Desktop\\OpenDMTQ"', whole)
        self.assertIn('rd /s /q "%D%"', whole)
        # Two seconds between tries, two minutes at most, then the script itself.
        self.assertIn("ping -n 3 127.0.0.1 >nul", whole)
        self.assertIn("if %N% GEQ 60 goto done", whole)
        self.assertIn('del /f /q "%~f0"', whole)
        self.assertTrue(whole.endswith("\r\n"))
        kept = self.remove.remover_script(r"C:\OpenDMTQ", True)
        self.assertIn('if /i not "%%~nxi"=="data" rd /s /q "%%i"', kept)
        self.assertIn('if /i not "%%~nxi"==".env" del /f /q "%%i"', kept)
        self.assertNotIn('rd /s /q "%D%"', kept)


if __name__ == "__main__":
    unittest.main()
