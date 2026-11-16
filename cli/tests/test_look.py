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

    def test_sentences_wrap_on_the_left_edge_without_a_lone_last_word(self):
        tty = terminal()
        try:
            text = ("The QR code for phones is on the site's home page: open http://192.168.1.10:8791/ in a browser and "
                    "sign in.")
            with mock.patch.object(look, "width", lambda stream=None: 120):
                lines = look.para(text, tty)
            # Every line on the common left edge, the words all there, and the last line more than a word or two.
            self.assertTrue(all(line.startswith(look.INDENT) and not line.startswith(look.INDENT + " ") for line in lines))
            self.assertEqual(" ".join(line.strip() for line in lines), text)
            self.assertGreaterEqual(len(lines[-1].strip()), 16, lines)
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



# What a line is, for the spacing rules below: its kind from its first characters once its left edge is taken off.
KINDS = [("state", re.compile(r"^(ok|note|warn|error|FAIL|missing) ")), ("log", re.compile(r"^\d\d:\d\d:\d\d  ")),
         ("item", re.compile(r"^\d+\. ")), ("closing", re.compile(r"^─+$")), ("heading", re.compile(r"^\S.* ─+$")),
         ("wordmark", re.compile(r"[█▀▄━]"))]


def kind_of(line):
    """The kind of a line of the window: one of KINDS, or a sentence (a label and its value too)."""
    text = line.strip()
    for name, pattern in KINDS:
        if pattern.search(text):
            return name
    return "sentence"


def spacing_problems(lines, columns):
    """What is wrong with the room around the window's lines (colour codes taken off), at a terminal this many columns
    wide: a line into the window's edge or on its first column, a line in from the left that does not stand under the
    text of the line above (a wrapped line), blocks of different kinds touching, a heading, a closing line or the
    wordmark without its blank line, and two blank lines where one is the gap."""
    problems = []
    lines = [plain(line) for line in lines]
    for n, line in enumerate(lines):
        above = lines[n - 1] if n else ""
        if not line.strip():
            if n and not above.strip():
                problems.append(f"line {n}: two blank lines")
            continue
        if len(line) > columns - 1:
            problems.append(f"line {n}: {len(line)} columns, into the edge of {columns}: {line!r}")
        # One right edge for text and headings' lines: the reading width, or the window's when narrower, less a margin as
        # wide as the left one.
        edge = min(columns, look.READ_WIDTH) - len(look.INDENT)
        if len(line) > edge and kind_of(line) != "wordmark":
            problems.append(f"line {n}: past the right edge at {edge}: {line!r}")
        if kind_of(line) in ("heading", "closing") and len(line) != edge:
            problems.append(f"line {n}: a heading's line ending at {len(line)}, not at the right edge {edge}")
        indent = len(line) - len(line.lstrip())
        if indent < len(look.INDENT):
            problems.append(f"line {n}: on the window's first column: {line!r}")
        kind = kind_of(line)
        if kind == "wordmark":
            # Its lean is its own; the line after its last row is blank.
            if n + 1 < len(lines) and lines[n + 1].strip() and kind_of(lines[n + 1]) != "wordmark":
                problems.append(f"line {n + 1}: touches the wordmark")
            continue
        if indent != len(look.INDENT):
            # A wrapped line: under the start of a word of the line above.
            if not (above.strip() and len(above) > indent and above[indent - 1] == " " and above[indent] != " "):
                problems.append(f"line {n}: {indent} columns in, under nothing of the line above: {line!r}")
            # Its last line not a word or two alone (unless the whole of it is that short).
            last = n + 1 >= len(lines) or len(lines[n + 1]) - len(lines[n + 1].lstrip()) != indent
            if last and len(line.strip()) < 16:
                problems.append(f"line {n}: a word alone at a wrapped line's end: {line!r}")
            continue
        if kind == "heading" and above.strip():
            problems.append(f"line {n}: a heading without a blank line above: {line!r}")
        if kind == "closing" and n + 1 < len(lines) and lines[n + 1].strip():
            problems.append(f"line {n + 1}: touches the closing line: {lines[n + 1]!r}")
        if above.strip():
            # Lines of one block, a heading and what stands under it, a sentence that leads into its list, a block and
            # its closing line; nothing else touches.
            together = {("sentence", "item"), ("item", "item"), ("sentence", "sentence"), ("state", "state"),
                        ("log", "log"), ("sentence", "closing")}
            # The line above may be the wrapped end of a longer one: the kind of where that began.
            back = n - 1
            while back > 0 and len(lines[back]) - len(lines[back].lstrip()) != len(look.INDENT) and lines[back].strip():
                back -= 1
            above_kind = kind_of(lines[back])
            if (above_kind, kind) not in together and above_kind not in ("wordmark", "heading"):
                problems.append(f"line {n}: a {kind} touching a {above_kind} above: {line!r}")
    return problems


