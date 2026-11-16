"""The PC's displays, for the Screen page: the main display's size in pixels and Windows' scale on it, so the page can
leave out window sizes larger than it or smaller than the game's window holds there, and every connected display's
refresh rate, so that the frame limits go up to the fastest of them (a 165 Hz or 180 Hz touch screen beside a 60 Hz
one included).

On Windows the rates come from Windows' own display configuration (QueryDisplayConfig: each active display's path and
its rate as a fraction, 164.999 Hz read as 165), else from each display's current mode (EnumDisplaySettings), else from
GDI's main display; elsewhere (development and the tests) Tk's screen size and no rate.
"""

import logging
import os
import re
import sys

log = logging.getLogger("opendmtq_client")

# The frame limits a display of a known rate is offered up to, besides each display's own rate: the rates displays
# are sold with, so that a limit at a whole fraction of one is there too (30 on 60 Hz, 80 on 160 Hz is not one people
# pick). Every one of them is inside the player's range (30 to 1000, arm32/desktop/settings.cpp).
RATES = (30, 60, 75, 90, 100, 120, 144, 160, 165, 170, 180, 200, 240, 280, 300, 360, 480, 500, 540)
# The player's own range for a frame limit (arm32/desktop/settings.cpp, number(value, 30, 1000, n)).
LEAST, MOST = 30, 1000
# A display's rate is offered up to this far above a rate in RATES: a 143.9 Hz display offers 144, never 165.
MARGIN = 1.03


def main_display(root=None):
    """{"width", "height", "hz", "scale"} of the main display; hz None when the system does not say, scale 1.0 (100 %)
    when it cannot be told. hz is the main display's own rate in whole hertz (164.999 Hz is 165)."""
    if sys.platform == "win32":
        found = _gdi_main()
        if found is not None:
            # The main display's rate from Windows' display configuration where it says one: GDI rounds a 164.999 Hz
            # display down to 164, and that 164 would leave its own 165 out of the frame limits.
            listed = [d for d in connected() if d.get("main") and d.get("hz")]
            if listed:
                found["hz"] = listed[0]["hz"]
            return found
    if root is not None:
        return {"width": root.winfo_screenwidth(), "height": root.winfo_screenheight(), "hz": None, "scale": 1.0}
    return {"width": 0, "height": 0, "hz": None, "scale": 1.0}


def _gdi_main():
    """The main display from GDI (its own pixels, its rate, Windows' scale on it), or None without GDI."""
    try:
        import ctypes
        from ctypes import wintypes
        user32, gdi32 = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
        # The screen's device context is a handle: its own type, so that it passes back whole.
        user32.GetDC.restype = wintypes.HDC
        user32.GetDC.argtypes = (wintypes.HWND,)
        user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
        gdi32.GetDeviceCaps.argtypes = (wintypes.HDC, ctypes.c_int)
        dc = user32.GetDC(None)
        try:
            # DESKTOPHORZRES, DESKTOPVERTRES and VREFRESH: the main display's own pixels, whatever the program's DPI
            # awareness (the command line has none, and HORZRES would give it the display shrunk by Windows' scaling),
            # and its rate in whole hertz.
            width, height, hz = gdi32.GetDeviceCaps(dc, 118), gdi32.GetDeviceCaps(dc, 117), gdi32.GetDeviceCaps(dc, 116)
            # Windows' scale on it, the same with DPI awareness (the launcher's window: LOGPIXELSX is the display's dots
            # per inch) and without (the command line: LOGPIXELSX says 96, and HORZRES the display shrunk by the scale):
            # whichever of the two says more.
            logical_dpi, logical_width = gdi32.GetDeviceCaps(dc, 88), gdi32.GetDeviceCaps(dc, 8)
        finally:
            user32.ReleaseDC(None, dc)
        scale = max(logical_dpi / 96.0 if logical_dpi > 0 else 1.0, width / float(logical_width) if logical_width > 0 else 1.0)
        # 0 and 1 mean the hardware's default rate, which says nothing.
        return {"width": width, "height": height, "hz": hz if hz > 1 else None, "scale": round(max(1.0, scale), 3)}
    except (AttributeError, OSError):
        # No GDI to ask (a stripped-down Windows).
        return None


def connected():
    """Every active display as [{"width", "height", "hz", "main"}], hz in whole hertz or None, the main one first; []
    where the system does not say (not Windows, or nothing to ask). Never raises: a display that cannot be read is left
    out, and the page then offers what it offers without a rate."""
    named = os.environ.get("OPENDMTQ_DISPLAYS")
    if named is not None:
        # Made-up displays for the tests and the pictures, as "2560x1440@165*,1920x1080@60" (* the main one).
        return made_up(named)
    if sys.platform != "win32":
        return []
    for reader in (_display_config, _display_settings):
        try:
            found = reader()
        except (AttributeError, OSError, ValueError):
            # This way of asking is missing or refused (an older Windows, Wine without it): the next one.
            log.debug("could not read the displays by %s", reader.__name__, exc_info=True)
            continue
        if found:
            # The main display first: the page's words about "this display" are about it.
            return sorted(found, key=lambda d: not d["main"])
    return []


