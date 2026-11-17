"""The command line's own look (OpenDMTQ-cmd.exe): what it prints laid out as the launcher's pages are, a title with the
version, then each part under its name, the names and values in two columns, a ready check's rows with a mark each,
and a download's progress as one bar that moves in place.

In a terminal that shows colours (Windows 10's console and Windows Terminal, once asked to, ANSI terminals elsewhere),
the marks and the names take the launcher's colours: lime for what is fine, yellow for what will change, red for a
problem, grey for names. Anywhere else (a pipe, a file, a script reading it, NO_COLOR set) the same layout in plain
text, the marks in words ("ok", "warn", "todo", "play"), so that what a script looks for stays the same.
"""

import os
import shutil
import sys

# The launcher's colours (theme.py) as 24-bit terminal colours: lime, yellow, red, the names' grey, the faint grey.
COLOURS = {"ok": (0x8c, 0xf2, 0x3d), "warn": (0xff, 0xcf, 0x3d), "bad": (0xff, 0x5f, 0x72), "muted": (0xae, 0xb8, 0xc3),
           "faint": (0x8d, 0x98, 0xa4), "text": (0xee, 0xf2, 0xf6)}
# A ready check's mark by its kind, as words in plain text (what scripts and the tests read) and the tone it shows in.
MARKS = {"ok": ("ok", "ok"), "warn": ("warn", "warn"), "todo": ("todo", "bad"), "play": ("play", "warn"),
         # A connection test's step that fails, and one not tried (connection.py).
         "fail": ("fail", "bad"), "skip": ("skip", "faint")}
# The names' column: as wide as the longest name of a part, at least this many characters.
NAME_WIDTH = 10
# How wide a line is at most when the terminal does not say (characters).
WIDTH = 100

# Windows' console: the mode that lets it read colour sequences (ENABLE_VIRTUAL_TERMINAL_PROCESSING), and the handle
# of standard output.
VT_PROCESSING = 0x0004
STD_OUTPUT_HANDLE = -11

_colour = None


def colour_on(stream=None):
    """Whether this run prints colours: a terminal, NO_COLOR not set, and on Windows a console that takes them (asked
    for once)."""
    global _colour
    stream = stream or sys.stdout
    if _colour is not None and stream is sys.stdout:
        return _colour
    on = bool(stream is not None and hasattr(stream, "isatty") and stream.isatty() and "NO_COLOR" not in os.environ
              and os.environ.get("TERM") != "dumb")
    if on and sys.platform == "win32":
        on = _windows_colours()
    if stream is sys.stdout:
        _colour = on
    return on


def _windows_colours():
    """Ask Windows' console to read colour sequences (Windows 10 and later do); False when it will not."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if mode.value & VT_PROCESSING:
            return True
        return bool(kernel32.SetConsoleMode(handle, mode.value | VT_PROCESSING))
    except (AttributeError, OSError):
        return False


def paint(text, tone=None, bold=False, stream=None):
    """`text` in a tone's colour (and bold) when this run prints colours, else as it is."""
    if not text or not colour_on(stream) or (tone is None and not bold):
        return text
    codes = []
    if bold:
        codes.append("1")
    if tone in COLOURS:
        codes.append("38;2;%d;%d;%d" % COLOURS[tone])
    return "\033[%sm%s\033[0m" % (";".join(codes), text)


def width():
    """How wide a line may be: the terminal's width, or WIDTH."""
    try:
        return max(40, min(WIDTH, shutil.get_terminal_size((WIDTH, 24)).columns - 1))
    except (OSError, ValueError):
        return WIDTH


def title(version, what="PC client"):
    """The first line of what a job prints: the program and its version."""
    return "%s %s  %s" % (paint("OpenDMTQ", "ok", bold=True), paint(version, bold=True), paint(what, "muted"))


def heading(name):
    """A part's name, on a line of its own with a blank line before it."""
    return "\n" + paint(name, bold=True)


def rows(pairs, indent=0):
    """Names and values in two columns ("name  value"), the names in grey, a value that runs long wrapped under its
    column. `pairs`: (name, value) or (name, value, tone)."""
    pairs = list(pairs)
    column = max([NAME_WIDTH] + [len(pair[0]) for pair in pairs]) + 2
    lines = []
    for pair in pairs:
        name, value = pair[0], pair[1]
        tone = pair[2] if len(pair) > 2 else None
        room = max(20, width() - indent - column)
        parts = _wrap(str(value), room)
        lines.append(" " * indent + paint(name.ljust(column), "muted") + paint(parts[0], tone))
        for part in parts[1:]:
            lines.append(" " * (indent + column) + paint(part, tone))
    return "\n".join(lines)


def mark(kind):
    """A ready check's mark: its word in a column of four, in its tone."""
    words, tone = MARKS[kind]
    return "[%s]" % paint(words.ljust(4), tone)


def words(items, indent=2):
    """Words such as name=value laid out in lines no wider than the terminal, two spaces apart."""
    room = width() - indent
    lines, line = [], ""
    for item in items:
        if line and len(line) + 2 + len(item) > room:
            lines.append(line)
            line = item
        else:
            line = item if not line else line + "  " + item
    if line:
        lines.append(line)
    return "\n".join(" " * indent + line for line in lines)


def bar(done, total, label, size=24):
    """A download's progress as one line: its words, a bar of `size` cells, and how far."""
    share = 0.0 if not total else max(0.0, min(1.0, done / float(total)))
    full = int(round(share * size))
    if colour_on():
        cells = paint("█" * full, "ok") + paint("░" * (size - full), "faint")
    else:
        cells = "#" * full + "." * (size - full)
    return "%s  %s  %3d%%" % (label, cells, int(round(share * 100)))


def _wrap(text, room):
    """`text` cut into lines no longer than `room` at its spaces (a long path stays whole on its own line)."""
    if len(text) <= room:
        return [text]
    lines, line = [], ""
    for word in text.split(" "):
        if line and len(line) + 1 + len(word) > room:
            lines.append(line)
            line = word
        else:
            line = word if not line else line + " " + word
    lines.append(line)
    return lines