class WindowSpacingTest(unittest.TestCase):
    """The start window, the status and the setup's end, as the real code prints them on a terminal of 80 columns and
    of the Windows console's 120: one indent step, one blank line between blocks, nothing into the window's edge."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "host"))
        try:
            from opendmtq_host import commands, server, setup
        finally:
            sys.path.pop(0)
        cls.commands, cls.server, cls.setup = commands, server, setup
        from opendmtq_cli import app, system
        cls.app, cls.system = app, system

    def window(self, columns):
        """Every line the flows print at a terminal this many columns wide."""
        tty = terminal()
        self.addCleanup(close, tty)
        look._decided.clear()
        printed = []
        values = {"PUBLIC_HOST": "192.168.1.10:8791", "LISTEN_PORT": "8791", "ADMIN_PASSWORD": "Xk3vQ9pLm2Rt7wZa"}
        record = lambda level, msg: logging.LogRecord("x", level, __file__, 1, msg, None, None)
        logs = look.ConsoleFormatter(tty)
        with mock.patch.object(sys, "stdout", tty), mock.patch.object(look, "width", lambda stream=None: columns), \
                mock.patch.object(look, "_shown", []), \
                mock.patch("builtins.print", lambda *a, **k: printed.extend(str(a[0] if a else "").split("\n"))), \
                mock.patch.object(self.setup, "programs", lambda: {}), mock.patch.object(self.setup, "WINDOWS", True), \
                mock.patch.object(self.commands, "WINDOWS", True), mock.patch.object(self.commands, "tool", lambda *a, **k: 0), \
                mock.patch.object(self.commands, "installer_offered", lambda: True), \
                mock.patch.object(self.setup, "ROOT", "C:\\Users\\someone\\Desktop\\OpenDMTQ"):
            # The Windows window: the setup's start, the settings it wrote, its summary, the running server's lines.
            self.setup.opening()
            for key in ("PUBLIC_HOST=192.168.1.10:8791", "LISTEN_PORT=8791", "ADMIN_PASSWORD=(made, see below)"):
                self.setup.ok(f"{key} written to .env")
            self.setup.summary(values)
            for line in (logs.format(record(logging.INFO, "keeper started (pid 344)")),
                         logs.format(record(logging.INFO, "serving http://192.168.1.10:8791/")),
                         logs.format(record(logging.WARNING, "no answer from the server after 60 s, still waiting. The first "
                                                             "start can be slow while an antivirus checks Apache; the "
                                                             "details are in C:\\Users\\someone\\OpenDMTQ\\data\\state\\logs\\server.log"))):
                print(line)
            print("")
            # A long note, then status.
            self.setup.warn("this computer's address is now 192.168.1.11, but the players' app calls 192.168.1.10. To move "
                            "the server, run OpenDMTQ.exe host 192.168.1.11:8791 (the app is built again; players install "
                            "it over the old one).")
            print("")
            with mock.patch.object(self.commands, "settings", lambda: values), \
                    mock.patch.object(self.commands, "health", lambda v: {"game_data": True, "songs": 128, "players": 6}), \
                    mock.patch.object(self.commands, "app_manifest", lambda: {"file": "opendmtq-192.168.1.10-8791.apk"}), \
                    mock.patch.object(self.commands, "build_status", lambda: {}):
                self.commands.cmd_status(None)
            # ./opendmtq: a step with a long warning and a failed check, the end of up and of the setup.
            self.system.step("2/5  Game files")
            self.system.ok("client data and base APK present")
            self.system.warn("no songs yet: the game starts with an empty song list. Add them with ./opendmtq import "
                             "--songs <folder with your game files>, or one by one on the admin pages")
            self.system.fail("the app download: 404")
            print("")
            for line in self.app.address_lines("192.168.1.10:8791", values):
                print(line)
            for line in self.app.setup_end_lines("203.0.113.7:8791", "anywhere", " The page opens on HTTPS with the "
                                                 "server's own certificate, which browsers warn about once (a phone that "
                                                 "installs http://203.0.113.7:8791/ca.crt does not).", values):
                print(line)
        return printed

    def test_80_columns(self):
        lines = self.window(80)
        self.assertEqual(spacing_problems(lines, 80), [], "\n".join(plain(line) for line in lines))

    def test_the_windows_consoles_120_columns(self):
        lines = self.window(120)
        self.assertEqual(spacing_problems(lines, 120), [], "\n".join(plain(line) for line in lines))

    def test_the_rules_find_what_they_are_for(self):
        # The check itself, on a window with each fault once.
        bad = ["  ok    one", "Players need an account", "  Addresses ─────", "  ok    " + "x" * 90, "", "",
               "      under nothing", "", "  note  a sentence that was wrapped", "        it)", "", "  " + "y" * 85]
        found = "\n".join(spacing_problems(bad, 120))
        for words in ("first column", "a heading without a blank line above", "two blank lines", "past the right edge",
                      "under nothing of the line above", "a word alone", "not at the right edge"):
            self.assertIn(words, found)
        found = "\n".join(spacing_problems(bad, 80))
        for words in ("into the edge",):
            self.assertIn(words, found)


if __name__ == "__main__":
    unittest.main()