def made_up(text):
    """Displays written as "2560x1440@165*,1920x1080@60" (each WIDTHxHEIGHT@HZ, * after the main one) as connected()
    lists them, the main one first; a part that is not one is left out."""
    found = []
    for part in text.split(","):
        match = re.match(r"^\s*(\d+)x(\d+)@(\d+(?:\.\d+)?)(\*?)\s*$", part)
        if match:
            hz = whole_hz(float(match.group(3)) * 1000, 1000)
            found.append({"width": int(match.group(1)), "height": int(match.group(2)), "hz": hz,
                          "main": bool(match.group(4))})
    return sorted(found, key=lambda d: not d["main"])


def whole_hz(numerator, denominator):
    """A rate given as a fraction (Windows' display configuration: 164999/1000) in whole hertz (165); None for none."""
    if not denominator or not numerator:
        return None
    hz = numerator / float(denominator)
    # 0 and 1 are a mode with no rate of its own; a rate rounds to the nearest whole hertz, 59.94 to 60.
    return int(round(hz)) if hz > 1.5 else None


def _display_config():
    """The active displays from Windows' display configuration (QueryDisplayConfig with QDC_ONLY_ACTIVE_PATHS): each
    path's target rate as a fraction, its source mode's size and place (the main display stands at 0,0)."""
    import ctypes
    from ctypes import wintypes

    class Luid(ctypes.Structure):
        _fields_ = (("low", wintypes.DWORD), ("high", wintypes.LONG))

    class Rational(ctypes.Structure):
        _fields_ = (("numerator", ctypes.c_uint32), ("denominator", ctypes.c_uint32))

    class PathSource(ctypes.Structure):
        _fields_ = (("adapter", Luid), ("id", ctypes.c_uint32), ("mode_index", ctypes.c_uint32),
                    ("status", ctypes.c_uint32))

    class PathTarget(ctypes.Structure):
        _fields_ = (("adapter", Luid), ("id", ctypes.c_uint32), ("mode_index", ctypes.c_uint32),
                    ("technology", ctypes.c_uint32), ("rotation", ctypes.c_uint32), ("scaling", ctypes.c_uint32),
                    ("rate", Rational), ("scan_order", ctypes.c_uint32), ("available", wintypes.BOOL),
                    ("status", ctypes.c_uint32))

    class Path(ctypes.Structure):
        _fields_ = (("source", PathSource), ("target", PathTarget), ("flags", ctypes.c_uint32))

    class SourceMode(ctypes.Structure):
        _fields_ = (("width", ctypes.c_uint32), ("height", ctypes.c_uint32), ("format", ctypes.c_uint32),
                    ("x", ctypes.c_long), ("y", ctypes.c_long))

    class Signal(ctypes.Structure):
        _fields_ = (("pixel_rate", ctypes.c_uint64), ("h_sync", Rational), ("v_sync", Rational),
                    ("active", ctypes.c_uint32 * 2), ("total", ctypes.c_uint32 * 2), ("standard", ctypes.c_uint32),
                    ("scan_order", ctypes.c_uint32))

    class ModeUnion(ctypes.Union):
        # The target's signal is the largest member (48 bytes): the union is that size whatever the mode is.
        _fields_ = (("target", Signal), ("source", SourceMode), ("room", ctypes.c_byte * 48))

    class Mode(ctypes.Structure):
        _fields_ = (("kind", ctypes.c_uint32), ("id", ctypes.c_uint32), ("adapter", Luid), ("mode", ModeUnion))

    # The sizes Windows lays these out in: a mismatch would read garbage, so it is refused before any call.
    if ctypes.sizeof(Path) != 72 or ctypes.sizeof(Mode) != 64:
        raise ValueError("display configuration structures of unexpected size")
    user32 = ctypes.WinDLL("user32")
    only_active = 2                                     # QDC_ONLY_ACTIVE_PATHS
    paths_n, modes_n = ctypes.c_uint32(), ctypes.c_uint32()
    for _ in range(3):
        # The counts can grow between the two calls (a display plugged in): asked again then.
        if user32.GetDisplayConfigBufferSizes(only_active, ctypes.byref(paths_n), ctypes.byref(modes_n)):
            raise OSError("GetDisplayConfigBufferSizes failed")
        paths, modes = (Path * paths_n.value)(), (Mode * modes_n.value)()
        status = user32.QueryDisplayConfig(only_active, ctypes.byref(paths_n), paths, ctypes.byref(modes_n), modes,
                                           None)
        if status == 0:
            break
        if status != 122:                               # ERROR_INSUFFICIENT_BUFFER: asked again
            raise OSError("QueryDisplayConfig failed with %d" % status)
    else:
        raise OSError("QueryDisplayConfig kept changing")
    found = []
    for path in paths[:paths_n.value]:
        hz = whole_hz(path.target.rate.numerator, path.target.rate.denominator)
        target_mode = path.target.mode_index
        if hz is None and target_mode < modes_n.value and modes[target_mode].kind == 2:
            # No rate on the path itself: the target mode's vertical sync (DISPLAYCONFIG_MODE_INFO_TYPE_TARGET).
            v_sync = modes[target_mode].mode.target.v_sync
            hz = whole_hz(v_sync.numerator, v_sync.denominator)
        width = height = 0
        main = False
        source_mode = path.source.mode_index
        if source_mode < modes_n.value and modes[source_mode].kind == 1:
            # DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE: the display's desktop size, and its place (0,0 for the main one).
            source = modes[source_mode].mode.source
            width, height, main = source.width, source.height, source.x == 0 and source.y == 0
        found.append({"width": int(width), "height": int(height), "hz": hz, "main": main})
    return found


