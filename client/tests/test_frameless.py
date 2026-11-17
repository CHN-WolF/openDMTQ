"""The installer's window without Windows' title bar (frameless.py): the styles it takes, the calls it makes to Windows
and to DWM, Windows' own move and minimise, and its buttons' pictures. Windows' libraries are stand-ins that record what
they are asked and answer as Windows 11, Windows 10 or Wine answer; nothing opens a window."""

import ctypes
import types
import unittest
from unittest import mock

from opendmtq_client import art, frameless, setup_window, theme, window_room

# Tk's wrapper round the installer's window as Wine reported it (tests/windows' probe of Tk 8.6.15): visible, clipping its
# children and siblings, a caption, the system menu and minimise, no sizing frame or maximise (Tk's window cannot be
# resized), and Tk's stray CS_DBLCLKS bit; its extended style WS_EX_WINDOWEDGE, which Windows gives a framed window.
TK_STYLE, TK_EX_STYLE = 0x16CA0008, 0x00000100
HWND = 0x20062
# HRESULTs: done; Windows 10 asked for rounded corners; Wine's DWM, which has nothing behind it.
S_OK, E_INVALIDARG, E_NOTIMPL = 0, -0x7FF8FFA9, -0x7FFFBFFF


class User32:
    """user32 as Windows answers the calls frameless.py makes, recording each one."""

    def __init__(self, style=TK_STYLE, ex_style=TK_EX_STYLE, button_down=True, keeps_caption=False):
        self.styles = {frameless.GWL_STYLE: style, frameless.GWL_EXSTYLE: ex_style}
        self.button_down, self.keeps_caption, self.calls = button_down, keeps_caption, []

    def GetWindowLongW(self, hwnd, index):
        self.calls.append(("GetWindowLongW", hwnd, index))
        # As Windows answers it: a signed LONG.
        return frameless._signed(self.styles[index])

    def SetWindowLongW(self, hwnd, index, value):
        self.calls.append(("SetWindowLongW", hwnd, index, value))
        if not self.keeps_caption:
            self.styles[index] = value & frameless.MASK
        return 1

    def SetWindowPos(self, *args):
        self.calls.append(("SetWindowPos",) + args)
        return 1

    def GetKeyState(self, key):
        self.calls.append(("GetKeyState", key))
        # The high bit of a SHORT while the button is down.
        return -32768 if self.button_down else 0

    def ReleaseCapture(self):
        self.calls.append(("ReleaseCapture",))
        return 1

    def SendMessageW(self, *args):
        self.calls.append(("SendMessageW",) + args)
        return 0

    def PostMessageW(self, *args):
        self.calls.append(("PostMessageW",) + args)
        return 1

    def SetWindowTextW(self, *args):
        self.calls.append(("SetWindowTextW",) + args)
        return 1

    def named(self, name):
        return [call for call in self.calls if call[0] == name]


class Dwmapi:
    """dwmapi answering each attribute and the frame's reach as told, recording what it was given."""

    def __init__(self, corners=S_OK, policy=S_OK, shadow=S_OK):
        self.answers, self.calls = {frameless.DWMWA_WINDOW_CORNER_PREFERENCE: corners,
                                    frameless.DWMWA_NCRENDERING_POLICY: policy}, []
        self.shadow = shadow

    def DwmSetWindowAttribute(self, hwnd, attribute, value, size):
        # The value as DWM reads it through the pointer it is given.
        self.calls.append(("DwmSetWindowAttribute", hwnd, attribute, value._obj.value, size))
        return self.answers[attribute]

    def DwmExtendFrameIntoClientArea(self, hwnd, margins):
        m = margins._obj
        self.calls.append(("DwmExtendFrameIntoClientArea", hwnd, (m.left, m.right, m.top, m.bottom)))
        return self.shadow


class Root:
    """The parts of Tk's root frameless.py asks for and sets."""

    def __init__(self, geometry="800x540+100+80"):
        self.places, self.iconified, self._geometry = [], 0, geometry

    def wm_frame(self):
        # Tk's answer for its wrapper: hexadecimal.
        return "0x%x" % HWND

    def geometry(self, text=None):
        if text is None:
            return self._geometry
        self.places.append(text)

    def winfo_rootx(self):
        return 103

    def winfo_rooty(self):
        return 109

    def iconify(self):
        self.iconified += 1


