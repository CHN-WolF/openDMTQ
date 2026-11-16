"""Tests for how the command line looks: the wordmark, the state colours and the aligned lines on a terminal, plain text
in a pipe, a log or with NO_COLOR, for ./opendmtq and the host install's window alike."""

import io
import logging
import os
import re
import sys
import types
import unittest
from unittest import mock

from opendmtq_cli import look

# The repository: the host program is beside the command line in it.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# An ANSI colour or style code.
CODE = re.compile(r"\033\[[0-9;]*m")


def terminal():
    """A stream that is a terminal: the writing end of a pseudo-terminal, as a text file."""
    leader, follower = os.openpty()
    # The reading end is not read: the lines are small and the pseudo-terminal holds them.
    stream = io.TextIOWrapper(io.FileIO(follower, "w"), encoding="utf-8", write_through=True)
    stream.leader = leader
    return stream


def close(stream):
    """Both ends of a terminal() closed."""
    stream.close()
    os.close(stream.leader)


def plain(text):
    """text without its colour codes."""
    return CODE.sub("", text)


class LookTest(unittest.TestCase):
    def setUp(self):
        # Each test decides afresh, with a terminal's usual settings and no NO_COLOR.
        look._decided.clear()
        patcher = mock.patch.dict(os.environ, {"TERM": "xterm-256color"})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("NO_COLOR", None)

    def test_colour_on_a_terminal(self):
        tty = terminal()
        try:
            line = look.state_line("ok", "server up", tty)
            self.assertRegex(line, CODE)
            self.assertEqual(plain(line), "  ok    server up")
            self.assertRegex(look.state_line("error", "no", tty), CODE)
        finally:
            close(tty)

    def test_no_colour_with_no_color(self):
        tty = terminal()
        try:
            with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
                self.assertNotRegex(look.state_line("ok", "server up", tty), CODE)
                # The wordmark is still drawn: it is a terminal, only without colour.
                self.assertIn("█", "\n".join(look.wordmark("0.11.0", tty)))
                self.assertNotRegex("\n".join(look.wordmark("0.11.0", tty)), CODE)
        finally:
            close(tty)

    def test_no_colour_with_a_dumb_terminal(self):
        tty = terminal()
        try:
            with mock.patch.dict(os.environ, {"TERM": "dumb"}):
                self.assertNotRegex(look.state_line("note", "x", tty), CODE)
        finally:
            close(tty)

    def test_windows_console_turned_to_colour_but_not_wines(self):
        # Windows' console draws the codes once its virtual terminal is on; Wine's takes the setting and prints them as
        # text, so there the window stays plain.
        def windows(wine):
            set_to = []
            ntdll = types.SimpleNamespace(wine_get_version=lambda: "11.0") if wine else types.SimpleNamespace()
            kernel32 = types.SimpleNamespace(GetConsoleMode=lambda handle, mode: 1,
                                             SetConsoleMode=lambda handle, mode: set_to.append(mode) or 1)
            fake = types.SimpleNamespace(windll=types.SimpleNamespace(ntdll=ntdll, kernel32=kernel32),
                                         c_uint32=lambda: types.SimpleNamespace(value=3), byref=lambda x: x)
            with mock.patch.dict(sys.modules, {"ctypes": fake, "msvcrt": types.SimpleNamespace(get_osfhandle=lambda fd: 7)}):
                return look._windows_vt(types.SimpleNamespace(fileno=lambda: 1)), set_to
        self.assertEqual(windows(wine=False), (True, [3 | 4]))
        self.assertEqual(windows(wine=True), (False, []))

    def test_plain_in_a_pipe(self):
        out = io.StringIO()
        self.assertEqual(look.state_line("ok", "server up", out), "  ok    server up")
        # One plain line for the name and the version, nothing drawn.
        self.assertEqual(look.wordmark("0.11.0", out), ["OpenDMTQ 0.11.0"])
        self.assertEqual(look.para("A long sentence " * 20, out), ["A long sentence " * 20])
        self.assertTrue(all(not CODE.search(line) for line in look.address_block("http://a/", "http://a/opendmtq/admin/",
                                                                                 "admin", where="in .env", stream=out)))

    def test_the_wordmark_on_a_terminal(self):
        tty = terminal()
        try:
            lines = [plain(line) for line in look.wordmark("0.11.0", tty)]
            # OPEN with its line, then the four rows of DMTQ, the version beside the last.
            self.assertEqual(len(lines), 5)
            self.assertIn("O P E N", lines[0])
            self.assertTrue(lines[-1].rstrip().endswith("v0.11.0"))
            # The lean: each row starts one column left of the one above.
            starts = [len(line) - len(line.lstrip()) for line in lines[1:]]
            self.assertEqual(starts, [starts[0] - i for i in range(4)])
            # The OPEN line ends where the letters' top row does.
            self.assertEqual(len(lines[0]), len(lines[1]))
            # The Q in lime: its colour (the product's #8cf23d) is in the drawing.
            with mock.patch.dict(os.environ, {"COLORTERM": "truecolor"}):
                self.assertIn("38;2;140;242;61", "".join(look.wordmark("0.11.0", tty)))
        finally:
            close(tty)

    def test_the_wordmark_once_per_run(self):
        out = io.StringIO()
        with mock.patch.object(look, "_shown", []):
            look.banner("0.11.0", out)
            look.banner("0.11.0", out)
        self.assertEqual(out.getvalue().count("OpenDMTQ"), 1)

    def test_values_in_one_column(self):
        tty = terminal()
        try:
            for stream in (tty, io.StringIO()):
                lines = [plain(line) for line in look.rows([("Server", ("running", "ok")), ("Admin pages", "http://a/"),
                                                           ("Songs", "128")], stream)]
                # Every value starts in the same column, after the longest label and two spaces.
                columns = {line.index(value) for line, value in zip(lines, ("running", "http://a/", "128"))}
                self.assertEqual(columns, {len(look.INDENT) + len("Admin pages") + 2})
        finally:
            close(tty)

    def test_the_address_block(self):
        tty = terminal()
        try:
            lines = [plain(line) for line in look.address_block("http://192.168.1.10:8791/",
                                                                "http://192.168.1.10:8791/opendmtq/admin/", "admin",
                                                                where="ADMIN_PASSWORD in .env", stream=tty)]
            text = "\n".join(lines)
            for words in ("Players' site", "http://192.168.1.10:8791/opendmtq/admin/", "Admin ID", "admin",
                          "ADMIN_PASSWORD in .env"):
                self.assertIn(words, text)
            # Framed by a heading line and a closing line.
            self.assertIn("─", lines[0])
            self.assertTrue(set(lines[-1].strip()) == {"─"})
        finally:
            close(tty)

    def test_log_lines(self):
        record = logging.LogRecord("x", logging.WARNING, __file__, 1, "still waiting", None, None)
        tty = terminal()
        try:
            # In the window: the time and a note word, coloured.
            shown = look.ConsoleFormatter(tty).format(record)
            self.assertRegex(shown, CODE)
            self.assertRegex(plain(shown), r"^  \d\d:\d\d:\d\d  note  still waiting$")
        finally:
            close(tty)
        # In a pipe: the date and the time, plain, as the log file has them.
        self.assertRegex(look.ConsoleFormatter(io.StringIO()).format(record), r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d still waiting$")

    def test_the_host_window_uses_it(self):
        # The host install's own messages (the Windows window): the same state words, in colour on a terminal.
        sys.path.insert(0, os.path.join(ROOT, "host"))
        try:
            from opendmtq_host import output
        finally:
            sys.path.pop(0)
        tty = terminal()
        try:
            with mock.patch.object(sys, "stdout", tty), mock.patch("builtins.print") as said:
                output.ok("server up")
                output.warn("slow")
            shown = [call.args[0] for call in said.call_args_list]
            self.assertTrue(all(CODE.search(line) for line in shown), shown)
            self.assertEqual([plain(line) for line in shown], ["  ok    server up", "  note  slow"])
        finally:
            close(tty)


if __name__ == "__main__":
    unittest.main()
