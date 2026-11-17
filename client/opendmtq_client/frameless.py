"""The installer's window without Windows' title bar, keeping the rest of what Windows gives a window.

Windows' title bar, with its minimise and close buttons, sat over the installer's own look; the installer draws its own
header instead (setup_window.py), and this module takes Windows' away while the window keeps what the title bar gave:

- The caption and the sizing frame go by the window's styles on Tk's wrapper window (`wm frame`), never by Tk's
  overrideredirect, which takes a window off the taskbar and out of Alt+Tab. The window becomes a pop-up that keeps its
  system menu and its minimise box, so the taskbar's button minimises and restores it and Alt+F4 closes it, and it is
  marked an application window, so it keeps its taskbar button.
- Tk keeps its own idea of the frame round its window (tkWinWm.c computes it from the style it gave the window) and
  holds an overlapped window that cannot be resized to that frame's size: the caption taken off, it would grow by the
  old frame at every restore. A pop-up's size is its own, so the window keeps its size through a minimise and a restore.
- Windows 11 rounds its corners and DWM draws its shadow (DwmSetWindowAttribute, DwmExtendFrameIntoClientArea with a
  1 px margin). Where DWM says no (Windows 10 has no rounded corners, Wine has no DWM), the window is square and nothing
  else changes.
- A press on the window's top moves it by Windows' own move, as a press on a title bar does (WM_NCLBUTTONDOWN on the
  caption); minimise is the title bar's own command (WM_SYSCOMMAND, SC_MINIMIZE).

Elsewhere (Linux, where the UI tests run on a virtual screen) the window keeps what its window manager gives it, a drag
moves it by its geometry and minimise iconifies it. Nothing here runs at import: every call to Windows is made when a
window asks, through a library a test can stand in for.
"""

import ctypes
import logging
import re
import sys

log = logging.getLogger("opendmtq_client")

# GetWindowLongW's indexes: the window's style and its extended style.
GWL_STYLE, GWL_EXSTYLE = -16, -20
# The styles a title bar comes from (the caption: a border and a dialog frame), the sizing frame and maximise, which go;
# the pop-up the window becomes; the system menu and minimise, which it keeps.
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
# An application window: a taskbar button whatever else the window is.
WS_EX_APPWINDOW = 0x00040000
# SetWindowPos: keep the window where it is in the stack, do not activate it, and work its frame out again.
SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x0004, 0x0010, 0x0020
# A press on the caption, the move it starts, and the title bar's minimise.
WM_NCLBUTTONDOWN, HTCAPTION = 0x00A1, 2
WM_SYSCOMMAND, SC_MINIMIZE = 0x0112, 0xF020
# The left mouse button, as GetKeyState knows it (its high bit set while it is down).
VK_LBUTTON = 0x01
# DWM: the window's corners rounded as Windows 11 rounds a window's (Windows 10 does not know the attribute), and DWM
# drawing what lies round the window (its shadow) though the window has no frame of its own.
DWMWA_NCRENDERING_POLICY, DWMNCRP_ENABLED = 2, 2
DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2
# The 32 bits of a style.
MASK = 0xFFFFFFFF


class Margins(ctypes.Structure):
    """DWM's MARGINS: how far its frame reaches into the window on each side."""
    _fields_ = (("left", ctypes.c_int), ("right", ctypes.c_int), ("top", ctypes.c_int), ("bottom", ctypes.c_int))


def supported():
    """True where the title bar is Windows' own to take away: Windows, and Wine."""
    return sys.platform == "win32"


def styles(style, ex_style):
    """The (style, extended style) of a window without Windows' title bar, from what Tk gave it: no caption, no sizing
    frame, no maximise; a pop-up with its system menu and its minimise box; an application window."""
    # The caption and its border, the sizing frame and maximise go.
    style &= ~(WS_CAPTION | WS_THICKFRAME | WS_MAXIMIZEBOX)
    # A pop-up keeps its own size (Tk holds an overlapped one to the frame it remembers), with the system menu (Alt+F4,
    # Alt+Space, the taskbar's menu) and minimise (the taskbar's button) it had.
    style |= WS_POPUP | WS_SYSMENU | WS_MINIMIZEBOX
    # Its taskbar button, whatever Windows makes of a pop-up.
    return style & MASK, (ex_style | WS_EX_APPWINDOW) & MASK


def _signed(value):
    """A style's 32 bits as the signed LONG SetWindowLongW takes (WS_POPUP is the sign bit)."""
    value &= MASK
    return value - (1 << 32) if value & 0x80000000 else value


