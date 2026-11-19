"""The launcher's window keeps Windows' own title bar, drawn dark in the launcher's colours (titlebar.py): what DWM is
asked, as Windows 11, Windows 10 before and after 2004 and Wine answer it. DWM is a stand-in that records what it is
asked; nothing opens a window."""

import ctypes
import unittest
from unittest import mock

from opendmtq_client import frameless, theme, titlebar

# Tk's wrapper round the launcher's window, as frameless.py's tests name it.
HWND = 0x20062
# HRESULTs: done; an attribute this Windows does not know (Windows 10 for Windows 11's colours, or before 2004 for the
# dark form's number); Wine's DWM, which has nothing behind it.
S_OK, E_INVALIDARG, E_NOTIMPL = 0, -0x7FF8FFA9, -0x7FFFBFFF


class Dwmapi:
    """dwmapi answering each attribute as told (S_OK for any not told), recording what it was given."""

    def __init__(self, **answers):
        self.answers, self.calls = {int(k[1:]): v for k, v in answers.items()}, []

    def DwmSetWindowAttribute(self, hwnd, attribute, value, size):
        # The value as DWM reads it through the pointer it is given.
        self.calls.append((hwnd, attribute, value._obj.value, size))
        return self.answers.get(attribute, S_OK)


class Root:
    """The part of Tk's root titlebar.py asks for: its wrapper."""

    def wm_frame(self):
        # Tk's answer for its wrapper: hexadecimal.
        return "0x%x" % HWND


class Dark(unittest.TestCase):
    def test_the_bar_is_asked_dark_in_the_launchers_colours(self):
        # Windows 11: the dark form, then the bar in the column's strip, its words in the text's colour, the window's edge
        # in the seam, each a 4-byte value on Tk's wrapper (main asked nothing: Windows' light bar over the dark launcher).
        dwmapi = Dwmapi()
        said = titlebar.dark(Root(), dwmapi)
        self.assertEqual(dwmapi.calls, [(HWND, 20, 1, 4), (HWND, 35, titlebar.colorref(theme.STRIP), 4),
                                        (HWND, 36, titlebar.colorref(theme.TEXT), 4),
                                        (HWND, 34, titlebar.colorref(theme.SEAM), 4)])
        self.assertEqual(said, {"dark": S_OK, "caption": S_OK, "words": S_OK, "edge": S_OK})

    def test_a_colour_is_windows_colorref(self):
        # 0x00bbggrr: the strip #151a20 is 0x00201a15.
        self.assertEqual(titlebar.colorref("#151a20"), 0x00201A15)
        self.assertEqual(titlebar.colorref(theme.TEXT), 0x00F6F2EE)

    def test_windows_10_before_2004_knows_the_dark_form_by_its_older_number(self):
        # 20 unknown, 19 done; Windows 10 has no colours of its own for the bar: said, nothing raised.
        dwmapi = Dwmapi(a20=E_INVALIDARG, a34=E_INVALIDARG, a35=E_INVALIDARG, a36=E_INVALIDARG)
        with self.assertLogs("opendmtq_client", "INFO") as logged:
            said = titlebar.dark(Root(), dwmapi)
        self.assertEqual([call[1:3] for call in dwmapi.calls[:2]], [(20, 1), (19, 1)])
        self.assertEqual(said["dark"], S_OK)
        self.assertEqual(said["caption"], E_INVALIDARG)
        self.assertIn("caption %08x" % (E_INVALIDARG & 0xFFFFFFFF), "\n".join(logged.output))

    def test_windows_10_after_2004_asks_the_older_number_never(self):
        dwmapi = Dwmapi(a35=E_INVALIDARG)
        titlebar.dark(Root(), dwmapi)
        self.assertNotIn(19, [call[1] for call in dwmapi.calls])

    def test_wine_and_a_failing_call_leave_the_bar_as_it_is(self):
        # Wine's DWM answers E_NOTIMPL to all; a call that raises is said in the log; the window shows either way.
        said = titlebar.dark(Root(), Dwmapi(a19=E_NOTIMPL, a20=E_NOTIMPL, a34=E_NOTIMPL, a35=E_NOTIMPL, a36=E_NOTIMPL))
        self.assertEqual(said["dark"], E_NOTIMPL)
        broken = Dwmapi()
        broken.DwmSetWindowAttribute = mock.Mock(side_effect=OSError("no such call"))
        with self.assertLogs("opendmtq_client", "WARNING"):
            said = titlebar.dark(Root(), broken)
        self.assertEqual(set(said.values()), {None})

    def test_no_dwm_at_all_leaves_windows_own_bar(self):
        with mock.patch.object(frameless, "supported", return_value=True), \
                mock.patch.object(frameless, "_dwmapi", side_effect=OSError("no dwmapi.dll")):
            self.assertEqual(titlebar.dark(Root()), {"dwm": None})

    def test_off_windows_nothing_of_windows_is_asked(self):
        # Linux, where the tests and the UI checks run: no library loaded, nothing to draw.
        with mock.patch.object(frameless, "supported", return_value=False), \
                mock.patch.object(ctypes, "WinDLL", side_effect=AssertionError("asked Windows"), create=True):
            self.assertEqual(titlebar.dark(Root()), {})


class AskedBeforeTheWindowShows(unittest.TestCase):
    def test_the_launcher_and_its_dialogs_draw_the_bar_before_they_show(self):
        # The launcher's window and its own dialogs' windows (Cannot start, OpenDMTQ stopped) on Windows: out of sight
        # first, the bar asked dark once Tk's wrapper is made, then shown (set once a window is on screen, Windows draws
        # the bar as it was until the window is next activated).
        import inspect
        from opendmtq_client import app, dialogs
        for source in (inspect.getsource(app.LauncherApp.__init__), inspect.getsource(dialogs._dark_title_bar)):
            withdraw = source.find(".withdraw()") if ".withdraw()" in source else 0
            made = source.index("update_idletasks()")
            dark = source.index("titlebar.dark(")
            shown = source.index("deiconify()")
            self.assertLess(withdraw, made)
            self.assertLess(made, dark)
            self.assertLess(dark, shown)


if __name__ == "__main__":
    unittest.main()
