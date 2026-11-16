"""The command line's look (console.py, main.py): in a terminal, a title, parts under their names, names and values in
columns, marks and bars in the launcher's colours; in a pipe the same words as before, for scripts; the console that
Windows opens for a double click on the console copy closed when the window opens."""

import contextlib
import io
import re
import sys
import types
import unittest
from unittest import mock

from opendmtq_client import console, main

# A terminal's colour sequence.
ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


class Terminal(io.StringIO):
    """Standard output as a terminal that shows colours."""

    def isatty(self):
        return True


class Look(unittest.TestCase):
    def setUp(self):
        # Whether this run shows colours is asked again for each test.
        console._colour = None
        self.addCleanup(setattr, console, "_colour", None)

    def test_colours_only_in_a_terminal(self):
        with mock.patch.object(sys, "stdout", Terminal()), mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("NO_COLOR", None)
            os.environ.pop("TERM", None)
            self.assertTrue(console.colour_on())
            painted = console.paint("fine", "ok")
            self.assertIn("\x1b[", painted)
            # The launcher's lime, as 24-bit colour.
            self.assertIn("38;2;140;242;61", painted)
        console._colour = None
        with mock.patch.object(sys, "stdout", io.StringIO()):
            self.assertFalse(console.colour_on())
            self.assertEqual(console.paint("fine", "ok"), "fine")
        console._colour = None
        with mock.patch.object(sys, "stdout", Terminal()), mock.patch.dict("os.environ", {"NO_COLOR": "1"}):
            self.assertFalse(console.colour_on())

    def test_names_and_values_in_two_columns(self):
        console._colour = False
        text = console.rows([("server", "Stand-in (http://192.168.1.10:8080)"), ("signed in", "player1"),
                             ("app", "none on this PC")], indent=2)
        lines = text.splitlines()
        # Every value starts in the same column, past the longest name and two spaces.
        starts = {len(line) - len(line.lstrip(" ")) + len(line.strip().split("  ")[0]) for line in lines}
        values = [line.index(value) for line, value in zip(lines, ("Stand-in", "player1", "none"))]
        self.assertEqual(len(set(values)), 1, text)
        self.assertTrue(all(line.startswith("  ") for line in lines))
        self.assertTrue(starts)

    def test_a_long_value_wraps_under_its_column(self):
        console._colour = False
        with mock.patch.object(console, "width", return_value=40):
            text = console.rows([("settings", " ".join("name%d=value" % i for i in range(8)))])
        lines = text.splitlines()
        self.assertGreater(len(lines), 1)
        column = lines[0].index("name0")
        for line in lines[1:]:
            self.assertEqual(len(line) - len(line.lstrip(" ")), column)
            self.assertLessEqual(len(line), 40 + 12)

    def test_marks_and_the_bar(self):
        console._colour = False
        self.assertEqual(console.mark("ok"), "[ok  ]")
        self.assertEqual(console.mark("todo"), "[todo]")
        self.assertEqual(console.bar(50, 100, "  Downloading", size=10), "  Downloading  #####.....   50%")
        self.assertEqual(console.bar(0, None, "x", size=4), "x  ....    0%")
        console._colour = True
        drawn = ESCAPE.sub("", console.bar(100, 100, "x", size=4))
        self.assertEqual(drawn, "x  \u2588\u2588\u2588\u2588  100%")


class Status(unittest.TestCase):
    """--status in a terminal: its title, its parts by name, the ready check's rows with their marks in one column; in a
    pipe, the lines scripts read, unchanged."""

    def setUp(self):
        console._colour = None
        self.addCleanup(setattr, console, "_colour", None)

    def run_status(self, colour):
        from opendmtq_client import actions, state as st, updates
        state = st.LauncherState()
        checks = [actions.Check("player", True, "the player"), actions.Check("server", False, "no answer", blocks=False),
                  actions.Check("app", False, "Sign in on ONLINE", page="online")]
        out = Terminal() if colour else io.StringIO()
        console._colour = colour
        with mock.patch.object(actions, "readiness", return_value=checks), \
                mock.patch.object(actions, "reach", return_value=False), \
                mock.patch.object(updates, "Look", return_value=types.SimpleNamespace(newer=lambda: None)), \
                mock.patch.object(main, "_log_paths", return_value={"launcher": "C:\\launcher.log", "player": None}), \
                contextlib.redirect_stdout(out):
            main._status(state)
        return out.getvalue()

    def test_in_a_pipe_the_lines_stay_as_scripts_read_them(self):
        said = self.run_status(colour=False)
        self.assertIn("server: none (connect with --server URL)\n", said)
        self.assertIn("  [ok  ] player: the player\n", said)
        self.assertIn("  [warn] server: no answer\n", said)
        self.assertIn("settings: display=fullscreen, ", said)
        self.assertNotIn("\x1b[", said)
        # No title or parts' names in a pipe.
        self.assertNotIn("Ready check", said)

    def test_in_a_terminal_it_is_laid_out(self):
        said = ESCAPE.sub("", self.run_status(colour=True))
        lines = said.splitlines()
        self.assertTrue(lines[0].startswith("OpenDMTQ "), lines[0])
        for part in ("PLAY", "Ready check", "Settings", "Logs"):
            self.assertIn(part, lines)
        # The ready check's marks and names in columns.
        rows = [line for line in lines if line.startswith("  [")]
        self.assertEqual(len(rows), 3, said)
        details = {line.index(detail) for line, detail in zip(rows, ("the player", "no answer", "Sign in"))}
        self.assertEqual(len(details), 1, rows)
        self.assertIn("[todo]", said)
        # The settings as name=value words, no "settings:" prefix, wrapped to the line.
        self.assertTrue(any(line.strip().startswith("display=fullscreen") for line in lines))


class OwnConsole(unittest.TestCase):
    def test_a_double_clicked_console_copy_closes_its_console(self):
        # One program on its console: Windows made it for this start, and it goes; a console shared with a terminal
        # (two programs and more) stays.
        freed = []
        kernel32 = types.SimpleNamespace(GetConsoleProcessList=lambda processes, size: 1,
                                         FreeConsole=lambda: freed.append(True))
        import ctypes
        with mock.patch.object(sys, "platform", "win32"), mock.patch.object(ctypes, "windll",
                                                                             types.SimpleNamespace(kernel32=kernel32),
                                                                             create=True), \
                mock.patch.object(sys, "stdout", io.StringIO()), mock.patch.object(sys, "stderr", io.StringIO()):
            self.assertTrue(main._leave_own_console())
            self.assertIsNone(sys.stdout)
        self.assertEqual(freed, [True])
        kernel32.GetConsoleProcessList = lambda processes, size: 2
        with mock.patch.object(sys, "platform", "win32"), mock.patch.object(ctypes, "windll",
                                                                             types.SimpleNamespace(kernel32=kernel32),
                                                                             create=True), \
                mock.patch.object(sys, "stdout", io.StringIO()):
            self.assertFalse(main._leave_own_console())
        self.assertEqual(freed, [True])


if __name__ == "__main__":
    unittest.main()
