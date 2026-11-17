"""The PC settings: their choices, their defaults, and the settings file the player reads."""

import os
import re
import unittest

from opendmtq_client import values as choices

# The player's own reader of the settings file: its keys and values are what this file must agree with.
SETTINGS_CPP = os.path.join(os.path.dirname(__file__), "..", "..", "arm32", "desktop", "settings.cpp")


class Values(unittest.TestCase):
    def test_defaults_fill_everything(self):
        filled = choices.normalize({})
        # Every setting the launcher keeps: the player's, and the counter's corner, which no key of the player's names.
        self.assertEqual(set(filled), set(choices.NAMES))
        self.assertEqual(set(choices.NAMES) - set(choices.ORDER), {"fps_position"})
        self.assertEqual(filled["display"], "fullscreen")
        self.assertEqual(filled["volume"], 100)

    def test_choices_are_checked(self):
        self.assertEqual(choices.normalize({"fps": "240"})["fps"], "240")
        self.assertEqual(choices.normalize({"vsync": "OFF"})["vsync"], "off")
        # Any whole number of frames in the player's range (160, 165 and 180 Hz displays' own rates among them), auto and
        # no limit; nothing outside it, nothing that is no whole number.
        for value in ("160", "165", "180", "241", "30", "1000", "0165"):
            self.assertEqual(choices.normalize({"fps": value})["fps"], str(int(value)))
        for name, value in (("fps", "29"), ("fps", "1001"), ("fps", "60.5"), ("fps", "fast"), ("vsync", "maybe"), ("render_scale", "25"), ("volume", "101"),
                            ("volume", "loud"), ("window", "100x100"), ("audio_device", "a\nb"), ("nothing", "1")):
            with self.assertRaises(choices.ChoiceError, msg=(name, value)):
                choices.normalize({name: value})

    def test_upscaler_and_anti_aliasing(self):
        # NVIDIA Image Scaling below 100 % by default (the nearest to the native picture as the player measured the
        # three), and no anti-aliasing (the game's picture as it draws it).
        filled = choices.normalize({})
        self.assertEqual((filled["upscaler"], filled["anti_aliasing"]), ("fsr1", "off"))
        # Each offered value is kept, in any case; the temporal ones and FXAA are not offered.
        self.assertEqual(choices.normalize({"upscaler": "FSR1"})["upscaler"], "fsr1")
        self.assertEqual(choices.normalize({"anti_aliasing": "SMAA"})["anti_aliasing"], "smaa")
        for name, value in (("upscaler", "dlss"), ("upscaler", "fsr2"), ("anti_aliasing", "taa"), ("anti_aliasing", "fxaa"),
                            ("anti_aliasing", "msaa16")):
            with self.assertRaises(choices.ChoiceError, msg=(name, value)):
                choices.normalize({name: value})
        # MSAA is no choice any more (it left the game's picture as it was): what an earlier launcher kept, and --set as
        # before, read as CMAA 2, kept or not strict, and the player's file says cmaa2.
        self.assertEqual(choices.ANTI_ALIASING, ("off", "cmaa2", "smaa"))
        for old in ("msaa2", "msaa4", "MSAA8"):
            self.assertEqual(choices.normalize({"anti_aliasing": old})["anti_aliasing"], "cmaa2", old)
            self.assertEqual(choices.normalize({"anti_aliasing": old}, strict=False)["anti_aliasing"], "cmaa2", old)
        self.assertIn("anti_aliasing=cmaa2", choices.settings_text({"anti_aliasing": "msaa4"}).splitlines())

    def test_the_frame_counter(self):
        # Off by default, its corner the bottom right; on and off by name, in any case.
        filled = choices.normalize({})
        self.assertEqual((filled["show_fps"], filled["fps_position"]), ("off", "bottom_right"))
        self.assertEqual(choices.normalize({"show_fps": "ON"})["show_fps"], "on")
        # Its corner kept while it is off, for the next time it is on.
        kept = choices.normalize({"show_fps": "off", "fps_position": "top_right"})
        self.assertEqual((kept["show_fps"], kept["fps_position"]), ("off", "top_right"))
        # A corner as show_fps's value (an older launcher's file, --set as before): on, in that corner.
        for corner in ("top_left", "top_right", "bottom_left", "bottom_right"):
            filled = choices.normalize({"show_fps": corner.upper(), "fps_position": "top_left"})
            self.assertEqual((filled["show_fps"], filled["fps_position"]), ("on", corner))
        # A place that is no corner refused, for either.
        for name, value in (("show_fps", "middle"), ("fps_position", "middle"), ("fps_position", "on")):
            with self.assertRaises(choices.ChoiceError, msg=(name, value)):
                choices.normalize({name: value})
        # The player's file names the corner while it is on, off while it is not.
        def counter_line(values):
            return [line for line in choices.settings_text(values).splitlines() if line.startswith("show_fps=")]
        self.assertEqual(counter_line({}), ["show_fps=off"])
        self.assertEqual(counter_line({"show_fps": "on"}), ["show_fps=bottom_right"])
        self.assertEqual(counter_line({"show_fps": "on", "fps_position": "bottom_left"}), ["show_fps=bottom_left"])
        self.assertEqual(counter_line({"show_fps": "off", "fps_position": "bottom_left"}), ["show_fps=off"])
        self.assertNotIn("fps_position", choices.settings_text({"show_fps": "on"}))

    def test_a_bad_value_keeps_the_default_when_not_strict(self):
        filled = choices.normalize({"fps": "1001", "volume": 40}, strict=False)
        self.assertEqual(filled["fps"], "auto")
        self.assertEqual(filled["volume"], 40)

    def test_window_sizes(self):
        self.assertEqual(choices.normalize({"window": "1920X1080"})["window"], "1920x1080")
        # The smallest area the player's window holds, 480x270: smaller is refused (the player would not take it).
        self.assertEqual(choices.normalize({"window": "480x270"})["window"], "480x270")
        for small in ("320x180", "479x270", "480x269"):
            with self.assertRaises(choices.ChoiceError, msg=small):
                choices.normalize({"window": small})
        with self.assertRaises(choices.ChoiceError) as refused:
            choices.normalize({"window": "320x180"})
        self.assertIn("480x270 or more", str(refused.exception))
        self.assertEqual(choices.size_of("1280x720"), (1280, 720))
        self.assertIsNone(choices.size_of("auto"))

    def test_window_sizes_at_windows_scale(self):
        # The smallest game area the player's window holds is 480x270 at Windows' scale (arm32/desktop/overlay_scale.h):
        # whole pixels, never fewer than the scale gives (270 at 125 % is 338).
        for scale, least in ((1.0, (480, 270)), (1.25, (600, 338)), (1.5, (720, 405)), (2.0, (960, 540)), (3.0, (1440, 810))):
            self.assertEqual(choices.smallest_on({"scale": scale}), least, scale)
        # No scale known: 100 %.
        self.assertEqual(choices.smallest_on({}), (480, 270))
        # A 4K display at 300 %: 1280x720 would open at 1440x810, so the Screen page leaves it out and --set refuses it;
        # the next size up and fitted stay.
        uhd = {"width": 3840, "height": 2160, "hz": 60, "scale": 3.0}
        self.assertTrue(choices.too_small("1280x720", uhd))
        self.assertFalse(choices.fits("1280x720", uhd))
        self.assertTrue(choices.fits("1600x900", uhd))
        self.assertTrue(choices.fits("auto", uhd))
        self.assertFalse(choices.too_small("auto", uhd))
        # At 200 % no size the page lists is too small (the smallest there is 960x540); 3840x2160 still goes for want of
        # room for the title bar.
        self.assertFalse(any(choices.too_small(s, dict(uhd, scale=2.0)) for s in choices.WINDOW_SIZES))
        self.assertFalse(choices.fits("3840x2160", dict(uhd, scale=2.0)))
        # The display's size unknown: the smallest is still the scale's.
        self.assertFalse(choices.fits("1280x720", {"width": 0, "height": 0, "scale": 3.0}))
        self.assertTrue(choices.fits("3840x2160", {"width": 0, "height": 0, "scale": 3.0}))

    def test_vsync_pacing_is_the_players(self):
        # The refreshes a frame stays for with VSync, as the player's pacing_math.h has them (its own test's cases):
        # every refresh without a limit or at the rate and above, a whole fraction near the limit, else by the clock.
        cases = [(60.0, "60", 1), (59.94, "60", 1), (60.0, "120", 1), (144.0, "144", 1), (180.0, "240", 1),
                 (240.084, "240", 1), (240.084, "120", 2), (240.084, "60", 4), (144.0, "72", 2), (180.0, "60", 3),
                 (165.0, "60", 3), (360.0, "120", 3), (360.0, "180", 2), (120.0, "60", 2), (240.084, "130", 2),
                 (240.084, "144", 0), (144.0, "120", 0), (144.0, "60", 0), (165.0, "144", 0), (180.0, "144", 0),
                 (360.0, "240", 0), (144, "auto", 1), (144, "unlimited", 1)]
        for hz, fps, want in cases:
            self.assertEqual(choices.vsync_refreshes(hz, fps), want, (hz, fps))
        # Above the rate (the same 3 % margin): no limit, a number past it; not auto, not a rate a little under 144.
        self.assertTrue(choices.above_rate(144, "165"))
        self.assertTrue(choices.above_rate(60, "unlimited"))
        self.assertFalse(choices.above_rate(143, "144"))
        self.assertFalse(choices.above_rate(144, "auto"))
        self.assertFalse(choices.above_rate(None, "360"))

    def test_the_frame_limits_offered_and_their_words(self):
        # Every rate up to the fastest connected display's, each display's own rate among them, whatever VSync says;
        # the display's own rate first and no limit last; a limit kept from before keeps its row. Made-up displays.
        from opendmtq_client import displays, i18n, pages

        def offered(*rates):
            found = [{"width": 1920, "height": 1080, "hz": hz, "main": i == 0} for i, hz in enumerate(rates)]
            return pages.fps_choices(found, "auto")

        self.assertEqual(offered(60), ["auto", "30", "60", "unlimited"])
        self.assertEqual(offered(144), ["auto", "30", "60", "75", "90", "100", "120", "144", "unlimited"])
        for hz in (160, 165, 180, 240):
            limits = offered(hz)
            # The display's own rate is there, and nothing above it.
            self.assertIn(str(hz), limits, hz)
            self.assertEqual(max(int(f) for f in limits if f.isdigit()), hz, hz)
        self.assertIn("170", offered(180))
        # Mixed displays: up to the fastest, with each display's own (a 60 Hz main beside a 180 Hz touch screen, a
        # 165 Hz beside a 144 Hz).
        mixed = offered(60, 180)
        self.assertIn("180", mixed)
        self.assertIn("144", mixed)
        self.assertNotIn("200", mixed)
        self.assertIn("165", offered(144, 165))
        # A display's own odd rate (a 59.94 Hz and a 164.999 Hz display read as 60 and 165).
        self.assertEqual(displays.whole_hz(59940, 1000), 60)
        self.assertEqual(displays.whole_hz(164999, 1000), 165)
        self.assertIsNone(displays.whole_hz(1, 1))
        self.assertIsNone(displays.whole_hz(0, 0))
        self.assertIn("165", offered(144, displays.whole_hz(164999, 1000)))
        # No rate known: the common ones up to 240.
        self.assertEqual(pages.fps_choices([], "auto")[-2:], ["240", "unlimited"])
        # A limit set on the command line keeps its row.
        self.assertEqual(pages.fps_choices([{"width": 1, "height": 1, "hz": 60, "main": True}], "240")[-1], "240")
        # Made-up displays as the tests and the pictures name them.
        found = displays.made_up("1920x1080@60,2560x1440@164.999*,bad")
        self.assertEqual([(d["hz"], d["main"]) for d in found], [(165, True), (60, False)])
        self.assertEqual(displays.describe(found), [
            "\\\\.\\DISPLAY2 (main): 2560 x 1440, now 165 Hz, up to 165 Hz at this size, dynamic refresh rate not said",
            "\\\\.\\DISPLAY1: 1920 x 1080, now 60 Hz, up to 60 Hz at this size, dynamic refresh rate not said"])
        # The hints name one rate only when every display has it.
        self.assertEqual(pages.single_rate(found, 165), None)
        self.assertEqual(pages.single_rate(found[:1], 165), 165)
        w = i18n.Words("en")
        self.assertEqual(pages.fps_hint(w, True, "72", 144), "On this 144 Hz display: 72 fps exactly.")
        self.assertEqual(pages.fps_hint(w, True, "60", 144), "On this 144 Hz display: very nearly 60 fps.")
        self.assertEqual(pages.fps_hint(w, True, "130", 240), "On this 240 Hz display: 120 fps exactly.")
        self.assertEqual(pages.fps_hint(w, True, "240", 144), w("screen.fps.hint.vsync.above", hz=144))
        self.assertEqual(pages.fps_hint(w, True, "auto", 144), w("screen.fps.hint.vsync_rate"))
        self.assertEqual(pages.fps_hint(w, False, "240", 144), w("screen.fps.hint.free"))
        self.assertNotIn("240", pages.fps_hint(w, True, "120", None))
        # The drop-down's words: the display's rate by its number when there is one rate.
        options = dict(pages.fps_options(w, found[:1], 165, "auto"))
        self.assertEqual(options["auto"], w("screen.fps.auto.hz", hz=165))
        self.assertEqual(dict(pages.fps_options(w, found, 165, "auto"))["auto"], w("screen.fps.auto"))

    def test_a_panel_is_offered_its_highest_rate_not_its_rate_now(self):
        # Windows 11's dynamic refresh rate runs a 180 Hz panel at 60 Hz while the desktop is still, and its current
        # mode says 60: 0.10.0 read that rate (GDI's VREFRESH, whole hertz) and, VSync on by default, offered no limit
        # above it. Each display's highest rate among its modes at its size is what is offered now. Made-up mode lists:
        # (size now, rate now, modes, the divider of the rate now or None, the top rate it must be offered).
        from opendmtq_client import displays, i18n, pages
        old_list = ("auto", "30", "60", "120", "144", "165", "180", "240", "360", "unlimited")

        def old_offered(gdi_rate):
            # 0.10.0's Screen page: its fixed list, and with VSync on none above the main display's GDI rate.
            return [f for f in old_list if not choices.above_rate(gdi_rate, f)]

        def numbers(offered):
            return [int(f) for f in offered if f.isdigit()]

        cases = (
            # A dynamic refresh rate panel at rest: 60 now, modes up to 180 at its size (a 240 Hz mode at another size
            # is no rate it runs at here).
            ("dynamic 180", (2560, 1600), 60, [(2560, 1600, 60), (2560, 1600, 120), (2560, 1600, 180),
                                              (1920, 1200, 240)], 2, 180),
            ("160 panel", (2560, 1600), 160, [(2560, 1600, 60), (2560, 1600, 160)], 1, 160),
            ("165 panel", (2560, 1440), 165, [(2560, 1440, 60), (2560, 1440, 144), (2560, 1440, 165)], None, 165),
            ("180 panel", (1920, 1080), 180, [(1920, 1080, 60), (1920, 1080, 180)], None, 180),
            ("240 panel", (2560, 1440), 240, [(2560, 1440, 60), (2560, 1440, 240)], 1, 240),
            ("179.999", (2560, 1600), 179.999, [(2560, 1600, 59.94), (2560, 1600, 179.999)], None, 180),
            ("59.94", (1920, 1080), 59.94, [(1920, 1080, 59.94)], None, 60),
        )
        w = i18n.Words("en")
        for name, (width, height), now, modes, divider, top in cases:
            d = displays.summarise("\\\\.\\DISPLAY1", width, height, now, modes, divider, main=True)
            self.assertEqual(d["top"], top, name)
            offered = pages.fps_choices([d], "auto")
            # Every rate up to its top, its top among them, nothing above it.
            self.assertIn(str(top), offered, name)
            self.assertEqual(max(numbers(offered)), top, name)
            # The display's rate as the page names it is the rate it runs a game at.
            self.assertEqual(dict(pages.fps_options(w, [d], None, "auto"))["auto"], w("screen.fps.auto.hz", hz=top), name)
            # 0.10.0's logic, from the rate now as GDI says it (whole hertz, cut): what it did not offer.
            gdi = int(now)
            if top > gdi * displays.MARGIN or top not in numbers(old_offered(gdi)) or gdi != top:
                # The top rate missing, or the display's rate named wrong (59 for 59.94 Hz, 179 for 179.999 Hz).
                self.assertTrue(top not in numbers(old_offered(gdi)) or gdi != top, name)
            else:
                # A plain panel 0.10.0 offered its rate to: the rates under it it did not have (160 for 165 Hz up).
                self.assertTrue(set(numbers(offered)) - set(numbers(old_offered(gdi))), name)
        # The dynamic panel: 0.10.0 offered nothing above 60 there; now up to 180, with VSync on too.
        self.assertEqual(max(numbers(old_offered(60))), 60)
        drr = displays.summarise("\\\\.\\DISPLAY1", 2560, 1600, 60, [(2560, 1600, 60), (2560, 1600, 180)], 2, main=True)
        self.assertEqual((drr["hz"], drr["top"], drr["drr"]), (60, 180, True))
        self.assertEqual(max(numbers(pages.fps_choices([drr], "auto"))), 180)
        # Two displays: a 60 Hz main beside a dynamic 180 Hz panel; up to 180, and the hints name no one rate.
        plain = displays.summarise("\\\\.\\DISPLAY2", 1920, 1080, 60, [(1920, 1080, 60)], 1, main=True)
        both = [plain, dict(drr, main=False)]
        self.assertEqual(max(numbers(pages.fps_choices(both, "auto"))), 180)
        self.assertIsNone(pages.single_rate(both, 60))
        # A panel Windows says is not dynamic, set to 60 of its 180: it runs a game at 60 (its rate is the one set), the
        # page says what it can run at too, and every limit up to 180 is still offered.
        fixed = displays.summarise("\\\\.\\DISPLAY1", 2560, 1600, 60, [(2560, 1600, 60), (2560, 1600, 180)], 1, main=True)
        self.assertEqual((pages.game_rate(fixed), fixed["drr"]), (60, False))
        self.assertEqual(max(numbers(pages.fps_choices([fixed], "auto"))), 180)
        main = {"width": 2560, "height": 1600, "hz": 60, "top": 180, "drr": False}
        self.assertEqual(pages.displays_line(w, main, [fixed]), "Main display: 2560 × 1600 at 60 Hz (up to 180 Hz)")
        # What the launcher's log says of each at its start: the rate now, the top, and the dynamic rate.
        self.assertEqual(displays.describe([drr]), [
            "\\\\.\\DISPLAY1 (main): 2560 x 1600, now 60 Hz, up to 180 Hz at this size, dynamic refresh rate on"])
        # Made up for the pictures the same way: 60 now, up to 180, dynamic.
        listed = displays.made_up("2560x1600@60~180d*")
        self.assertEqual([(d["hz"], d["top"], d["drr"], d["main"]) for d in listed], [(60, 180, True, True)])

    def test_the_sound_settings(self):
        # Master, music and effects from 0 to 100, all at 100 at first; the equaliser flat, its bands at 0 dB.
        filled = choices.normalize({})
        self.assertEqual([filled[n] for n in ("volume", "music_volume", "effects_volume")], [100, 100, 100])
        self.assertEqual([filled[n] for n in ("eq", "eq_low", "eq_mid", "eq_high")], ["flat", 0, 0, 0])
        for name, value in (("music_volume", "101"), ("effects_volume", "-1"), ("eq_low", "13"), ("eq_high", "-13"),
                            ("eq", "loud"), ("eq_mid", "a")):
            with self.assertRaises(choices.ChoiceError, msg=(name, value)):
                choices.normalize({name: value})
        self.assertEqual(choices.normalize({"eq": "custom", "eq_low": "+3", "eq_high": "-12"})["eq_low"], 3)
        # A preset sets its bands, the player's own numbers (arm32/desktop/sound_mix.h): the file writes them after it,
        # in the contract's order after volume.
        bass = choices.normalize({"eq": "bass", "eq_low": "-5"})
        self.assertEqual([bass[b] for b in choices.EQ_BANDS], list(choices.EQ_PRESETS["bass"]))
        sound_mix = os.path.join(os.path.dirname(__file__), "..", "..", "arm32", "desktop", "sound_mix.h")
        if os.path.isfile(sound_mix):
            # The player's presets, where its branch has them: the same numbers.
            with open(sound_mix, encoding="utf-8") as f:
                source = f.read()
            for kind, bands in choices.EQ_PRESETS.items():
                found = re.search(r"EqPreset::k%s: return \{(-?\d+), (-?\d+), (-?\d+)\}" % kind.title(), source)
                self.assertTrue(found, kind)
                self.assertEqual(tuple(int(n) for n in found.groups()), bands, kind)
        lines = [line for line in choices.settings_text({"eq": "vocal", "music_volume": 40}).splitlines()
                 if not line.startswith("#")]
        start = lines.index("volume=100")
        self.assertEqual(lines[start:start + 7], ["volume=100", "music_volume=40", "effects_volume=100", "eq=vocal",
                                                  "eq_low=-2", "eq_mid=4", "eq_high=1"])
        # A band set alone makes the equaliser the player's own (state.set_value, --set eq_low=3).
        from opendmtq_client import state as st
        state = st.LauncherState()
        state.set_value("eq", "treble")
        state.set_value("eq_mid", "5")
        self.assertEqual((state.values["eq"], state.values["eq_mid"], state.values["eq_high"]), ("custom", 5, 6))
        # What the player's in-game menu wrote back: the sound's keys that differ, nothing else, nothing it cannot be.
        back = choices.took_back(choices.normalize({}), "display=window\nvolume=40\nmusic_volume=x\neq=custom\n"
                                                         "eq_low=3\neq_mid=0\neq_high=0\nkeyboard=off\n")
        self.assertEqual(back, {"volume": 40, "eq": "custom", "eq_low": 3})
        self.assertEqual(choices.took_back(choices.normalize({}), choices.settings_text({})), {})

    def test_the_buffer_is_low_as_the_players_default(self):
        # The low buffer first, the player's own default where the file names none (arm32/desktop/player.h), measured
        # through whole songs on real Windows with no gap and the least latency.
        self.assertEqual(choices.normalize({})["audio_buffer"], "low")
        player_h = os.path.join(os.path.dirname(SETTINGS_CPP), "player.h")
        if os.path.isfile(player_h):
            with open(player_h, encoding="utf-8") as f:
                found = re.search(r"int audio_buffer = (\d);", f.read())
            self.assertTrue(found)
            self.assertEqual(("low", "normal", "safe")[int(found.group(1))], choices.DEFAULTS["audio_buffer"])

    def test_settings_file(self):
        text = choices.settings_text({"display": "window", "window": "1600x900", "vsync": "off", "fps": "unlimited",
                                      "render_scale": "75", "upscaler": "nis", "anti_aliasing": "smaa", "show_fps": "on",
                                      "audio_device": "{0.0.0.00000000}.{x}",
                                      "audio_mode": "exclusive", "audio_buffer": "low", "volume": 35})
        lines = [line for line in text.splitlines() if not line.startswith("#")]
        self.assertEqual(lines, ["display=window", "window=1600x900", "vsync=off", "fps=unlimited", "render_scale=75",
                                 "upscaler=nis", "anti_aliasing=smaa", "show_fps=bottom_right", "audio_device={0.0.0.00000000}.{x}",
                                 "audio_mode=exclusive", "audio_buffer=low", "volume=35", "music_volume=100",
                                 "effects_volume=100", "eq=flat", "eq_low=0", "eq_mid=0", "eq_high=0", "keyboard=on", "keys_2line=F J",
                                 "keys_3line=D F J", "keys_4line=D F J K"])

    def test_the_player_reads_every_key_and_value(self):
        """Each key the launcher writes, and each fixed value it offers, is one the player's reader takes."""
        with open(SETTINGS_CPP, encoding="utf-8") as f:
            source = f.read()
        # The equaliser's names are read by the player's sound mixer (eq_from_name), where its branch has one.
        sound_mix = os.path.join(os.path.dirname(SETTINGS_CPP), "sound_mix.h")
        if os.path.isfile(sound_mix):
            with open(sound_mix, encoding="utf-8") as f:
                source += f.read()
        # Every key, keyboard play's four too: the player's reader takes each by its name (settings.cpp, key == "...").
        # A reader that left one out would log it and play without it, so none is let off.
        # The sound's keys of 0.11.0 (the in-game menu's volumes and equaliser) come with the player's own branch: until
        # its reader has any of them, they are left out here; once it has one, it must have them all.
        added = ("music_volume", "effects_volume", "eq", "eq_low", "eq_mid", "eq_high")
        has_added = any('key == "%s"' % name in source for name in added)
        for name in choices.ORDER:
            if name in added and not has_added:
                continue
            self.assertIn('key == "%s"' % name, source, name)
        for name, offered in choices.CHOICES.items():
            if name in added and not has_added:
                continue
            for value in offered:
                if name in ("fps", "render_scale") and value not in ("auto", "unlimited"):
                    continue
                self.assertIn('"%s"' % value, source, (name, value))
        # Numbers: the player's ranges hold every number offered.
        fps = re.search(r'number\(value, (\d+), (\d+), n\)\)\) s\.fps', source)
        scale = re.search(r'number\(value, (\d+), (\d+), n\)\)\) s\.render_scale', source)
        self.assertTrue(fps and scale)
        from opendmtq_client import displays
        self.assertEqual((int(fps.group(1)), int(fps.group(2))), choices.FPS_RANGE)
        for value in choices.FPS + tuple(str(rate) for rate in displays.RATES):
            if value.isdigit():
                self.assertTrue(int(fps.group(1)) <= int(value) <= int(fps.group(2)), value)
        for value in choices.RENDER_SCALE:
            self.assertTrue(int(scale.group(1)) <= int(value) <= int(scale.group(2)), value)


if __name__ == "__main__":
    unittest.main()
