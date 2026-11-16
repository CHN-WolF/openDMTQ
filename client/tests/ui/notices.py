"""The launcher's notices say each change of the state as it comes, every time, not only the first (the window's own
look, app.watch, and its look for a newer launcher): a server that stops answering, answers again and stops again; a
sign-in the server stops taking, signed in again and stopped again; a newer app on the server; a newer launcher, and
another newer one after it.

Run inside the opendmtq-client-ui container only (client/tests/ui/run.sh); it refuses anywhere else, because it opens
windows. The server is the tests' stand-in site (tests/stub.py) on this machine's loopback, the player a stand-in.

  python tests/ui/notices.py --lang en|ko      (from client/)
Exit status 1 when a notice did not come; each failure is printed.
"""

import argparse
import importlib.util
import os
import sys
import time

# Run from client/ (the container mounts the repository and works there).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from opendmtq_client import safety  # noqa: E402

# The keyboard checks' set-up (a launcher signed in on the stand-in server, its app on this PC), from the file beside.
_spec = importlib.util.spec_from_file_location("keyboard", os.path.join(os.path.dirname(__file__), "keyboard.py"))
keyboard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(keyboard)
shots = keyboard.shots


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", default="en")
    args = parser.parse_args()
    if not safety.on_virtual_display():
        sys.exit("refusing: this opens windows; run it through client/tests/ui/run.sh")
    site, state = keyboard.setup(args.lang)
    from opendmtq_client import pages, updates
    from opendmtq_client.app import LauncherApp
    problems = []
    app = LauncherApp(state)
    app.root.geometry("1180x760+0+0")
    shots.settle(app)

    def look(what):
        """The window's own look, waited for: its answers taken and the ready check that follows them back."""
        done = {}
        app.watch(then=lambda: done.setdefault("yes", True))
        end = time.time() + 15
        while "yes" not in done and time.time() < end:
            app.root.update()
            time.sleep(0.02)
        shots.settle(app)
        if "yes" not in done:
            problems.append("%s: the look did not come back" % what)

    def says(key, what):
        said = getattr(app.status_message, "key", None)
        if said != key:
            problems.append("%s: the status line says %r (%r), not %s" % (what, said, app.status_text, key))

    # ---- the server stops answering, answers again, stops again: each said as it comes.
    app.nav_go("play")
    shots.settle(app)
    for round_ in (1, 2):
        site.old = True
        look("server down, round %d" % round_)
        says("status.server_down", "server down, round %d" % round_)
        site.old = False
        look("server back, round %d" % round_)
        says("status.ready", "server back, round %d" % round_)
    # ---- the server stops taking the sign-in; signed in again; stops again: said each time.
    from opendmtq_client import actions
    from tests import stub
    for round_ in (1, 2):
        site.signed_cookies.clear()
        look("sign-in ended, round %d" % round_)
        says("status.signed_out", "sign-in ended, round %d" % round_)
        if app.state.signed_in():
            problems.append("sign-in ended, round %d: the launcher still keeps the sign-in" % round_)
        site.signed_cookies.add(site.cookie)
        actions.sign_in(app.state, stub.ACCOUNT, stub.PASSWORD)
        app.state.save()
        app.user_acted()
        look("signed in again, round %d" % round_)
        says("status.ready", "signed in again, round %d" % round_)
    # ---- a newer app on the server: the ready check's app line and the Online page say it, by themselves.
    site.app = site.app + b"newer"
    look("a newer app")
    if not any(c.key == "app_update" for c in app.checks or ()):
        problems.append("a newer app: the ready check does not say it (%r)" % [c.key for c in app.checks or ()])
    app.nav_go("online")
    shots.settle(app)
    newer = app.words("online.app.newer", date=pages._date(site.describe()))
    if not any(x.winfo_class() == "Label" and x.cget("text") == newer for x in shots.widgets_of(app.body.inner)):
        problems.append("a newer app: the Online page does not say %r" % newer)
    # ---- a newer launcher, then another newer one: each said.
    for version in ("9.9.9", "9.9.10"):
        found = updates.Result("available", version=version)
        original = updates.Look

        class Found:
            def newer(self):
                return found

        updates.Look = Found
        try:
            app.look_for_update()
            end = time.time() + 5
            while (app.update_found is None or app.update_found.version != version) and time.time() < end:
                app.root.update()
                time.sleep(0.02)
        finally:
            updates.Look = original
        shots.settle(app)
        app.user_acted()
        app._say_state()
        if getattr(app.status_message, "key", None) != "about.available" or version not in app.status_text:
            problems.append("a newer launcher %s: the status line says %r" % (version, app.status_text))
    for job in app.root.tk.splitlist(app.root.tk.call("after", "info")):
        app.root.after_cancel(job)
    app.root.destroy()
    site.stop()
    print("notices %s: %d problems" % (args.lang, len(problems)))
    for problem in problems:
        print("  " + problem)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