def _user32():
    """user32 with the signatures this module calls it by, apart from ctypes.windll's shared one (whose functions
    other modules call with their own arguments)."""
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    for name, result, arguments in (
            ("GetWindowLongW", ctypes.c_long, (wintypes.HWND, ctypes.c_int)),
            ("SetWindowLongW", ctypes.c_long, (wintypes.HWND, ctypes.c_int, ctypes.c_long)),
            ("SetWindowPos", wintypes.BOOL, (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                             ctypes.c_int, wintypes.UINT)),
            ("GetKeyState", ctypes.c_short, (ctypes.c_int,)),
            ("ReleaseCapture", wintypes.BOOL, ()),
            ("PostMessageW", wintypes.BOOL, (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)),
            ("SetWindowTextW", wintypes.BOOL, (wintypes.HWND, wintypes.LPCWSTR))):
        function = getattr(user32, name)
        function.restype, function.argtypes = result, arguments
    return user32


def _dwmapi():
    """dwmapi with its signatures; OSError where there is none."""
    from ctypes import wintypes
    dwmapi = ctypes.WinDLL("dwmapi")
    # Both answer an HRESULT: 0 when done, negative when DWM says no.
    dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
    dwmapi.DwmSetWindowAttribute.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
    dwmapi.DwmExtendFrameIntoClientArea.restype = ctypes.c_long
    dwmapi.DwmExtendFrameIntoClientArea.argtypes = (wintypes.HWND, ctypes.POINTER(Margins))
    return dwmapi


def frame_of(root):
    """The window Windows knows for `root`: Tk's wrapper round it, once it exists (the window shown, or withdrawn and
    laid out once)."""
    return int(str(root.wm_frame()), 16)


def round_and_shadow(hwnd, dwmapi=None):
    """Windows 11's rounded corners and DWM's shadow for a window with no frame of its own. Returns what DWM answered
    each (an HRESULT: 0 when done), or {"dwm": None} where there is no DWM; nothing is raised either way."""
    try:
        dwmapi = dwmapi or _dwmapi()
    except (AttributeError, OSError):
        # No dwmapi (an old Windows, a Wine without it): a square window with no shadow.
        return {"dwm": None}

    def asked(call, *arguments):
        """What DWM answered, or None for a call that could not be made: corners and a shadow are the window's looks,
        never a reason for it not to show."""
        try:
            return call(*arguments)
        except Exception as e:  # noqa: BLE001  (any failure of an optional look: said in the log, the window shows)
            log.warning("DWM could not be asked: %s", e)
            return None

    # Rounded as Windows 11 rounds its windows (Windows 10 answers E_INVALIDARG: it has square corners).
    corner = ctypes.c_int(DWMWCP_ROUND)
    said = {"corners": asked(dwmapi.DwmSetWindowAttribute, hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(corner),
                             ctypes.sizeof(corner))}
    # DWM draws round the window though it has no frame of its own (a pop-up's is off by default)...
    policy = ctypes.c_int(DWMNCRP_ENABLED)
    said["policy"] = asked(dwmapi.DwmSetWindowAttribute, hwnd, DWMWA_NCRENDERING_POLICY, ctypes.byref(policy),
                           ctypes.sizeof(policy))
    # ...and its frame reaches 1 px into the window, which gives it the shadow a framed window has.
    margins = Margins(1, 1, 1, 1)
    said["shadow"] = asked(dwmapi.DwmExtendFrameIntoClientArea, hwnd, ctypes.byref(margins))
    return said


def apply(root, box, user32=None, dwmapi=None):
    """Take Windows' title bar off `root` (on Windows; elsewhere nothing to do) and put the window at `box` (width,
    height, x, y), which counts no title bar. Call it once Tk's wrapper exists and before anything else sets the
    window's size (Tk would size it for the frame it remembers). True when the window has no caption."""
    if not supported() and user32 is None:
        return False
    width, height, x, y = box
    try:
        user32 = user32 or _user32()
        hwnd = frame_of(root)
        style = user32.GetWindowLongW(hwnd, GWL_STYLE) & MASK
        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & MASK
        new_style, new_ex_style = styles(style, ex_style)
        user32.SetWindowLongW(hwnd, GWL_STYLE, _signed(new_style))
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, _signed(new_ex_style))
        # Rounded and shadowed where DWM can; said in the log either way.
        said = round_and_shadow(hwnd, dwmapi)
        # Its frame worked out again for the new style, at the size and place that count no title bar.
        user32.SetWindowPos(hwnd, None, int(x), int(y), int(width), int(height),
                            SWP_FRAMECHANGED | SWP_NOZORDER | SWP_NOACTIVATE)
        shown = user32.GetWindowLongW(hwnd, GWL_STYLE) & MASK
    except Exception as e:  # noqa: BLE001  (a Windows or a Wine without a call, a window with no wrapper yet: said)
        # Windows' title bar stays; the window shows all the same.
        log.warning("the window keeps Windows' title bar: %s", e)
        return False
    gone = not shown & WS_CAPTION
    log.info("the window's title bar %s: style %08x (was %08x), DWM %s", "is gone" if gone else "stayed", shown, style,
             ", ".join("%s %s" % (k, "none" if v is None else "%08x" % (v & MASK)) for k, v in sorted(said.items())))
    return gone