class Styles(unittest.TestCase):
    def test_the_title_bar_goes_and_the_rest_stays(self):
        style, ex_style = frameless.styles(TK_STYLE, TK_EX_STYLE)
        # No caption (neither its border nor its dialog frame), no sizing frame, no maximise.
        self.assertEqual(style & (frameless.WS_CAPTION | frameless.WS_THICKFRAME | frameless.WS_MAXIMIZEBOX), 0)
        # A pop-up with its system menu (Alt+F4, the taskbar's menu) and minimise (the taskbar's button).
        for bit in (frameless.WS_POPUP, frameless.WS_SYSMENU, frameless.WS_MINIMIZEBOX):
            self.assertEqual(style & bit, bit)
        # Everything else Tk gave it stays: visible, clipping, its stray class bit.
        self.assertEqual(style & 0x16000008, 0x16000008)
        # An application window, its taskbar button whatever it is; its edge as it was.
        self.assertEqual(ex_style, TK_EX_STYLE | frameless.WS_EX_APPWINDOW)

    def test_a_resizable_window_loses_its_frame_and_maximise_too(self):
        # A Tk window that can be resized has a sizing frame and maximise: both go with the caption.
        style, _ex = frameless.styles(0x16CF0008, 0)
        self.assertEqual(style & (frameless.WS_THICKFRAME | frameless.WS_MAXIMIZEBOX | frameless.WS_CAPTION), 0)

    def test_the_pop_up_style_goes_to_windows_as_a_long(self):
        style, _ex = frameless.styles(TK_STYLE, TK_EX_STYLE)
        # WS_POPUP is the sign bit: SetWindowLongW takes a signed LONG, which reads back as the same 32 bits.
        self.assertLess(frameless._signed(style), 0)
        self.assertEqual(frameless._signed(style) & frameless.MASK, style)


class Apply(unittest.TestCase):
    def test_the_caption_comes_off_tks_wrapper_and_the_window_keeps_its_size(self):
        user32, dwmapi = User32(), Dwmapi()
        self.assertTrue(frameless.apply(Root(), (800, 540, 100, 80), user32, dwmapi))
        style, ex_style = frameless.styles(TK_STYLE, TK_EX_STYLE)
        # Both styles set on Tk's wrapper, as signed LONGs.
        self.assertEqual(user32.named("SetWindowLongW"),
                         [("SetWindowLongW", HWND, frameless.GWL_STYLE, frameless._signed(style)),
                          ("SetWindowLongW", HWND, frameless.GWL_EXSTYLE, frameless._signed(ex_style))])
        # Then its frame worked out again, at the size and place that count no title bar, neither raised nor activated.
        self.assertEqual(user32.named("SetWindowPos"),
                         [("SetWindowPos", HWND, None, 100, 80, 800, 540,
                           frameless.SWP_FRAMECHANGED | frameless.SWP_NOZORDER | frameless.SWP_NOACTIVATE)])
        names = [call[0] for call in user32.calls]
        self.assertLess(names.index("SetWindowLongW"), names.index("SetWindowPos"))
        # The style read back last, without its caption.
        self.assertEqual(user32.calls[-1], ("GetWindowLongW", HWND, frameless.GWL_STYLE))

    def test_rounded_corners_and_the_shadow_are_asked_of_dwm(self):
        dwmapi = Dwmapi()
        frameless.apply(Root(), (800, 540, 100, 80), User32(), dwmapi)
        self.assertEqual(dwmapi.calls, [
            # Windows 11's rounded corners (DWMWCP_ROUND), a 4-byte value.
            ("DwmSetWindowAttribute", HWND, 33, 2, 4),
            # DWM drawing round a window with no frame of its own (DWMNCRP_ENABLED)...
            ("DwmSetWindowAttribute", HWND, 2, 2, 4),
            # ...and its frame 1 px into the window on every side: the shadow.
            ("DwmExtendFrameIntoClientArea", HWND, (1, 1, 1, 1))])

    def test_where_dwm_says_no_the_title_bar_goes_all_the_same(self):
        # Windows 10 (no rounded corners) and Wine (no DWM behind its calls): said in the log, nothing raised.
        for name, dwmapi in (("Windows 10", Dwmapi(corners=E_INVALIDARG)),
                             ("Wine", Dwmapi(corners=E_NOTIMPL, policy=E_NOTIMPL, shadow=E_NOTIMPL))):
            with self.subTest(name), self.assertLogs("opendmtq_client", "INFO") as said:
                user32 = User32()
                self.assertTrue(frameless.apply(Root(), (800, 540, 100, 80), user32, dwmapi))
                self.assertEqual(len(user32.named("SetWindowPos")), 1)
                self.assertIn("corners %08x" % (dwmapi.answers[33] & frameless.MASK), "\n".join(said.output))

    def test_no_dwm_at_all_leaves_a_square_window_without_a_title_bar(self):
        user32 = User32()
        with mock.patch.object(frameless, "_dwmapi", side_effect=OSError("no dwmapi.dll")):
            self.assertTrue(frameless.apply(Root(), (800, 540, 100, 80), user32))
        self.assertEqual(len(user32.named("SetWindowPos")), 1)

    def test_a_window_that_keeps_its_caption_says_so(self):
        # Windows refusing the new style: the caption reads back, and the window says it kept it.
        self.assertFalse(frameless.apply(Root(), (800, 540, 100, 80), User32(keeps_caption=True), Dwmapi()))

    def test_a_windows_without_the_calls_keeps_the_title_bar(self):
        user32 = User32()
        user32.GetWindowLongW = mock.Mock(side_effect=OSError("no such call"))
        with self.assertLogs("opendmtq_client", "WARNING"):
            self.assertFalse(frameless.apply(Root(), (800, 540, 100, 80), user32, Dwmapi()))
        self.assertEqual(user32.named("SetWindowLongW"), [])

    def test_off_windows_nothing_of_windows_is_asked(self):
        # Linux, where the tests run: no library loaded, nothing to take off.
        with mock.patch.object(frameless, "supported", return_value=False), \
                mock.patch.object(ctypes, "WinDLL", side_effect=AssertionError("asked Windows"), create=True):
            self.assertFalse(frameless.apply(Root(), (800, 540, 100, 80)))
            frameless.name(types.SimpleNamespace(winfo_id=lambda: 7), "Minimize")


