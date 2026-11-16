"""What the program says: its messages, and its log."""

import logging
import logging.handlers
import sys

from .paths import BUNDLE, WINDOWS
# The command line's look (cli/opendmtq_cli/look.py, on the path through .paths): the same state words and colours as
# ./opendmtq.
from opendmtq_cli import look


def say(msg=""):
    """One line for the person at the terminal, at once."""
    print(msg, flush=True)


def tell(msg):
    """A sentence or two for the person: wrapped on the terminal's left edge there (look.para), as it is in a log."""
    for line in look.para(msg):
        say(line)


def ok(msg):
    """A step that worked."""
    say(look.state_line("ok", msg))


def warn(msg):
    """Something to know that does not stop the server."""
    say(look.state_line("note", msg))


def die(msg, code=1):
    """Stop with what went wrong and what to do about it."""
    say(look.state_line("error", msg))
    # In the background nobody reads the terminal: the reason goes to the log file as well. Only there: a logger without
    # a file writes to the same terminal, and the reason would show twice.
    if any(isinstance(h, logging.FileHandler) for h in logging.getLogger().handlers):
        logging.error(msg)
    # In the Windows window, the reason stays readable until the person closes it.
    if WINDOWS and BUNDLE and sys.stdin and sys.stdin.isatty():
        try:
            input("Press Enter to close this window.")
        except EOFError:
            pass
    sys.exit(code)
