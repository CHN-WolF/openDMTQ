"""The PC's displays, for the Screen page: the main display's size in pixels and Windows' scale on it, so the page can
leave out window sizes larger than it or smaller than the game's window holds there, and each connected display's
refresh rates, so that the frame limits go up to the fastest rate any display runs at.

A display's rate now is not what it can run at. With Windows 11's dynamic refresh rate (DRR, "Dynamic" in Advanced
display) a 120, 165 or 180 Hz laptop or tablet panel runs at 60 Hz while the desktop is still, and Windows' current mode
says 60 (GDI's VREFRESH, which 0.10.0 read, and EnumDisplaySettings' current mode alike); 0.10.0 then offered no frame
limit above 60 with VSync on. So for each display this reads its modes, and takes the highest rate among the modes at
its current resolution as the rate it runs at when a game asks (the player asks Windows for the panel's full rate):

  current   the rate of the mode it is in now (Windows' display configuration, as a fraction: 179.999 is 180)
  top       the highest rate of its modes at its current size, never below the current one
  drr       True when Windows says its rate is divided now (dynamic refresh rate), False when it says it is not, None
            when this Windows says nothing of it

On Windows from EnumDisplayDevices and EnumDisplaySettings (each display, its current mode and all its modes) with
QueryDisplayConfig (the current rate as a fraction, and its divider); elsewhere (development and the tests) Tk's screen
size and no rate. OPENDMTQ_DISPLAYS makes displays up for the tests and the pictures (made_up).
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
# The most modes read of one display (a driver lists a few hundred at most; the loop ends at the first missing one).
MODES_READ = 4096


def main_display(root=None):
    """{"width", "height", "hz", "top", "scale"} of the main display: hz its rate now and top the highest rate of its
    modes at its size (None when the system does not say), scale 1.0 (100 %) when it cannot be told."""
    if os.environ.get("OPENDMTQ_DISPLAYS") is not None:
        # Made-up displays (the tests and the pictures): the main one's size and rates, at 100 %.
        listed = [d for d in connected() if d.get("main")]
        if listed:
            main = listed[0]
            return {"width": main["width"], "height": main["height"], "hz": main["hz"], "top": main["top"],
                    "scale": 1.0}
    if sys.platform == "win32":
        found = _gdi_main()
        if found is not None:
            # The main display's rates from its modes and Windows' display configuration where they say them: GDI's
            # VREFRESH is the rate now in whole hertz (164 for 164.999, 60 for a dynamic 180 Hz panel at rest).
            listed = [d for d in connected() if d.get("main")]
            if listed:
                found["hz"] = listed[0]["hz"] or found["hz"]
                found["top"] = listed[0]["top"] or found["hz"]
            return found
    if root is not None:
        return {"width": root.winfo_screenwidth(), "height": root.winfo_screenheight(), "hz": None, "top": None,
                "scale": 1.0}
    return {"width": 0, "height": 0, "hz": None, "top": None, "scale": 1.0}


def _gdi_main():
    """The main display from GDI (its own pixels, its rate now, Windows' scale on it), or None without GDI."""
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
            # and its rate now in whole hertz.
            width, height, hz = gdi32.GetDeviceCaps(dc, 118), gdi32.GetDeviceCaps(dc, 117), gdi32.GetDeviceCaps(dc, 116)
            # Windows' scale on it, the same with DPI awareness (the launcher's window: LOGPIXELSX is the display's dots
            # per inch) and without (the command line: LOGPIXELSX says 96, and HORZRES the display shrunk by the scale):
            # whichever of the two says more.
            logical_dpi, logical_width = gdi32.GetDeviceCaps(dc, 88), gdi32.GetDeviceCaps(dc, 8)
        finally:
            user32.ReleaseDC(None, dc)
        scale = max(logical_dpi / 96.0 if logical_dpi > 0 else 1.0, width / float(logical_width) if logical_width > 0 else 1.0)
        # 0 and 1 mean the hardware's default rate, which says nothing.
        hz = hz if hz > 1 else None
        return {"width": width, "height": height, "hz": hz, "top": hz, "scale": round(max(1.0, scale), 3)}
    except (AttributeError, OSError):
        # No GDI to ask (a stripped-down Windows).
        return None


def connected():
    """Every active display as [{"name", "width", "height", "hz", "top", "drr", "main"}] (the module's words say what
    each is), the main one first; [] where the system does not say (not Windows, or nothing to ask). Never raises: a
    display that cannot be read is left out, and the page then offers what it offers without a rate."""
    named = os.environ.get("OPENDMTQ_DISPLAYS")
    if named is not None:
        # Made-up displays for the tests and the pictures.
        return made_up(named)
    if sys.platform != "win32":
        return []
    try:
        found = _windows_displays()
    except (AttributeError, OSError, ValueError):
        # A Windows (or a Wine) without these calls: nothing said of the displays, as off Windows.
        log.debug("could not read the displays", exc_info=True)
        return []
    # The main display first: the page's words about "this display" are about it.
    return sorted(found, key=lambda d: not d["main"])


def whole_hz(numerator, denominator):
    """A rate given as a fraction (Windows' display configuration: 164999/1000) in whole hertz (165); None for none."""
    if not denominator or not numerator:
        return None
    hz = numerator / float(denominator)
    # 0 and 1 are a mode with no rate of its own; a rate rounds to the nearest whole hertz, 59.94 to 60.
    return int(round(hz)) if hz > 1.5 else None


def summarise(name, width, height, current, modes, divider=None, main=False):
    """One display as connected() lists it, from what Windows says of it: its size now, its rate now (`current`, in hertz,
    a fraction allowed), its modes [(width, height, hertz)], and the divider of its rate now (None where Windows says
    nothing of it). Its top rate is the highest of its modes at its size now, never below the rate now."""
    now = whole_hz(int(round(float(current) * 1000)), 1000) if current else None
    at_size = [whole_hz(int(round(float(hz) * 1000)), 1000) for w, h, hz in modes if (w, h) == (width, height) and hz]
    rates = [rate for rate in at_size + [now] if rate]
    top = max(rates) if rates else None
    drr = None if not divider else divider > 1
    return {"name": name, "width": int(width), "height": int(height), "hz": now, "top": top, "drr": drr,
            "main": bool(main)}


def made_up(text):
    """Displays written as "2560x1600@60~180d*,1920x1080@60" as connected() lists them, the main one first: each
    WIDTHxHEIGHT@HZ (its rate now, a fraction allowed), then ~TOP (the highest rate of its modes at that size, when it is
    more), then d or f (dynamic refresh rate on or off; neither: not said), then * after the main one. A part that is
    not one is left out."""
    found = []
    for i, part in enumerate(text.split(",")):
        match = re.match(r"^\s*(\d+)x(\d+)@(\d+(?:\.\d+)?)(?:~(\d+(?:\.\d+)?))?([df]?)(\*?)\s*$", part)
        if not match:
            continue
        width, height = int(match.group(1)), int(match.group(2))
        current, top = float(match.group(3)), match.group(4)
        modes = [(width, height, current)] + ([(width, height, float(top))] if top else [])
        divider = {"d": 2, "f": 1}.get(match.group(5))
        found.append(summarise("\\\\.\\DISPLAY%d" % (i + 1), width, height, current, modes, divider,
                               main=bool(match.group(6))))
    return sorted(found, key=lambda d: not d["main"])


def _windows_displays():
    """The active displays as Windows says them: each attached display device (EnumDisplayDevices), its current mode
    and every mode it lists (EnumDisplaySettings), and from Windows' display configuration (QueryDisplayConfig) its rate
    now as a fraction and that rate's divider, matched by the device's name."""
    import ctypes
    from ctypes import wintypes

    class Device(ctypes.Structure):
        _fields_ = (("size", wintypes.DWORD), ("name", wintypes.WCHAR * 32), ("string", wintypes.WCHAR * 128),
                    ("flags", wintypes.DWORD), ("id", wintypes.WCHAR * 128), ("key", wintypes.WCHAR * 128))

    class DevMode(ctypes.Structure):
        # DEVMODEW as far as the display's fields reach (the printer's union laid out as the display's: position,
        # orientation and output), then its rate, then the rest of its 220 bytes.
        _fields_ = (("device_name", wintypes.WCHAR * 32), ("spec_version", wintypes.WORD),
                    ("driver_version", wintypes.WORD), ("size", wintypes.WORD), ("driver_extra", wintypes.WORD),
                    ("fields", wintypes.DWORD), ("x", wintypes.LONG), ("y", wintypes.LONG),
                    ("orientation", wintypes.DWORD), ("output", wintypes.DWORD), ("color", ctypes.c_short),
                    ("duplex", ctypes.c_short), ("y_resolution", ctypes.c_short), ("tt_option", ctypes.c_short),
                    ("collate", ctypes.c_short), ("form_name", wintypes.WCHAR * 32), ("log_pixels", wintypes.WORD),
                    ("bits_per_pel", wintypes.DWORD), ("width", wintypes.DWORD), ("height", wintypes.DWORD),
                    ("display_flags", wintypes.DWORD), ("frequency", wintypes.DWORD), ("rest", wintypes.DWORD * 8))

    # Windows' own sizes for these: a mismatch would read garbage, so it is refused before any call.
    if ctypes.sizeof(DevMode) != 220 or ctypes.sizeof(Device) != 840:
        raise ValueError("display structures of unexpected size")
    user32 = ctypes.WinDLL("user32")
    attached, primary = 0x1, 0x4                        # DISPLAY_DEVICE_ATTACHED_TO_DESKTOP, _PRIMARY_DEVICE
    current_settings = -1                               # ENUM_CURRENT_SETTINGS
    fractions = _display_config()
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
        if not user32.EnumDisplaySettingsW(device.name, current_settings, ctypes.byref(mode)):
            continue
        # Every mode the display lists, its size and rate (the same size at other rates among them).
        modes, number = [], 0
        while number < MODES_READ:
            listed = DevMode()
            listed.size = ctypes.sizeof(DevMode)
            if not user32.EnumDisplaySettingsW(device.name, number, ctypes.byref(listed)):
                break
            modes.append((int(listed.width), int(listed.height), int(listed.frequency)))
            number += 1
        # The rate now as a fraction and its divider, from the display configuration where it names this device.
        fraction, divider = fractions.get(device.name, (None, None))
        current = fraction or (mode.frequency if mode.frequency > 1 else None)
        found.append(summarise(device.name, mode.width, mode.height, current, modes, divider,
                               main=bool(device.flags & primary)))
    return found


def _display_config():
    """{GDI device name: (rate now in hertz as a fraction, its divider or None)} from Windows' display configuration
    (QueryDisplayConfig with QDC_ONLY_ACTIVE_PATHS, each path's source named by DisplayConfigGetDeviceInfo); {} where
    Windows has none of it (an older one, Wine without it)."""
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

    class Signal(ctypes.Structure):
        # DISPLAYCONFIG_VIDEO_SIGNAL_INFO: its "standard" is a union whose bits 16 to 21 are, on Windows 11, the divider
        # of the rate the display runs at now (vSyncFreqDivider).
        _fields_ = (("pixel_rate", ctypes.c_uint64), ("h_sync", Rational), ("v_sync", Rational),
                    ("active", ctypes.c_uint32 * 2), ("total", ctypes.c_uint32 * 2), ("standard", ctypes.c_uint32),
                    ("scan_order", ctypes.c_uint32))

    class ModeUnion(ctypes.Union):
        # The target's signal is the largest member (48 bytes): the union is that size whatever the mode is.
        _fields_ = (("target", Signal), ("room", ctypes.c_byte * 48))

    class Mode(ctypes.Structure):
        _fields_ = (("kind", ctypes.c_uint32), ("id", ctypes.c_uint32), ("adapter", Luid), ("mode", ModeUnion))

    class Header(ctypes.Structure):
        _fields_ = (("type", ctypes.c_uint32), ("size", ctypes.c_uint32), ("adapter", Luid), ("id", ctypes.c_uint32))

    class SourceName(ctypes.Structure):
        _fields_ = (("header", Header), ("name", wintypes.WCHAR * 32))

    # The sizes Windows lays these out in: a mismatch would read garbage, so it is refused before any call.
    if ctypes.sizeof(Path) != 72 or ctypes.sizeof(Mode) != 64 or ctypes.sizeof(SourceName) != 84:
        return {}
    try:
        user32 = ctypes.WinDLL("user32")
        query, sizes, info = user32.QueryDisplayConfig, user32.GetDisplayConfigBufferSizes, user32.DisplayConfigGetDeviceInfo
    except (AttributeError, OSError):
        return {}
    only_active = 2                                     # QDC_ONLY_ACTIVE_PATHS
    paths_n, modes_n = ctypes.c_uint32(), ctypes.c_uint32()
    for _ in range(3):
        # The counts can grow between the two calls (a display plugged in): asked again then.
        if sizes(only_active, ctypes.byref(paths_n), ctypes.byref(modes_n)):
            return {}
        paths, modes = (Path * paths_n.value)(), (Mode * modes_n.value)()
        status = query(only_active, ctypes.byref(paths_n), paths, ctypes.byref(modes_n), modes, None)
        if status == 0:
            break
        if status != 122:                               # ERROR_INSUFFICIENT_BUFFER: asked again
            return {}
    else:
        return {}
    found = {}
    for path in paths[:paths_n.value]:
        source = SourceName()
        source.header.type = 1                          # DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME
        source.header.size = ctypes.sizeof(SourceName)
        source.header.adapter = path.source.adapter
        source.header.id = path.source.id
        if info(ctypes.byref(source.header)) != 0:
            continue
        rate = path.target.rate
        hz = rate.numerator / float(rate.denominator) if rate.denominator else None
        divider = None
        target_mode = path.target.mode_index
        if target_mode < modes_n.value and modes[target_mode].kind == 2:
            # DISPLAYCONFIG_MODE_INFO_TYPE_TARGET: its signal, the divider of its rate now where Windows says one.
            signal = modes[target_mode].mode.target
            divider = (signal.standard >> 16) & 0x3F or None
            if not hz and signal.v_sync.denominator:
                hz = signal.v_sync.numerator / float(signal.v_sync.denominator)
        found[source.name] = (hz if hz and hz > 1.5 else None, divider)
    return found


def highest_rate(found):
    """The highest rate any of `found` (connected()'s list) runs at when a game asks: its top rate, or None when none
    says its rate."""
    rates = [d.get("top") or d.get("hz") for d in found]
    rates = [rate for rate in rates if rate]
    return max(rates) if rates else None


def frame_limits(found):
    """The frame limits offered for the displays `found` (connected()'s list), as numbers in their order: every rate of
    RATES up to the highest rate any display runs at (with MARGIN), and each display's own rates, now and at its top, so
    that a 160, 165 or 180 Hz panel is offered its own even while Windows runs it at 60. With no rate known, RATES up to
    240."""
    top = highest_rate(found)
    if top is None:
        return [rate for rate in RATES if rate <= 240]
    offered = {rate for rate in RATES if rate <= top * MARGIN}
    # Each display's own rates, within the player's range.
    for d in found:
        offered.update(rate for rate in (d.get("hz"), d.get("top")) if rate and LEAST <= rate <= MOST)
    return sorted(offered)


def describe(found):
    """The displays for the launcher's log, one a line: "\\\\.\\DISPLAY1 (main): 2560 x 1600, now 60 Hz, up to 180 Hz at
    this size, dynamic refresh rate on"."""
    if not found:
        return ["none listed by Windows"]
    lines = []
    for d in found:
        now = "now %d Hz" % d["hz"] if d.get("hz") else "now at a rate not said"
        top = "up to %d Hz at this size" % d["top"] if d.get("top") else "no other rate listed"
        drr = {True: "dynamic refresh rate on", False: "dynamic refresh rate off", None: "dynamic refresh rate not said"}
        lines.append("%s%s: %d x %d, %s, %s, %s" % (d.get("name") or "a display", " (main)" if d.get("main") else "",
                                                   d["width"], d["height"], now, top, drr[d.get("drr")]))
    return lines