class MoveAndMinimise(unittest.TestCase):
    def test_a_press_on_the_top_starts_windows_own_move(self):
        user32 = User32()
        event = types.SimpleNamespace(x_root=1500, y_root=-20)
        self.assertTrue(frameless.start_move(Root(), event, user32))
        # Tk's hold on the pointer let go first, then the press on the caption at the pointer's place (a display above
        # the main one: y below 0, packed in 16 bits as Windows packs it), posted: never sent from the press's handler,
        # where Windows' move loop would run Tk's timers inside it.
        self.assertEqual([call[0] for call in user32.calls], ["GetKeyState", "ReleaseCapture", "PostMessageW"])
        self.assertEqual(user32.calls[-1], ("PostMessageW", HWND, frameless.WM_NCLBUTTONDOWN, frameless.HTCAPTION,
                                            1500 | (0xFFEC << 16)))
        self.assertEqual(user32.named("SendMessageW"), [])

    def test_a_click_already_over_starts_no_move(self):
        user32 = User32(button_down=False)
        self.assertFalse(frameless.start_move(Root(), types.SimpleNamespace(x_root=10, y_root=10), user32))
        self.assertEqual(user32.named("PostMessageW") + user32.named("ReleaseCapture"), [])

    def test_minimise_is_the_title_bars_own_command(self):
        user32, root = User32(), Root()
        frameless.minimize(root, user32)
        self.assertEqual(user32.named("PostMessageW"),
                         [("PostMessageW", HWND, frameless.WM_SYSCOMMAND, frameless.SC_MINIMIZE, 0)])
        self.assertEqual(root.iconified, 0)
        # Elsewhere the window manager's own.
        with mock.patch.object(frameless, "supported", return_value=False):
            frameless.minimize(root)
        self.assertEqual(root.iconified, 1)

    def test_the_buttons_are_named_for_screen_readers(self):
        user32 = User32()
        frameless.name(types.SimpleNamespace(winfo_id=lambda: 0x3005C), "최소화", user32)
        self.assertEqual(user32.named("SetWindowTextW"), [("SetWindowTextW", 0x3005C, "최소화")])

    def test_off_windows_the_top_moves_the_window_by_its_geometry(self):
        root, bound = Root(), {}
        widget = types.SimpleNamespace(bind=lambda sequence, command, add=None: bound.setdefault(sequence, command))
        with mock.patch.object(frameless, "supported", return_value=False):
            mover = frameless.Mover(root)
            mover.bind(widget, where=lambda e: e.y_root < 150)
            # A press below the top moves nothing.
            self.assertIsNone(bound["<ButtonPress-1>"](types.SimpleNamespace(x_root=300, y_root=400)))
            bound["<B1-Motion>"](types.SimpleNamespace(x_root=340, y_root=430))
            self.assertEqual(root.places, [])
            # One on it: the window follows the pointer from where its geometry put it.
            self.assertEqual(bound["<ButtonPress-1>"](types.SimpleNamespace(x_root=300, y_root=100)), "break")
            bound["<B1-Motion>"](types.SimpleNamespace(x_root=340, y_root=130))
            bound["<ButtonRelease-1>"](types.SimpleNamespace(x_root=340, y_root=130))
            bound["<B1-Motion>"](types.SimpleNamespace(x_root=400, y_root=200))
        self.assertEqual(root.places, ["+140+110"])

    def test_on_windows_the_top_hands_the_move_to_windows(self):
        root, bound, user32 = Root(), {}, User32()
        widget = types.SimpleNamespace(bind=lambda sequence, command, add=None: bound.setdefault(sequence, command))
        frameless.Mover(root, user32).bind(widget)
        bound["<ButtonPress-1>"](types.SimpleNamespace(x_root=300, y_root=100))
        bound["<B1-Motion>"](types.SimpleNamespace(x_root=340, y_root=130))
        # Windows moves the window itself; Tk's geometry is not touched.
        self.assertEqual(len(user32.named("PostMessageW")), 1)
        self.assertEqual(root.places, [])

    def test_the_place_a_geometry_gives(self):
        self.assertEqual(frameless.place(Root("800x540+100+80")), (100, 80))
        # Tk writes a place left of or above the screen as "+-10".
        self.assertEqual(frameless.place(Root("800x540+-10+-4")), (-10, -4))
        # Counted from the right or the foot: where the window is on the screen.
        self.assertEqual(frameless.place(Root("800x540-0+20")), (103, 109))


