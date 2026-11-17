"""Whether a setting changed in the launcher redraws the window visibly: the screen is filmed while a person changes a
setting (a switch with Space, a drop-down's choice, a row of tabs with an arrow key), and what the film shows between
the screen before and the screen after is counted, with the widgets the change made anew.

A change shows at once as the screen after it: the frames that are neither the screen before nor the one after
(a page half drawn, its cards gone for a moment, text wrapped narrow then wide) are the flicker a person sees. Each
change may make anew only the rows it brings, never the page.

Run inside the opendmtq-client-ui container only (client/tests/ui/run.sh); it refuses anywhere else, because it opens
windows. The film is the virtual screen's own pixels, taken as fast as it gives them (a frame every few ms).

  python tests/ui/flicker.py --lang en|ko [--size 1180x760] [--report FILE]      (from client/)
Exit status 1 when a change flickers or makes anew more than its rows; each change's counts are printed.
"""

import argparse
import importlib.util
import os
import sys
import threading
import time

# Run from client/ (the container mounts the repository and works there).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from opendmtq_client import safety, widgets  # noqa: E402

# The screenshots' helpers and the keyboard test's set-up (a launcher signed in with its app), from the files beside.
_here = os.path.dirname(__file__)
_spec = importlib.util.spec_from_file_location("shots", os.path.join(_here, "shots.py"))
shots = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shots)
_spec = importlib.util.spec_from_file_location("keyboard", os.path.join(_here, "keyboard.py"))
keyboard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(keyboard)

# How long the film runs after a change (seconds): the page's late work (its picture behind, a second look at a page
# that got shorter) comes within 0.2 s.
FILM = 0.6
# The frames in between allowed for a change of a value: one, within a 60 Hz display's frame (the control and its hint
# are two windows the X server may show a moment apart; nothing of the page goes blank).
FRAMES_ALLOWED, FRAMES_MS = 1, 17
# For a change that brings or takes a row (or makes a hint a line longer): Tk lays the page out parent by parent, and
# the rows under it move down within this many frames and milliseconds (two of a 60 Hz display's frames, and a margin
# for a busy test machine), never a page or a card emptied as before (7 to 11 frames over 150 ms and more).
MOVING_FRAMES, MOVING_MS = 2, 50
# For an answer that makes one card of a page again with other content (signed out: the sign-in form in place of the
# account), that card alone: its frames while it is laid out, never the page's other cards made again.
CARD_FRAMES, CARD_MS = 8, 250
# Where a frame between is saved as a picture for each change that has one (--frames), or None.
FRAMES_OUT = None


class Film:
    """The window's part of the virtual screen, taken over and over on a thread of its own while the window's thread
    works (Tk lets go of Python's lock while it draws, so the frames come between its steps too)."""

    def __init__(self, box):
        self.box, self.frames, self.times, self._stop = box, [], [], threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        from PIL import ImageGrab
        while not self._stop.is_set():
            frame = ImageGrab.grab(bbox=self.box, xdisplay=os.environ.get("DISPLAY"))
            # Kept as bytes: a frame is told from another by its pixels alone.
            data = frame.tobytes()
            if not self.frames or self.frames[-1] != data:
                self.frames.append(data)
                # When it first showed (the change's time on the screen is from its first frame to its last).
                self.times.append(time.monotonic())
            time.sleep(0.002)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()


# The changes filmed, page by page, as a person makes them: (what it is, the control's kind, its row's name, the key
# pressed on it or the drop-down's choice, whether it brings or takes a row or makes a hint a line longer).
CHANGES = (
    ("screen", (
        ("VSync off (Space)", widgets.Toggle, "screen.vsync", "<space>", False),
        ("VSync on (Space)", widgets.Toggle, "screen.vsync", "<space>", False),
        ("frame limit 120", widgets.Select, "screen.fps", "120", False),
        ("frame limit back", widgets.Select, "screen.fps", "auto", False),
        ("FPS counter on (brings Position)", widgets.Toggle, "screen.counter", "<space>", True),
        ("FPS counter off (takes Position)", widgets.Toggle, "screen.counter", "<space>", True),
        ("render scale 75 (brings Upscaler)", widgets.Select, "screen.scale", "75", True),
        ("upscaler NIS", widgets.Select, "screen.upscaler", "nis", False),
        ("render scale 100 (takes Upscaler)", widgets.Select, "screen.scale", "100", True),
        ("anti-aliasing SMAA", widgets.Select, "screen.aa", "smaa", False),
        ("anti-aliasing off", widgets.Select, "screen.aa", "off", False),
        ("mode window (brings Window size)", widgets.Segmented, "screen.mode", "<Right>", True),
        ("mode full screen (takes it)", widgets.Segmented, "screen.mode", "<Left>", True))),
    ("sound", (
        ("master volume down (arrow)", widgets.Slider, "sound.volume.master", "<Left>", False),
        ("music volume down (arrow)", widgets.Slider, "sound.volume.music", "<Left>", False),
        ("equaliser Bass (arrow)", widgets.Segmented, "sound.eq.preset", "<Right>", True),
        ("low band up (makes it Custom)", widgets.Slider, "sound.eq.low", "<Right>", True),
        ("buffer normal (arrow)", widgets.Segmented, "sound.buffer", "<Right>", True),
        ("buffer low (arrow)", widgets.Segmented, "sound.buffer", "<Left>", True),
        ("mode exclusive (arrow)", widgets.Segmented, "sound.mode", "<Right>", True),
        ("mode shared (arrow)", widgets.Segmented, "sound.mode", "<Left>", True))),
    ("controls", (
        ("keyboard play off (takes the keys)", widgets.Toggle, "controls.keys.play", "<space>", True),
        ("keyboard play on (brings the keys)", widgets.Toggle, "controls.keys.play", "<space>", True))),
)


