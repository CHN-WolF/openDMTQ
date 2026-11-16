"""How the command line looks in a terminal: the OpenDMTQ wordmark, state colours, aligned label and value lines and the
block with the addresses. Shared by ./opendmtq (Docker) and the host install's program (the Windows bundle's window too).
Standard library only. Colour only on a terminal that shows it (not in a pipe, a log file, NO_COLOR or TERM=dumb); the
wordmark only on a terminal at all, plain lines everywhere else."""

import logging
import os
import shutil
import sys
import textwrap

# The product's colours (server/portal/style.css): its lime, the warning yellow, the error red, the grey of quiet text.
# A terminal without 24-bit colour (macOS Terminal) gets the nearest of the 256 every terminal has (nearest_256).
COLOURS = {"ok": "#8cf23d", "warn": "#ffcf3d", "bad": "#ff5f72", "dim": "#8f99a4", "ash": "#aeb8c3", "accent": "#8cf23d"}

# The wordmark's letters, four rows each: the site's logo (DMTQ in its wide italic, under a small OPEN with a line that
# runs from grey into lime). The italic lean comes from starting each row one column further left than the one above.
LETTERS = {
    "D": ["█████▄ ", "██   ██", "██   ██", "█████▀ "],
    "M": ["███▄ ▄███", "██ ▀█▀ ██", "██     ██", "██     ██"],
    "T": ["████████", "   ██   ", "   ██   ", "   ██   "],
    "Q": ["▄█████▄ ", "██   ██ ", "██  ▄██ ", "▀█████▀▄"],
}
# Each row's colour, top to bottom: the letters' metal (white, a dark band, light again) and the Q's white into lime,
# as the logo's own gradients on the site.
METAL = ["#ffffff", "#e4e9ee", "#9aa4ae", "#d5dbe1"]
LIME = ["#f0ffe0", "#c4f78f", "#8cf23d", "#8cf23d"]
# Columns between letters, and how far the top row starts right of the bottom one (the lean).
GAP, LEAN = "  ", 3

# What every line starts with, so the wordmark, the state words and the blocks share one left edge.
INDENT = "  "

# Whether the terminal was set up for colour already (Windows' virtual terminal), and the answer, per stream.
_decided = {}


def _windows_vt(stream):
    """Turns on Windows' virtual terminal for the console the stream writes to, so it draws colour codes instead of
    printing them; False when it cannot (an old Windows, no console)."""
    try:
        import ctypes
        import msvcrt
        # Wine takes the setting but its console window prints the codes as text: no colour there.
        if hasattr(ctypes.windll.ntdll, "wine_get_version"):
            return False
        kernel = ctypes.windll.kernel32
        handle = msvcrt.get_osfhandle(stream.fileno())
        mode = ctypes.c_uint32()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING: the console reads ANSI codes.
        return bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError, ValueError, ImportError):
        return False


def is_terminal(stream=None):
    """True when the stream is a terminal a person reads (not a pipe or a file)."""
    stream = stream or sys.stdout
    try:
        return stream.isatty()
    except (AttributeError, ValueError):
        return False


def colour_on(stream=None):
    """True when the stream shows colour: a terminal, NO_COLOR unset (https://no-color.org), TERM not dumb, and on
    Windows its virtual terminal turned on."""
    stream = stream or sys.stdout
    key = id(stream)
    if key not in _decided:
        on = is_terminal(stream) and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"
        if on and os.name == "nt":
            on = _windows_vt(stream)
        _decided[key] = on
    return _decided[key]


def _code(rgb):
    """The escape code for a colour, #rrggbb: 24-bit where the terminal has it (Windows' console, a terminal that says
    so in COLORTERM), else the nearest of the 256."""
    if os.name == "nt" or os.environ.get("COLORTERM") in ("truecolor", "24bit"):
        return "\033[38;2;%d;%d;%dm" % tuple(int(rgb[i:i + 2], 16) for i in (1, 3, 5))
    return f"\033[38;5;{nearest_256(rgb)}m"


def paint(text, role, stream=None, bold=False):
    """text in a role's colour (COLOURS), or as it is where colour is off."""
    if not colour_on(stream):
        return text
    return ("\033[1m" if bold else "") + _code(COLOURS[role]) + text + "\033[0m"


def width(stream=None):
    """The terminal's width in columns, 100 when it does not say."""
    return shutil.get_terminal_size((100, 24)).columns


def nearest_256(rgb):
    """The index of the 256-colour palette's entry nearest to #rrggbb: one of its 6x6x6 cube or of its 24 greys."""
    r, g, b = (int(rgb[i:i + 2], 16) for i in (1, 3, 5))
    steps = [0, 95, 135, 175, 215, 255]
    # The cube's nearest step for each channel, and how far that entry is.
    cube = [min(range(6), key=lambda k, v=v: abs(steps[k] - v)) for v in (r, g, b)]
    cube_far = sum((steps[k] - v) ** 2 for k, v in zip(cube, (r, g, b)))
    # The grey ramp (8, 18, ... 238) at the channels' average.
    grey = min(range(24), key=lambda k: abs(8 + 10 * k - (r + g + b) / 3))
    grey_far = sum((8 + 10 * grey - v) ** 2 for v in (r, g, b))
    return 16 + 36 * cube[0] + 6 * cube[1] + cube[2] if cube_far <= grey_far else 232 + grey


