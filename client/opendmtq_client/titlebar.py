"""The launcher's window keeps Windows' own title bar (its minimise, maximise and close, a double click and a drag to
snap), drawn dark in the launcher's colours instead of Windows' light one over the dark launcher.

The owner asked for the installer's title bar to go (frameless.py); the launcher's stays, and DWM, which draws it, is
asked for its dark form (DWMWA_USE_IMMERSIVE_DARK_MODE, Windows 10 2004 and later; 19 on the Windows 10 builds before
it) and, where Windows 11 has them, for its colours: the bar in the column's strip under it, its words in the launcher's
text colour, the window's edge in the seam along the column (theme.STRIP, theme.TEXT, theme.SEAM). Where DWM says no to
one (Windows 10 has no colours, Wine has no DWM), the bar keeps what it had and the window shows all the same.

Asked before the window first shows (app.py): set once the window is on screen, Windows draws the bar as it was until
the window is next activated. Nothing here runs at import; every call goes through a library a test can stand in for.
"""

import ctypes
import logging

from opendmtq_client import frameless, theme

log = logging.getLogger("opendmtq_client")

# DWM's attributes: the title bar's dark form (its number since Windows 10 2004, and the one before it), then Windows
# 11's own colours for the window's edge, the title bar and the title bar's words.
DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_2004 = 20, 19
DWMWA_BORDER_COLOR, DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR = 34, 35, 36
# The colours, the launcher's own: the bar the strip at the column's foot and top (the column runs up under it), its
# words the text's, the window's edge the seam along the column's side.
COLOURS = ((DWMWA_CAPTION_COLOR, "caption", theme.STRIP), (DWMWA_TEXT_COLOR, "words", theme.TEXT),
           (DWMWA_BORDER_COLOR, "edge", theme.SEAM))


def colorref(colour):
    """A theme colour ("#rrggbb") as Windows' COLORREF: 0x00bbggrr."""
    value = colour.lstrip("#")
    red, green, blue = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return red | (green << 8) | (blue << 16)


def dark(root, dwmapi=None):
    """Windows' title bar of `root` drawn dark in the launcher's colours, where Windows has them (on Windows; elsewhere
    nothing to do). Call it once Tk's wrapper exists and before the window shows. Returns what DWM answered for each
    ({"dark": HRESULT, "caption": ..., "words": ..., "edge": ...}, 0 when done, None for a call that could not be made),
    {"dwm": None} where there is no DWM, or {} off Windows; never raises: the bar's colours never stop the window."""
    if not frameless.supported() and dwmapi is None:
        return {}
    try:
        dwmapi = dwmapi or frameless._dwmapi()
    except (AttributeError, OSError):
        # No dwmapi (an old Windows, a Wine without it): Windows' own bar as it is.
        return {"dwm": None}

    def asked(attribute, value):
        """What DWM answered for one attribute (an int), or None for a call that could not be made."""
        number = ctypes.c_int(value)
        try:
            return dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(number), ctypes.sizeof(number))
        except Exception as e:  # noqa: BLE001  (any failure of an optional look: said in the log, the window shows)
            log.warning("DWM could not be asked for the title bar: %s", e)
            return None

    try:
        hwnd = frameless.frame_of(root)
    except Exception as e:  # noqa: BLE001  (a window with no wrapper yet: said, the bar stays as it is)
        log.warning("the title bar stays light: %s", e)
        return {"dwm": None}
    # The dark form, by its number since Windows 10 2004; a Windows before it knows it by the older number.
    said = {"dark": asked(DWMWA_USE_IMMERSIVE_DARK_MODE, 1)}
    if said["dark"] != 0:
        said["dark"] = asked(DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_2004, 1)
    # Windows 11's colours (Windows 10 answers E_INVALIDARG: its dark bar is Windows' own dark grey).
    for attribute, name, colour in COLOURS:
        said[name] = asked(attribute, colorref(colour))
    log.info("the title bar: %s", ", ".join("%s %s" % (k, "none" if v is None else "%08x" % (v & 0xFFFFFFFF))
                                            for k, v in sorted(said.items())))
    return said