def grab(box):
    from PIL import ImageGrab
    return ImageGrab.grab(bbox=box, xdisplay=os.environ.get("DISPLAY")).tobytes()


def window_box(app):
    root = app.root
    root.update()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    return (x, y, x + root.winfo_width(), y + root.winfo_height())


def all_widgets(app):
    return set(shots.widgets_of(app.root))


def run_until(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.root.update()
        time.sleep(0.005)


def measure_change(app, name, act, results, rows_allowed=0, focus=None, moves=False, expect_change=True):
    """Film `act()` (a change as a person makes it) and count: the frames between the screen before and after, and the
    widgets the change made anew. `rows_allowed`: the widgets the change may make (the rows it brings). `focus()` gives
    the control the keyboard is on before the film starts (its ring is no part of the change)."""
    if focus is not None:
        focus().focus_set()
    shots.settle(app)
    run_until(app, 0.3)
    box = window_box(app)
    before_widgets = all_widgets(app)
    before = grab(box)
    with Film(box) as film:
        act()
        run_until(app, FILM)
    after = grab(box)
    after_widgets = all_widgets(app)
    made = len(after_widgets - before_widgets)
    gone = len(before_widgets - after_widgets)
    between = [f for f in film.frames if f != before and f != after]
    # How long the screen showed frames between: from the first frame that is not the screen before to the first that
    # is the screen after (0 when it went from one to the other at once).
    shown = [t for f, t in zip(film.frames, film.times) if f != before]
    settled = [t for f, t in zip(film.frames, film.times) if f == after]
    span = int(round(1000 * (settled[0] - shown[0]))) if shown and settled and settled[0] >= shown[0] else 0
    changed = before != after
    results.append({"change": name, "moves": moves, "expect_change": expect_change, "frames_between": len(between),
                    "span": span, "made": made, "gone": gone, "changed": changed,
                    "rows_allowed": rows_allowed})
    if between and FRAMES_OUT:
        # The frame in the middle of the ones between, as a picture: what a person sees for a moment.
        from PIL import Image
        size = (box[2] - box[0], box[3] - box[1])
        for i, frame in enumerate(between):
            Image.frombytes("RGB", size, frame).save(os.path.join(FRAMES_OUT, "%02d-between-%d.png" % (len(results), i)))
        Image.frombytes("RGB", size, before).save(os.path.join(FRAMES_OUT, "%02d-0before.png" % len(results)))
        Image.frombytes("RGB", size, after).save(os.path.join(FRAMES_OUT, "%02d-9after.png" % len(results)))


def control(app, area, kind, title):
    found = keyboard.setting_control(area, kind, title)
    if found is None:
        raise AssertionError("no %s named %r on the page" % (kind.__name__, title))
    return found


def press(widget, key):
    """A key on a control the keyboard is on (measure_change puts it there before the film starts)."""
    widget.event_generate(key)


def choose(select, value):
    """A drop-down's choice as a person makes it: the value, then the drop-down's own event."""
    select.set_value(value)
    select.event_generate("<<ComboboxSelected>>")


def change(app, name, results, find, kind, key, act, rows_allowed=0, canvas=False, moves=False):
    """measure_change for the control of `kind` in the row named by `key`: the keyboard on it first, then `act(it)`."""
    def it():
        found = find(kind, key)
        return found.canvas if canvas else found
    try:
        it()
    except (AssertionError, KeyError) as e:
        # No such control (an older launcher's page): said, and the next change measured.
        results.append({"change": name, "missing": str(e)})
        return
    measure_change(app, name, lambda: act(it()), results, rows_allowed, focus=it, moves=moves)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", default="en")
    parser.add_argument("--size", default="1180x760")
    parser.add_argument("--report")
    parser.add_argument("--frames")
    args = parser.parse_args()
    global FRAMES_OUT
    FRAMES_OUT = args.frames
    if FRAMES_OUT:
        os.makedirs(FRAMES_OUT, exist_ok=True)
    if not safety.on_virtual_display():
        sys.exit("refusing: this opens windows; run it through client/tests/ui/run.sh")
    site, state = keyboard.setup(args.lang)
    from opendmtq_client.app import LauncherApp
    app = LauncherApp(state)
    app.root.geometry("%s+0+0" % args.size)
    shots.settle(app)
    w = app.words
    results = []

    find = lambda kind, key: control(app, app.body, kind, w(key))  # noqa: E731
    for page, changes in CHANGES:
        app.nav_go(page)
        shots.settle(app)
        if page == "sound":
            # The devices come from the player on a worker thread: their row is made when they come.
            shots.settle(app, 6, until=lambda: app.devices is not None)
            shots.settle(app)
        for name, kind, key, how, moves in changes:
            # A key on the control, or a drop-down's choice (a value in place of a key).
            act = (lambda c, k=how: press(c, k)) if how.startswith("<") else (lambda c, v=how: choose(c, v))
            change(app, "%s: %s" % (page, name), results, find, kind, key, act, canvas=kind is widgets.Slider,
                   moves=moves)

    # ---- Answers that change a card of a page, never the page: Help's Check again with nothing changed makes nothing
    # anew; Online's Sign out makes the sign-in card again and leaves the server's and the app's cards as they were.
    app.nav_go("help")
    shots.settle(app)
    recheck = shots.button(app, w("help.recheck"))
    measure_change(app, "help: Check again, nothing changed", lambda: recheck.press(), results, focus=lambda: recheck,
                   expect_change=False)
    app.nav_go("online")
    shots.settle(app)
    kept = [x for x in shots.widgets_of(app.body.inner) if isinstance(x, widgets.Field)]
    sign_out = shots.button(app, w("online.signout"))
    measure_change(app, "online: Sign out, its card alone", lambda: sign_out.press(), results, rows_allowed=60,
                   focus=lambda: sign_out, moves="card")
    if not kept or not all(x.winfo_exists() for x in kept):
        results.append({"change": "online: Sign out", "missing": "the server's card was made again"})

    # ---- The connection test: Test connection makes its card alone (its steps waiting: the test is held at its start),
    # then each step says itself in place, nothing made or gone, until the test ends.
    from opendmtq_client import connection
    gate, real_run = threading.Event(), connection.run

    def held_run(*args, **kwargs):
        gate.wait(10)
        return real_run(*args, **kwargs)

    connection.run = held_run
    try:
        kept = [x for x in shots.widgets_of(app.body.inner) if isinstance(x, widgets.Field)]
        test = shots.button(app, w("test.button"))
        measure_change(app, "online: Test connection, its card alone", lambda: test.press(), results, rows_allowed=150,
                       focus=lambda: test, moves="card")
        if not kept or not all(x.winfo_exists() for x in kept):
            results.append({"change": "online: Test connection", "missing": "the server's card was made again"})
        shots.settle(app)
        before = all_widgets(app)
        gate.set()
        shots.settle(app, 30, until=lambda: not app.connection_test["running"])
        after = all_widgets(app)
        results.append({"change": "online: the test's steps said in place", "moves": False, "expect_change": True,
                        "frames_between": 0, "span": 0, "made": len(after - before), "gone": len(before - after),
                        "changed": True, "rows_allowed": 0})
    finally:
        connection.run = real_run

    for job in app.root.tk.splitlist(app.root.tk.call("after", "info")):
        app.root.after_cancel(job)
    app.root.destroy()
    site.stop()

    problems = []
    lines = []
    for r in results:
        if "missing" in r:
            lines.append("%-48s no such control (%s)" % (r["change"], r["missing"]))
            problems.append("%s: no such control" % r["change"])
            continue
        lines.append("%-48s frames between %2d over %3d ms, widgets made %3d, gone %3d" % (
            r["change"], r["frames_between"], r["span"], r["made"], r["gone"]))
        frames, ms = {"card": (CARD_FRAMES, CARD_MS), True: (MOVING_FRAMES, MOVING_MS),
                      False: (FRAMES_ALLOWED, FRAMES_MS)}[r["moves"]]
        if r["frames_between"] > frames or r["span"] > ms:
            problems.append("%s: %d frames between the screen before and after, over %d ms" % (
                r["change"], r["frames_between"], r["span"]))
        if r.get("gone", 0) > r["rows_allowed"] and r["change"].endswith("said in place"):
            problems.append("%s: %d widgets gone (none may go)" % (r["change"], r["gone"]))
        if r["made"] > r["rows_allowed"]:
            problems.append("%s: %d widgets made anew (the rows it brings: %d at most)" % (r["change"], r["made"],
                                                                                         r["rows_allowed"]))
        if not r["changed"] and r.get("expect_change", True):
            problems.append("%s: the screen did not change" % r["change"])
    report = "flicker %s %s: %d changes, %d problems\n" % (args.lang, args.size, len(results), len(problems))
    report += "".join("  %s\n" % line for line in lines)
    report += "".join("  PROBLEM %s\n" % p for p in problems)
    print(report, end="")
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