def start_move(root, event, user32=None):
    """Windows' own move of the window from where the pointer pressed, as a press on a title bar starts it: the window
    follows the pointer until the button comes up. Only while the button is still down (a click already over starts
    nothing). True when the move was started.

    The press on the caption is posted, never sent: Windows' move runs a loop of its own until the button comes up, and
    Tk lets its timers run during it (WM_ENTERSIZEMOVE), which call Python; sent from this press's handler, the loop
    would run inside it, where tkinter cannot call Python again (a fatal error, met under Wine). Posted, the loop starts
    from Tk's own loop once the handler is done, as a press on a title bar does; and Windows takes posted messages before
    the mouse's, so a button let go meanwhile ends the move as soon as it starts."""
    user32 = user32 or _user32()
    if not user32.GetKeyState(VK_LBUTTON) & 0x8000:
        return False
    hwnd = frame_of(root)
    # Tk holds the pointer for the widget pressed: let go of it, so that the move takes it.
    user32.ReleaseCapture()
    # The press on the caption, at the pointer's place on the screen (the low and high 16 bits, as Windows packs it).
    point = (int(event.x_root) & 0xFFFF) | ((int(event.y_root) & 0xFFFF) << 16)
    user32.PostMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, point)
    return True


def minimize(root, user32=None):
    """Minimise the window as the title bar's button did: Windows' own minimise (on to the taskbar, the next window
    active), or the window manager's elsewhere."""
    if not supported() and user32 is None:
        root.iconify()
        return
    user32 = user32 or _user32()
    # Posted, as the title bar's button posts it: done once this press is over, by Tk's own loop.
    user32.PostMessageW(frame_of(root), WM_SYSCOMMAND, SC_MINIMIZE, 0)


def name(widget, words, user32=None):
    """The words a screen reader says for `widget` (on Windows its window's text, which Windows' own accessibility
    names a window by; Tk gives its widgets none)."""
    if not supported() and user32 is None:
        return
    try:
        user32 = user32 or _user32()
        user32.SetWindowTextW(widget.winfo_id(), words)
    except (AttributeError, OSError) as e:
        log.warning("could not name %s for screen readers: %s", words, e)


def place(root):
    """(x, y) of the window as its geometry says it ("800x540+100+80", a negative place as "+-10"): the corner a new
    geometry puts it at. Its place on the screen where the geometry counts from another edge ("-10")."""
    found = re.match(r"^\d+x\d+([+-])(-?\d+)([+-])(-?\d+)$", str(root.geometry()))
    if found and found.group(1) == "+" and found.group(3) == "+":
        return int(found.group(2)), int(found.group(4))
    return root.winfo_rootx(), root.winfo_rooty()


class Mover:
    """Moves `root` by the widgets bound to it (the window's top): on Windows by Windows' own move (start_move), else by
    following the pointer with the window's geometry. `where(event)` says whether a press lies on the part that moves the
    window (the column's top, not its steps); None for all of a widget."""

    def __init__(self, root, user32=None):
        self.root, self.user32 = root, user32
        # Where a move by the geometry began: the pointer's place on the screen and the window's, or None.
        self.start = None

    def bind(self, widget, where=None):
        widget.bind("<ButtonPress-1>", lambda e: self._press(e, where), add="+")
        widget.bind("<B1-Motion>", self._motion, add="+")
        widget.bind("<ButtonRelease-1>", self._release, add="+")

    def _press(self, event, where):
        if where is not None and not where(event):
            return None
        if supported() or self.user32 is not None:
            start_move(self.root, event, self.user32)
            return "break"
        # The window's place as its geometry says it (its frame's corner under a window manager), and the pointer's.
        self.start = (event.x_root, event.y_root) + place(self.root)
        return "break"

    def _motion(self, event):
        if self.start is None:
            return None
        px, py, x, y = self.start
        # Where the pointer has gone since the press, the window as far.
        self.root.geometry("+%d+%d" % (x + event.x_root - px, y + event.y_root - py))
        return "break"

    def _release(self, event):
        moved, self.start = self.start is not None, None
        return "break" if moved else None