def _mix(a, b, share):
    """The colour share of the way from a to b, all #rrggbb."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * share) for x, y in zip(ca, cb))


def wordmark(version="", stream=None):
    """The wordmark's lines, the version beside its foot as on the site; on something that is not a terminal (a pipe,
    the log) one plain line with the name and the version instead."""
    if not is_terminal(stream):
        return [f"OpenDMTQ {version}".rstrip()]
    colour = colour_on(stream)
    letters = "DMTQ"
    span = sum(len(LETTERS[c][0]) for c in letters) + len(GAP) * (len(letters) - 1)
    head = "O P E N "
    # The line after OPEN runs to the wordmark's right end, grey into lime.
    run = span - len(head)
    if colour:
        rule = "".join(_code(_mix("#5d6670", "#8cf23d", i / max(run - 1, 1))) + "━" for i in range(run)) + "\033[0m"
        head = paint(head, "ash", stream)
    else:
        rule = "━" * run
    lines = [INDENT + " " * LEAN + head + rule]
    for row in range(4):
        parts = []
        for c in letters:
            glyph = LETTERS[c][row]
            parts.append(_code((LIME if c == "Q" else METAL)[row]) + glyph + "\033[0m" if colour else glyph)
        line = INDENT + " " * (LEAN - row) + GAP.join(parts)
        # The version beside the last row, as the site's logo carries it.
        if row == 3 and version:
            line += "  " + paint("v" + version.lstrip("v"), "ash", stream)
        lines.append(line)
    return lines


# Once per run: `setup` runs `up`, and each would show it.
_shown = []


def banner(version="", stream=None):
    """Prints the wordmark once per run, with a blank line under it."""
    if _shown:
        return
    _shown.append(True)
    out = stream or sys.stdout
    for line in wordmark(version, stream) + [""]:
        print(line, file=out, flush=True)


def tag(kind, stream=None):
    """The word that starts a state line, padded to one width and coloured by what it says: ok, note (or warn), error
    (or FAIL)."""
    role = {"ok": "ok", "note": "warn", "warn": "warn", "error": "bad", "FAIL": "bad"}[kind]
    return paint(kind, role, stream, bold=role == "bad") + " " * (6 - len(kind))


def state_line(kind, msg, stream=None):
    """One state line: the tag, then the message, on the common left edge."""
    return f"{INDENT}{tag(kind, stream)}{msg}"


def rows(pairs, stream=None, indent=INDENT):
    """Label and value lines, the values in one column after the longest label; labels in quiet grey. A value may be a
    (text, role) pair to colour it by its state."""
    pairs = [(label, value) for label, value in pairs if value is not None]
    room = max((len(label) for label, _ in pairs), default=0) + 2
    out = []
    for label, value in pairs:
        text = paint(value[0], value[1], stream) if isinstance(value, tuple) else str(value)
        out.append(indent + paint(label.ljust(room), "dim", stream) + text)
    return out


def rule(title="", stream=None):
    """A section's heading: its title, then a line to a comfortable width (shorter on a narrow terminal)."""
    span = min(width(stream) - len(INDENT) - 1, 72)
    head = f"{title} " if title else ""
    line = "─" * max(span - len(head), 4)
    if not is_terminal(stream):
        # A pipe or a log: a plain heading line, nothing drawn.
        return f"{INDENT}{title}" if title else ""
    return INDENT + paint(head, "ash", stream, bold=True) + paint(line, "dim", stream)


def para(text, stream=None):
    """A sentence or two for a person: on a terminal wrapped to its width on the common left edge, so a long line does not
    run back to the first column; as it is anywhere else."""
    if not is_terminal(stream):
        return [text]
    room = min(width(stream), 110) - len(INDENT) - 1
    return textwrap.wrap(text, room, initial_indent=INDENT, subsequent_indent=INDENT, break_on_hyphens=False,
                         break_long_words=False) or [""]


def address_block(site, admin, user, password=None, where=None, stream=None, title="Addresses"):
    """The block a start ends with: where players go, where the admin pages are, and how the owner signs in. password is
    shown when given (the first setup's window), else where it is kept (where)."""
    pairs = [("Players' site", site), ("Admin pages", admin), ("Admin ID", user)]
    if password:
        pairs.append(("Password", password + (f"  ({where})" if where else "")))
    elif where:
        pairs.append(("Password", where))
    lines = [rule(title, stream)] + rows(pairs, stream, indent=INDENT + "  ")
    # A closing line on a terminal; nothing more in a pipe or a log.
    return lines + ([rule("", stream)] if is_terminal(stream) else [])


class ConsoleFormatter(logging.Formatter):
    """The running server's lines in its window: the time in grey and a state word for a warning or an error; plain,
    with the date, anywhere else (the log file has its own formatter)."""

    def __init__(self, stream=None):
        super().__init__("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S")
        self.stream = stream

    def format(self, record):
        if not is_terminal(self.stream):
            return super().format(record)
        when = paint(self.formatTime(record, "%H:%M:%S"), "dim", self.stream)
        kind = "error" if record.levelno >= logging.ERROR else "note" if record.levelno >= logging.WARNING else None
        return f"{INDENT}{when}  " + (tag(kind, self.stream) if kind else "") + record.getMessage()