def _display_settings():
    """The active displays from each one's current mode (EnumDisplayDevices, EnumDisplaySettings): whole hertz only."""
    import ctypes
    from ctypes import wintypes

    class Device(ctypes.Structure):
        _fields_ = (("size", wintypes.DWORD), ("name", wintypes.WCHAR * 32), ("string", wintypes.WCHAR * 128),
                    ("flags", wintypes.DWORD), ("id", wintypes.WCHAR * 128), ("key", wintypes.WCHAR * 128))

    class DevMode(ctypes.Structure):
        # DEVMODEW as far as the display's fields reach (the printer's union laid out as the display's: position,
        # orientation and output), then its rate.
        _fields_ = (("device_name", wintypes.WCHAR * 32), ("spec_version", wintypes.WORD),
                    ("driver_version", wintypes.WORD), ("size", wintypes.WORD), ("driver_extra", wintypes.WORD),
                    ("fields", wintypes.DWORD), ("x", wintypes.LONG), ("y", wintypes.LONG),
                    ("orientation", wintypes.DWORD), ("output", wintypes.DWORD), ("color", ctypes.c_short),
                    ("duplex", ctypes.c_short), ("y_resolution", ctypes.c_short), ("tt_option", ctypes.c_short),
                    ("collate", ctypes.c_short), ("form_name", wintypes.WCHAR * 32), ("log_pixels", wintypes.WORD),
                    ("bits_per_pel", wintypes.DWORD), ("width", wintypes.DWORD), ("height", wintypes.DWORD),
                    ("display_flags", wintypes.DWORD), ("frequency", wintypes.DWORD), ("rest", wintypes.DWORD * 8))

    user32 = ctypes.WinDLL("user32")
    attached, primary = 0x1, 0x4                        # DISPLAY_DEVICE_ATTACHED_TO_DESKTOP, _PRIMARY_DEVICE
    found, index = [], 0
    while True:
        device = Device()
        device.size = ctypes.sizeof(Device)
        if not user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
            break
        index += 1
        if not device.flags & attached:
            # A display adapter's output with nothing on it.
            continue
        mode = DevMode()
        mode.size = ctypes.sizeof(DevMode)
        # ENUM_CURRENT_SETTINGS: the mode the display is in now.
        if not user32.EnumDisplaySettingsW(device.name, -1, ctypes.byref(mode)):
            continue
        hz = mode.frequency if mode.frequency > 1 else None
        found.append({"width": int(mode.width), "height": int(mode.height), "hz": hz,
                      "main": bool(device.flags & primary)})
    return found


def highest_rate(found):
    """The highest refresh rate among `found` (connected()'s list), or None when none says its rate."""
    rates = [d["hz"] for d in found if d.get("hz")]
    return max(rates) if rates else None


def frame_limits(found):
    """The frame limits offered for the displays `found` (connected()'s list), as numbers in their order: every rate of
    RATES up to the highest display's rate (with MARGIN), and each display's own rate, so that a 160 Hz, 165 Hz or
    180 Hz display is offered its own. With no rate known, RATES up to 240."""
    top = highest_rate(found)
    if top is None:
        return [rate for rate in RATES if rate <= 240]
    offered = {rate for rate in RATES if rate <= top * MARGIN}
    # Each display's own rate, within the player's range.
    offered.update(d["hz"] for d in found if d.get("hz") and LEAST <= d["hz"] <= MOST)
    return sorted(offered)


def describe(found):
    """The displays as one line for the launcher's log: "2560 x 1440 at 165 Hz (main), 1920 x 1080 at 60 Hz"."""
    if not found:
        return "none listed by Windows"
    parts = []
    for d in found:
        rate = " at %d Hz" % d["hz"] if d.get("hz") else " at an unknown rate"
        parts.append("%d x %d%s%s" % (d["width"], d["height"], rate, " (main)" if d.get("main") else ""))
    return ", ".join(parts)
