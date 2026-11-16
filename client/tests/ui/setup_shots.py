"""The installer's window (OpenDMTQ-Setup.exe, and the uninstall Windows' Settings, Apps opens) on the test container's
virtual screen: every page and state it shows, a screenshot of each, and the layout measured as the launcher's pages
are (text cut off, a control past the window's edge or squeezed, a line running under the strip with the buttons).

Run inside the opendmtq-client-ui container only (client/tests/ui/run.sh); it refuses anywhere else, because it opens
windows. Nothing is installed or removed: Velopack's setup and uninstaller are stand-ins that write what the real ones
write (a log, the program's folder filling or emptying) in a folder of the run's own.

  python tests/ui/setup_shots.py --out DIR [--lang en|ko] [--tag TAG]      (from client/)
Exit status 1 when the layout check finds a problem; the problems are printed and written to DIR/setup-problems-*.txt.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from unittest import mock

# Run from client/ (the container mounts the repository and works there).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from opendmtq_client import safety  # noqa: E402

# The launcher's measure of boxes and room, from the file beside this one.
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("spacing", os.path.join(os.path.dirname(__file__), "spacing.py"))
spacing = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spacing)

# Velopack's setup's log as it writes it, line by line (its real words, a run of 0.10.0's under Wine).
SETUP_LOG = """[setup:448] [11:47:52] [INFO] Starting Velopack Setup (1.2.161)
[setup:448] [11:47:52] [INFO] Reading bundle header...
[setup:448] [11:47:52] [INFO] Bundle offset = 7546368, length = 41322990
[setup:448] [11:47:52] [INFO] There is 312.75 GB free space available at destination, this package requires 187.49 MB.
[setup:448] [11:47:52] [INFO] Preparing and cleaning installation directory...
[setup:448] [11:47:52] [INFO] Extracting Update.exe...
[setup:448] [11:47:52] [INFO] Copying nupkg to packages directory...
[setup:448] [11:47:52] [INFO] Extracting 1032 app files to '"C:\\\\users\\\\player\\\\AppData\\\\Local\\\\OpenDMTQ.Client\\\\current"'...
"""


class Process:
    """A stand-in for a program the installer starts and waits for: running until `ends` (a time), then `code`."""

    def __init__(self, seconds, code=0, during=None):
        self.ends, self.code, self.during = time.time() + seconds, code, during

    def poll(self):
        if self.during is not None:
            self.during()
        return None if time.time() < self.ends else self.code

    def kill(self):
        self.ends = 0


def widgets_of(widget):
    yield widget
    for child in widget.winfo_children():
        yield from widgets_of(child)


def measure(window, name, problems):
    """The page as a person sees it: no text cut off, nothing past the window's right edge or under the strip along its
    foot, no button squeezed, every line of text inside its card."""
    import tkinter as tk
    from opendmtq_client import widgets
    root = window.root
    root.update()
    right = root.winfo_rootx() + root.winfo_width()
    strip_top = window.strip.master.winfo_rooty()
    for w in widgets_of(root):
        if not w.winfo_ismapped():
            continue
        cls = w.winfo_class()
        if cls == "Label" and w.cget("text") and w.winfo_reqwidth() > w.winfo_width() + 2:
            problems.append("%s: text cut off: %r (needs %d px, has %d)" % (name, w.cget("text")[:60],
                                                                            w.winfo_reqwidth(), w.winfo_width()))
        if cls in ("Label", "Frame", "Canvas") and w.winfo_width() > 1 and w.winfo_viewable():
            if w.winfo_rootx() + w.winfo_width() > right + 1:
                problems.append("%s: past the right edge: %s %r" % (name, cls, (w.cget("text") if cls == "Label"
                                                                                else "")[:40]))
        if isinstance(w, widgets.Button) and w.winfo_width() + 1 < w.winfo_reqwidth():
            problems.append("%s: button squeezed: %r" % (name, w.words))
        if isinstance(w, tk.Label) and w.cget("text") and str(w).startswith(str(window.page_area.inner)):
            # Text of the page lies above the strip once the page is scrolled to it: the page area ends there.
            area = window.page_area.canvas
            if w.winfo_rooty() + w.winfo_height() > area.winfo_rooty() + area.winfo_height() + 1 \
                    and area.yview() == (0.0, 1.0):
                problems.append("%s: text under the strip: %r" % (name, w.cget("text")[:40]))
    if window.page_area.canvas.winfo_rooty() + window.page_area.canvas.winfo_height() > strip_top + 1:
        problems.append("%s: the page runs under the strip" % name)
    # The launcher's own measure of boxes and room (tests/ui/spacing.py): nothing touching, words inside their card's
    # padding, the gaps on the spacing scale.
    problems.extend(spacing.check(root, window.ui, name))


def shot(root, out, name):
    """Screenshot of the window, through the X server (what a person would see)."""
    root.update()
    time.sleep(0.3)
    root.update()
    target = os.path.join(out, name + ".png")
    subprocess.run(["import", "-window", str(root.winfo_id()), target], check=True)
    return target


def settle(root, seconds):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--lang", default="en")
    parser.add_argument("--tag", default="")
    args = parser.parse_args()
    if not safety.on_virtual_display():
        sys.exit("refusing: this opens windows; run it through client/tests/ui/run.sh")
    os.makedirs(args.out, exist_ok=True)
    home = tempfile.mkdtemp()
    local = os.path.join(home, "local")
    for name, value in (("HOME", home), ("LOCALAPPDATA", local), ("XDG_DATA_HOME", local),
                        ("OPENDMTQ_CLIENT_DIR", os.path.join(local, "OpenDMTQ", "client"))):
        os.environ[name] = value
    from opendmtq_client import __version__, installer, removal
    from opendmtq_client import state as st
    # The launcher's language as the player chose it.
    state = st.LauncherState()
    state.language = args.lang
    state.save()
    tag = "%s%s" % (args.lang, ("-" + args.tag) if args.tag else "")
    problems = []
    folder = installer.app_dir()

    def program(version):
        """An install folder as Velopack lays one out, of `version`, with a few files of the program."""
        os.makedirs(os.path.join(folder, "current", "player"), exist_ok=True)
        with open(os.path.join(folder, "current", "sq.version"), "w") as f:
            f.write("<version>%s</version>" % version)
        with open(os.path.join(folder, "Update.exe"), "wb") as f:
            f.write(b"MZ" + b"\0" * 4000)
        with open(os.path.join(folder, "current", "player", "OpenDMTQ-Player.exe"), "wb") as f:
            f.write(b"MZ" + b"\0" * 400000)

    def data():
        """The launcher's settings and a game's data, so that the uninstall has sizes to say."""
        game = os.path.join(removal.data_root(), "com.example.game", "data")
        os.makedirs(game, exist_ok=True)
        with open(os.path.join(game, "android_id"), "w") as f:
            f.write("0123456789abcdef")
        with open(os.path.join(game, "songs.bin"), "wb") as f:
            f.write(b"\0" * (3 << 20))

    def run(name, make, steps=()):
        """Open the window as `make()` makes it, take each step (a function of the window and the installer), then a
        screenshot and the measures; the window closed after."""
        if not os.path.isfile(st.LauncherState.path()):
            # Delete everything took the launcher's settings, the player's language with them: given back, so that
            # every page is seen in the run's language.
            kept = st.LauncherState()
            kept.language = args.lang
            kept.save()
        made = make()
        window = made.window
        settle(window.root, 1.0)
        for step in steps:
            step(made)
            settle(window.root, 0.6)
        full = "setup-%s_%s" % (tag, name)
        shot(window.root, args.out, full)
        measure(window, full, problems)
        try:
            # Its timers first (a bar's easing, a look at the work): they would call widgets that are gone.
            for job in window.root.tk.splitlist(window.root.tk.call("after", "info")):
                window.root.after_cancel(job)
            window.root.destroy()
        except Exception:  # noqa: BLE001  (a page that closed itself already)
            pass

    patches = [mock.patch.object(installer, "launcher_open", return_value=False),
               mock.patch.object(installer, "game_running", return_value=False),
               mock.patch.object(installer, "start_launcher"),
               mock.patch.object(installer, "own_entry"),
               mock.patch.object(installer, "brought", return_value={"url": "http://192.168.1.10:8790",
                                                                      "name": "Club Night"})]
    for patch in patches:
        patch.start()

    # ---- a PC without OpenDMTQ: Install, its progress, its end.
    import shutil
    shutil.rmtree(folder, ignore_errors=True)
    run("install", installer.Installer)

    def setup_runs(path):
        """Velopack's setup as it runs: its log written (to the path the installer names), the program's folder filling
        a little at each look."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(SETUP_LOG)

        def fill():
            program(__version__)
            chunk = os.path.join(folder, "current", "chunk.bin")
            if not os.path.exists(chunk) or os.path.getsize(chunk) < (110 << 20):
                with open(chunk, "ab") as f:
                    f.write(b"\0" * (8 << 20))

        return Process(60, 0, during=fill)

    with mock.patch.object(installer, "run_setup", setup_runs):
        run("installing", installer.Installer, [lambda made: made.work("install"), lambda made: settle(made.root, 1.5)])
    shutil.rmtree(folder, ignore_errors=True)
    with mock.patch.object(installer, "run_setup", lambda path: Process(0.3, 0, during=lambda: program(__version__))):
        run("installed", installer.Installer, [lambda made: made.work("install"), lambda made: settle(made.root, 2.0)])
    # ---- a PC with OpenDMTQ: the same version, an older one (Update), a newer one (go back).
    program(__version__)
    run("choose", installer.Installer)

    # The keyboard alone (P1: nothing reachable only by the pointer): Tab goes the choices, then the strip's buttons;
    # the arrow keys move the choice; Enter on the choices does the main button's; Esc on the uninstall's page goes
    # back, on the first page closes the window.
    def keys(made):
        from opendmtq_client import setup_window
        root = made.root
        settle(root, 0.5)
        focus = root.focus_get()
        if not isinstance(focus, setup_window.Options):
            problems.append("setup-%s: the choices do not have the keyboard at first (%r)" % (tag, focus))
            return
        order = [focus]
        widget = focus
        for _ in range(4):
            widget = widget.tk_focusNext()
            if widget is None or widget in order:
                break
            order.append(widget)
        words = [getattr(w, "words", None) for w in order[1:]]
        if words[:2] != [made.words("setup.close"), made.words("setup.open")]:
            problems.append("setup-%s: Tab goes %r after the choices" % (tag, words))
        for key in ("<Down>", "<Down>"):
            focus.event_generate(key)
        if focus.value != "uninstall":
            problems.append("setup-%s: the arrow keys did not reach Uninstall (%s)" % (tag, focus.value))
        focus.event_generate("<Return>")
        settle(root, 0.5)
        if made.flow[0][1] != "data":
            problems.append("setup-%s: Enter on Uninstall did not open the uninstall's page" % tag)
        root.event_generate("<Escape>")
        settle(root, 0.5)
        if made.flow[0][0] != "choose":
            problems.append("setup-%s: Esc on the uninstall's page did not go back (%r)" % (tag, made.flow))

    run("choose-keys", installer.Installer, [keys])
    # The notices follow the PC each time: a launcher opened while the page shows says so, closed again it goes; the
    # game too.
    notice = {"launcher": False, "game": False}

    def said(made):
        return [w.cget("text") for w in widgets_of(made.root) if w.winfo_class() == "Label" and w.winfo_ismapped()]

    def flip(made, what, on, expect):
        notice[what] = on
        settle(made.root, 1.6)
        words = made.words("setup.closing" if what == "launcher" else "setup.notice.game")
        if (words in said(made)) != expect:
            problems.append("setup-%s: the notice that the %s is open %s after it %s" % (
                tag, what, "did not show" if expect else "stayed", "opened" if on else "closed"))

    with mock.patch.object(installer, "launcher_open", lambda: notice["launcher"]), \
            mock.patch.object(installer, "game_running", lambda: notice["game"]):
        run("choose-notices", installer.Installer,
            [lambda made: flip(made, "launcher", True, True), lambda made: flip(made, "launcher", False, False),
             lambda made: flip(made, "launcher", True, True), lambda made: flip(made, "game", True, True)])
        notice.update(launcher=False, game=False)
        # Waiting for the game: once it closes, the work goes on by itself.
        started = []
        notice["game"] = True
        with mock.patch.object(installer, "run_setup", lambda path: (started.append(path), Process(60, 0))[1]):
            run("game-waits", installer.Installer, [lambda made: made.work("repair"),
                                                    lambda made: (notice.update(game=False), settle(made.root, 1.6))])
        if not started:
            problems.append("setup-%s: the repair did not go on once the game closed" % tag)
    program("0.0.1")
    run("choose-update", installer.Installer)
    program("99.0.0")
    run("choose-older", installer.Installer)
    program(__version__)
    # Repair's end.
    with mock.patch.object(installer, "run_setup", lambda path: Process(0.3, 0)):
        run("repaired", installer.Installer, [lambda made: made.work("repair"), lambda made: settle(made.root, 2.0)])
    # A failure, with its log.
    def setup_fails(path):
        """Velopack's setup ending with an error line in its log, as a full disk ends it."""
        with open(path, "w", encoding="utf-8") as f:
            f.write("[setup:448] [11:47:52] [ERROR] There is not enough space on the disk.\n")
        return Process(0.2, 1)

    with mock.patch.object(installer, "run_setup", setup_fails):
        run("failed", installer.Installer, [lambda made: made.work("repair"), lambda made: settle(made.root, 1.5)])
    # The game open: the work waits for it.
    with mock.patch.object(installer, "game_running", return_value=True):
        run("game-open", installer.Installer, [lambda made: made.work("repair")])
    # ---- Uninstall: the choice with the sizes, the work, both ends.
    data()

    def to_uninstall(made):
        made.uninstall_page()

    run("uninstall", installer.Installer, [to_uninstall, lambda made: settle(made.root, 1.5)])

    def uninstaller(seconds):
        def started(root_folder):
            def empty():
                # Velopack's uninstaller as it goes: the program's folder emptied, then gone.
                shutil.rmtree(os.path.join(folder, "current"), ignore_errors=True)
            return Process(seconds, 0, during=empty)
        return started

    for choice, name in (("keep", "uninstalled-keep"), ("all", "uninstalled-all")):
        program(__version__)
        data()
        with mock.patch.object(removal, "start_uninstaller", uninstaller(0.4)):
            run(name, installer.Installer, [to_uninstall, lambda made: settle(made.root, 1.5),
                                            lambda made, c=choice: made.uninstall(c),
                                            lambda made: settle(made.root, 3.0)])
    program(__version__)
    data()
    with mock.patch.object(removal, "start_uninstaller", uninstaller(30)):
        run("uninstalling", installer.Installer, [to_uninstall, lambda made: settle(made.root, 1.5),
                                                  lambda made: made.uninstall("all"),
                                                  lambda made: settle(made.root, 0.8)])
    # Windows' Settings, Apps: the uninstall alone.
    program(__version__)
    run("apps-uninstall", lambda: installer.Installer(start="uninstall", folder=folder),
        [lambda made: settle(made.root, 1.5)])
    for patch in patches:
        patch.stop()
    report = os.path.join(args.out, "setup-problems-%s.txt" % tag)
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(problems) + ("\n" if problems else ""))
    print("setup %s: %d problems" % (tag, len(problems)))
    for problem in problems:
        print("  " + problem)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