class Placement(unittest.TestCase):
    def test_the_installer_counts_no_title_bar(self):
        # An 800x480 screen with a 40 px taskbar, where Windows' caption and frame took 31 px: the window has none now,
        # so it takes the room's whole share (404 px) and stays above the taskbar.
        with mock.patch.object(window_room, "work_area", return_value=(0, 0, 800, 440)), \
                mock.patch.object(window_room, "title_bar_height", return_value=31):
            w, h, x, y = setup_window.placement(object(), lambda n: n)
        self.assertEqual((w, h), (736, 404))
        self.assertLessEqual(y + h, 440)


class Pictures(unittest.TestCase):
    """The buttons' pictures (art.window_button) at 100 % and at 200 %."""

    @staticmethod
    def near(pixel, colour, slack=6):
        return all(abs(a - b) <= slack for a, b in zip(pixel, art._rgb(colour)))

    def test_quiet_metal_with_its_glyph_never_lime(self):
        for scale in (1.0, 2.0):
            size = int(round(32 * scale))
            for glyph in ("minimize", "close"):
                for state in ("normal", "hover", "pressed"):
                    for focused in (False, True):
                        face = art.window_button(size, glyph, state, focused, scale, bg=theme.BG)
                        with self.subTest(scale=scale, glyph=glyph, state=state, focused=focused):
                            self.assertEqual(face.size, (size, size))
                            # Never the lime of a main button, anywhere on it.
                            self.assertFalse(any(self.near(p, theme.OK, 40) for p in face.getdata()))

    def test_close_turns_red_under_the_pointer_and_minimise_stays_metal(self):
        # A point of the face away from its glyph and its edges' light and shade.
        at = (9, 20)
        rest = art.window_button(32, "close", "normal", False, bg=theme.BG)
        self.assertTrue(self.near(rest.getpixel(at), theme.RAIL_UP))
        self.assertTrue(self.near(art.window_button(32, "close", "hover", False, bg=theme.BG).getpixel(at), theme.BAD))
        self.assertTrue(self.near(art.window_button(32, "minimize", "hover", False, bg=theme.BG).getpixel(at),
                                  art.BUTTON_LOOKS["neutral"]["hover"][0]))

    def test_the_glyphs_quiet_at_rest_bright_under_the_pointer(self):
        # The minimise bar's middle, and the X's crossing.
        self.assertTrue(self.near(art.window_button(32, "minimize", "normal", False, bg=theme.BG).getpixel((16, 16)),
                                  theme.MUTED))
        self.assertTrue(self.near(art.window_button(32, "minimize", "hover", False, bg=theme.BG).getpixel((16, 16)),
                                  theme.TEXT))
        self.assertTrue(self.near(art.window_button(32, "close", "hover", False, bg=theme.BG).getpixel((16, 16)),
                                  art.BUTTON_LOOKS["danger_quiet"]["hover_text"], 30))

    def test_the_keyboards_ring_shows(self):
        ringed = art.window_button(32, "minimize", "normal", True, bg=theme.BG)
        plain = art.window_button(32, "minimize", "normal", False, bg=theme.BG)
        cyan = [p for p in ringed.getdata() if self.near(p, theme.CYAN, 30)]
        self.assertGreater(len(cyan), 40)
        self.assertFalse([p for p in plain.getdata() if self.near(p, theme.CYAN, 30)])

    def test_the_cut_corners_show_what_lies_under(self):
        # Under it a lime shard of the page's picture: its top-left corner, cut, shows it.
        under = art.Image.new("RGB", (32, 32), art._rgb("#5a9a2a"))
        face = art.window_button(32, "close", "normal", False, under=under)
        self.assertEqual(face.getpixel((0, 0)), art._rgb("#5a9a2a"))
        self.assertEqual(face.getpixel((31, 31)), art._rgb("#5a9a2a"))


if __name__ == "__main__":
    unittest.main()
