"""The launcher's pages, as the site's: a title in the wide face and a line under it (heading), then cards. Each builder
fills the page's column.

A setting row changes the remembered state right away (app.changed); the player reads the settings at the next PLAY,
so nothing changes under a game that is running.
"""

import logging
import os
import threading
import tkinter as tk

from opendmtq_client import actions, apps, dialogs, displays, i18n, keys, maintenance, player, theme, updates, widgets
from opendmtq_client import server as srv
from opendmtq_client import state as st
from opendmtq_client import values as choices

log = logging.getLogger("opendmtq_client")

# ------------------------------------------------------------------------------------------- headings

# Each page's title, in English in both languages as the site's page titles and the game's menus are.
TITLES = {"play": "PLAY", "screen": "SCREEN", "sound": "SOUND", "controls": "CONTROLS", "online": "ONLINE",
          "help": "HELP", "about": "LAUNCHER"}


def heading(app, page):
    """A page's title and the line under it: PLAY's says where it plays, the others what the page is for."""
    if page == "play":
        server = app.state.server()
        return TITLES[page], (app.words("play.on", name=server["name"]) if server else app.words("app.tagline"))
    return TITLES[page], app.words(page + ".sub")


def main_button(app, parent, text, command):
    """A page's main action (Connect, Sign in, the app's download, the launcher's update) as a button: lit in lime while
    PLAY is not, and quiet beside a lit PLAY, so that a screen has one lime main action. It follows PLAY as PLAY
    changes (app._paint_play); the guide's steps, which have no PLAY, light it."""
    button = widgets.Button(parent, app.ui, text, command, kind="secondary" if app.play_lit() else "primary")
    app.main_buttons.append(button)
    return button


def _card(parent, ui, title, last=False):
    """A card with its title, stacked under the ones before it with the site's gap between cards."""
    card = widgets.Card(parent, ui, title)
    card.pack(fill="x", pady=(0, 0 if last else ui.px(CARD_GAP)))
    return card


# The gap between two cards (the site's --gap is 20 px; the window is smaller than a page).
CARD_GAP = 16


class Sections:
    """A page's cards, each made by its own builder from what it shows (its key, a function of the launcher's state):
    refresh() makes again only the cards whose key changed, each in its own place, the others as they were. An answer
    that came (a server connected, a sign-in, a download done, a game that ended) changes its own card, never the page
    drawn again (client/tests/ui/flicker.py)."""

    def __init__(self, parent, ui, after=None):
        self.parent, self.ui, self.after = parent, ui, after
        # Each card: its holder frame (in the page's order), its key, its builder, the key it was made for, and the
        # gap above it now.
        self.items = []

    def add(self, key, build, expand=False):
        """A card at the end, made now: `build(holder)` makes it in its holder, `key()` says what it shows. `expand`:
        the holder takes the height left to its column (the PLAY page's Last game)."""
        holder = tk.Frame(self.parent, bg=self.parent.cget("bg"))
        item = {"holder": holder, "key": key, "build": build, "made": object(), "gap": None, "expand": expand}
        self.items.append(item)
        self._make(item)
        return holder

    def _make(self, item):
        """The card made (again) in its holder; the holder shown in its place while it holds something. A card on show is
        made anew in a holder of its own laid over it, then put in its place: the old card stays on the screen until the
        new one is drawn whole, never a gap where it was."""
        holder = item["holder"]
        if holder.winfo_children() and holder.winfo_ismapped():
            self._swap(item)
            return
        for child in holder.winfo_children():
            child.destroy()
        item["build"](holder)
        # The gap between two cards is the holders' (_gaps), not the cards' own: a card made last today may have
        # another under it tomorrow.
        for child in holder.pack_slaves():
            child.pack_configure(pady=0)
        # What it was made for, as the state is once it is made (a builder may start work that changes it).
        item["made"] = item["key"]()
        shown = bool(holder.winfo_children())
        if shown and not holder.winfo_manager():
            later = [i["holder"] for i in self.items[self.items.index(item) + 1:] if i["holder"].winfo_manager()]
            fill = {"fill": "both", "expand": True} if item["expand"] else {"fill": "x"}
            if later:
                holder.pack(before=later[0], **fill)
            else:
                holder.pack(**fill)
        elif not shown and holder.winfo_manager():
            holder.pack_forget()
        if not shown:
            # Packed again later with its gap set afresh.
            item["gap"] = None
        self._gaps()

    def _swap(self, item):
        """The card on show made anew over it, laid out and drawn there, then put in its place (_make)."""
        self._put(self._over(item))

    def _over(self, item):
        """The new card for `item` made in a holder of its own laid over the old one (as wide as it, as tall as it asks),
        so that it is laid out and drawn while the old one is still under it. Returns (item, the new holder)."""
        old = item["holder"]
        fresh = tk.Frame(self.parent, bg=self.parent.cget("bg"))
        fresh.place(in_=old, x=0, y=0, relwidth=1.0)
        item["build"](fresh)
        for child in fresh.pack_slaves():
            child.pack_configure(pady=0)
        return item, fresh

    def _put(self, made, laid=False):
        """The new holder in the old one's place, with its packing, and the old one gone: one change of the page's
        layout. `laid`: the new one was laid out already (refresh lays out all of them at once)."""
        item, fresh = made
        old = item["holder"]
        if not laid:
            fresh.update_idletasks()
        info = old.pack_info()
        fresh.place_forget()
        info.pop("in", None)
        fresh.pack(before=old, **info)
        old.destroy()
        item["holder"] = fresh
        item["made"] = item["key"]()
        if not fresh.winfo_children():
            # The card went (nothing to show now): its place goes too.
            fresh.pack_forget()
            item["gap"] = None
        self._gaps()

    def _gaps(self):
        """The cards' gap above each shown card but the first."""
        first = True
        for item in self.items:
            holder = item["holder"]
            if not holder.winfo_manager():
                continue
            wanted = 0 if first else self.ui.px(CARD_GAP)
            if item["gap"] != wanted:
                holder.pack_configure(pady=(wanted, 0))
                item["gap"] = wanted
            first = False

    def refresh(self):
        """Each card whose key changed made again in its place; True when any was. The cards on show that change are
        made over their old ones first, all of them laid out and drawn together, then all put in place at once: one
        change of the page's layout whatever the number of cards."""
        changed = False
        over = []
        for item in self.items:
            if not item["holder"].winfo_exists():
                return changed
            if item["key"]() != item["made"]:
                changed = True
                if item["holder"].winfo_children() and item["holder"].winfo_ismapped():
                    over.append(self._over(item))
                else:
                    self._make(item)
        if over:
            self.parent.update_idletasks()
            for made in over:
                self._put(made, laid=True)
        if changed and self.after is not None:
            # What the page does once a card of it is made again (its names' column fitted to the new rows).
            self.after()
        return changed

# The names of the setting rows the PC brings to a page or takes from it (the game's log once the game has run, Repair and
# Uninstall in an installed launcher): counted in the page's names' column whether shown or not (widgets.fit_names), so
# that none of them moves the controls when it comes. The rows a choice brings (a window's size, the counter's corner,
# the upscaler) are made with their page, hidden while they do not apply, and counted as they are.
ROWS_THAT_COME = {
    "help": ("help.player_log", "help.repair.row", "help.uninstall.row"),
}


def rows_that_come(page):
    """The names of ROWS_THAT_COME[page] in both languages, for widgets.fit_names."""
    return [words for key in ROWS_THAT_COME.get(page, ()) for words in i18n.TEXT[key] if words]


def _columns(parent, ui, weights=(3, 2), gap_above=0):
    """Cards side by side: a frame for each column, as wide as its share of the row less the gaps; one under another
    when the row is narrower than STACK_BELOW (the smallest window, beside the menu column). The shares come from the
    row's own width alone: a grid that sized them from what they hold would loop for ever, as the text in each wraps to
    the width it is given and so asks for what it got (one pixel going back and forth between the columns)."""
    row = tk.Frame(parent, bg=theme.BG)
    row.pack(fill="x", pady=(ui.px(gap_above), 0))
    columns = []
    for i in range(len(weights)):
        column = tk.Frame(row, bg=theme.BG)
        columns.append(column)
    laid = {"stacked": None}

    def fit(event):
        stacked = event.width < ui.px(STACK_BELOW)
        if stacked != laid["stacked"]:
            # Laid out again only when the arrangement changes: the cells' places, then their widths below.
            laid["stacked"] = stacked
            for i, column in enumerate(columns):
                if stacked:
                    column.grid(row=i, column=0, sticky="nsew", padx=0, pady=(ui.px(CARD_GAP) if i else 0, 0))
                else:
                    column.grid(row=0, column=i, sticky="nsew", padx=(ui.px(CARD_GAP) if i else 0, 0), pady=0)
        if stacked:
            row.columnconfigure(0, minsize=event.width, weight=0)
            for i in range(1, len(weights)):
                row.columnconfigure(i, minsize=0, weight=0)
            return
        room = max(1, event.width - ui.px(CARD_GAP) * (len(weights) - 1))
        given = 0
        for i, weight in enumerate(weights):
            width = room * weight // sum(weights) if i < len(weights) - 1 else room - given
            given += width
            row.columnconfigure(i, minsize=width + (ui.px(CARD_GAP) if i else 0), weight=0)

    row.bind("<Configure>", fit)
    # Side by side until the row is laid out (the first <Configure> settles it).
    for i, column in enumerate(columns):
        column.grid(row=0, column=i, sticky="nsew", padx=(ui.px(CARD_GAP) if i else 0, 0))
    row.odq_stacked = lambda: bool(laid["stacked"])
    return columns


# A row of cards side by side narrower than this (logical pixels) puts them one under another.
STACK_BELOW = 760


# ---------------------------------------------------------------------------------------------- PLAY


def _server_card(app, parent):
    """Where PLAY plays: the server, its address, and the account signed in there."""
    ui, w = app.ui, app.words
    card = _card(parent, ui, w("play.server"))
    server = app.state.server()
    line = tk.Frame(card.body, bg=theme.PANEL)
    line.pack(fill="x")
    if server is None:
        widgets.label(line, ui, w("play.no_server"), fg=theme.MUTED, wrap_margin=0).pack(side="left", fill="x",
                                                                                         expand=True)
        main_button(app, line, w("play.connect"), lambda: app.nav_go("online")).pack(side="right")
        return
    signed = app.state.signed_in(server)
    if not signed:
        main_button(app, line, w("online.signin"), lambda: app.nav_go("online")).pack(side="right", anchor="n")
    words = tk.Frame(line, bg=theme.PANEL)
    words.pack(side="left", fill="x", expand=True)
    if st.has_own_name(server):
        # Its name, and its address under it.
        widgets.label(words, ui, server["name"], font=ui.fonts.body_bold, wrap_margin=0).pack(fill="x")
        widgets.label(words, ui, server["url"], font=ui.fonts.small, fg=theme.MUTED, wrap_margin=0).pack(fill="x")
    else:
        # A server with no name of its own calls itself by its address: said once, in the name's place.
        widgets.label(words, ui, server["url"], font=ui.fonts.body_bold, wrap_margin=0).pack(fill="x")
    widgets.divider(card.body, ui)
    account = (w("play.signed", account=server["account"]) if signed else
               w("play.not_signed", account=server["account"]) if server.get("account") else w("play.no_account"))
    state = widgets.check_line(card.body, ui, "ok" if signed else "change", account)
    state.pack(fill="x")


def build_play(app, parent):
    ui, w = app.ui, app.words
    # The server's card over the two columns, made again only when the server or its sign-in changed.
    top = Sections(parent, ui)
    top.add(lambda: _server_key(app), lambda holder: _server_card(app, holder))
    left, right = _columns(parent, ui, gap_above=CARD_GAP)
    # Left: the ready check, filled in when the worker thread finishes it, as tall as the column, so that the row's cards
    # end on one line. Check again stands at its title's right end, as on Help, and its rows from the top: the room the
    # column gives it lies under them (client/tests/ui/shots.py, play_fits).
    ready = widgets.Card(left, ui, w("play.ready"))
    ready.pack(fill="both", expand=True)
    widgets.Button(ready.head, ui, w("help.recheck"), lambda: app.refresh_checks(force=True)).pack(side="right")
    app.check_box = tk.Frame(ready.body, bg=theme.PANEL)
    app.check_box.pack(fill="x")
    # Right: how to play, keyboard play first, and how the last game went, the last as tall as what is left of the
    # column; each made again only when what it says changed (the keys, the game that ended).
    side = Sections(right, ui)
    side.add(lambda: tuple(app.state.values[name] for name in ("keyboard",) + tuple(choices.LANES)) + (w.language,),
             lambda holder: how_to_play(app, _card(holder, ui, w("play.how")).body))
    side.add(lambda: repr(sorted((app.state.last_session or {}).items())), lambda holder: _last_card(app, holder),
             expand=True)
    app.page_follow = lambda: (top.refresh(), side.refresh())
    # Made again each time the page shows: a sign-in can have ended, or an app come, since the last one. Until it
    # comes back, the box says it is being made.
    app.refresh_checks()
    refresh_checks(app)


def _server_key(app):
    """What the PLAY page's server card shows: the server, its name, its sign-in."""
    server = app.state.server()
    if server is None:
        return None
    return (server["url"], server["name"], st.has_own_name(server), app.state.signed_in(server), server.get("account"))


def _last_card(app, holder):
    """The PLAY page's Last game: how the last game went, and the player's log one press away after a crash."""
    ui, w = app.ui, app.words
    last = widgets.Card(holder, ui, w("play.last"))
    last.pack(fill="both", expand=True)
    record = app.state.last_session or {}
    if record.get("crashed") or record.get("failed_start"):
        # The reason is in the player's log: one press away, on the card's own line at its title's right end (as Help
        # has Check again).
        widgets.Button(last.head, ui, w("status.open_log"), app.open_player_log).pack(side="right")
    widgets.label(last.body, ui, _last_session(app), fg=theme.MUTED, wrap_margin=0).pack(fill="x")


# How to play's lines after keyboard play's: the touch screen and the mouse in one, so that the card and Last game
# under it end above the bottom bar at the window's own size, then Esc and leaving the game by the bar.
HOW_TO_PLAY = ("play.how.1", "play.how.3")


def keys_line(w, values):
    """How to play's first line, keyboard play as the settings have it now (the Controls page or --set): each LINE
    mode's keys from its top lane ("F J in 2 LINE, ..."), a lane's second key after a /, or that it is off."""
    if values["keyboard"] != "on":
        # Off: the line says so, and the link beside it leads where it is turned on.
        return w("play.how.keys.off")
    # Each mode in the game's own order (2, 3, then 4 LINE), with its lanes as the settings file writes them.
    modes = [w("play.how.keys.mode", keys=values[name], mode=choices.mode(name)) for name in choices.LANES]
    return w("play.how.keys", lanes=", ".join(modes))


def how_to_play(app, body, link=True):
    """How to play's lines in a card's body, on PLAY and on the guide's STAGE START: keyboard play first, as the settings
    have it, with the Controls page one press away (`link`; the guide has no menu to go to), then HOW_TO_PLAY's."""
    ui, w = app.ui, app.words
    # Keyboard play's line, its link at the right end as Help's lines have theirs.
    line = tk.Frame(body, bg=theme.PANEL)
    line.pack(fill="x")
    beside = ()
    if link:
        # The page the keys are set on, by the menu's own name, reached by the mouse or the keyboard.
        to = widgets.link(line, ui, TITLES["controls"], lambda: app.nav_go("controls"))
        to.pack(side="right", anchor="n")
        beside = (to,)
    widgets.label(line, ui, keys_line(w, app.state.values), wrap_margin=12, beside=beside).pack(side="left", fill="x")
    for key in HOW_TO_PLAY:
        # One line each, split by the card's faint lines as the ready check's rows are.
        widgets.divider(body, ui, pady=CHECK_GAP)
        widgets.label(body, ui, w(key), wrap_margin=0).pack(fill="x")


def _last_session(app):
    record, w = app.state.last_session, app.words
    if not record:
        return w("play.last.none")
    minutes = record.get("seconds", 0) // 60
    span = w("common.minutes", m=minutes) if minutes else w("common.seconds", s=record.get("seconds", 0))
    if record.get("failed_start"):
        return w("play.last.failed")
    return w("play.last.crash" if record.get("crashed") else "play.last.ok", time=span)


def refresh_checks(app):
    """Fill the ready check (PLAY page, Help page, the guide's last step) from app.checks: a row a line, each with its
    lamp, its name, and at the right end what it is about or the way to fix it. The rows are made again only when what
    they say changed: a check that came back the same (the window asks again every half minute) leaves them be."""
    box = getattr(app, "check_box", None)
    if box is None or not box.winfo_exists():
        return
    ui, w = app.ui, app.words
    # While a check is made (it may ask the server for a few seconds), the last one that came back stays on show: the
    # rows do not blink to "..." and back each time a page asks for one.
    checks = app.checks if app.checks is not None else getattr(app, "shown_checks", None)
    if checks is None:
        if getattr(box, "odq_shown", None) != "waiting":
            for child in box.winfo_children():
                child.destroy()
            widgets.label(box, ui, "...", fg=theme.MUTED).pack(anchor="w")
            box.odq_shown = "waiting"
        return
    from opendmtq_client import installed
    # Asked once for every row: whether this launcher was installed, so that its player can be put back by Repair.
    root = installed.root()
    rows = [(check, check_row(check, w, on_play=app.page == "play" and app.guide is None, in_guide=app.guide is not None,
                              installed=bool(root))) for check in checks]
    # What the rows say, in the window's language: the same as on show, nothing is made again.
    shown = tuple((check.key, w("check." + check.key), tuple(sorted(row.items()))) for check, row in rows)
    if getattr(box, "odq_shown", None) == shown:
        return
    for child in box.winfo_children():
        child.destroy()
    box.odq_shown = shown
    for i, (check, row) in enumerate(rows):
        if i:
            widgets.divider(box, ui, pady=CHECK_GAP)
        # The row's way on: Repair runs here, a page name opens that page (none in the guide, which has no menu).
        action = None
        if row["go"] == "repair":
            # Repair runs on the click, under its own dialog.
            action = lambda: maintenance.repair_program(app)
        elif row["go"]:
            # The page it names, as the menu would open it.
            action = lambda p=row["go"]: app.nav_go(p)
        widgets.check_line(box, ui, row["state"], w("check." + check.key), row["link"], action,
                           value=row["value"]).pack(fill="x")


# The room either side of the faint line between two rows of a list in a card (the ready check, Help's lines, the
# Controls page's lines), in logical pixels: on the launcher's spacing scale.
CHECK_GAP = 8


def check_row(check, w, on_play=False, in_guide=False, installed=False):
    """How a ready-check row says one check: {"state": "ok", "change" or "bad", "value": words at the right end or None,
    "link": the link's words or None, "go": "repair", a page's name or None}. A link is named after where it leads, as
    Help's lines name their pages: the page's name in the menu ("ONLINE ›"), or Repair, which runs at once."""
    row = {"state": "ok", "value": None, "link": None, "go": None}
    if not check.ok and check.key == "player" and installed:
        # The player comes with the launcher: the installed one puts it back from its package, at once.
        row.update(state="bad", link=w("check.player.repair"), go="repair")
    elif not check.ok and check.key == "player":
        # A copied folder: installing brings the player back, and no page here can.
        row.update(state="bad", value=w("check.player.missing"))
    elif check.ok:
        # What it is about, which a player wants to confirm: the server, the account, the app's date. The PLAY page's
        # server card above already names the server and the account.
        about = ("app",) if on_play else ("server", "account", "app")
        if check.key in about:
            row["value"] = check.detail
    elif check.play_fixes:
        # PLAY does these by itself; the row only says it will.
        row.update(state="change", value=w("play.will_get"))
    elif not check.blocks and check.key == "server":
        # The server does not answer: nothing to fix on this PC, and PLAY still plays this PC's app.
        row.update(state="change", value=w("check.server.down"))
    else:
        # What stops PLAY is a problem; the rest will change once the player sees to it.
        row["state"] = "bad" if check.key in actions.BLOCKING else "change"
        if check.page and not in_guide:
            # The page that sees to it, by the menu's own name; the guide has no menu to go to, so no link there.
            row.update(link=TITLES[check.page], go=check.page)
    return row


# -------------------------------------------------------------------------------------------- Screen


def screen_rows(app, parent, full=True):
    """The Screen page's settings in their cards, which the guide's SOUND CHECK shows too (full=False: the ones a first
    start needs). Every row is made once: a choice changes its own control, the hints that follow from it and the rows
    it brings or takes (shown or hidden in place, widgets.RowList), never the page (client/tests/ui/flicker.py)."""
    ui, w, v = app.ui, app.words, app.state.values
    display = displays.main_display(app.root)
    found = displays.connected()
    rows = {}

    def setter(name, value):
        app.changed(name, value)
        # The rows and hints that follow from it, in place.
        follow()

    card = _card(parent, ui, w("screen.display"))
    shown = widgets.RowList(card.body, ui)
    shown.pack(fill="x")
    slot = shown.add()
    rows["mode"] = widgets.setting_row(
        slot.body, ui, w("screen.mode"),
        lambda p: widgets.Segmented(p, ui, [("fullscreen", w("screen.mode.fullscreen")), ("window", w("screen.mode.window"))],
                                    v["display"], lambda value: setter("display", value)),
        w("screen.mode.hint." + v["display"]))
    rows["mode"].pack(fill="x")
    if full:
        # Sizes that fit the display with room for the title bar and the taskbar (values.fits, which --set window= uses
        # too); fitted always stays.
        sizes = [size for size in choices.WINDOW_SIZES if choices.fits(size, display)]
        if v["window"] not in sizes:
            # A size set on the command line keeps its row.
            sizes.append(v["window"])
        options = [(size, w("screen.size.auto") if size == "auto" else size.replace("x", " × ")) for size in sizes]
        rows["size_slot"] = shown.add(shown=v["display"] == "window")
        widgets.setting_row(rows["size_slot"].body, ui, w("screen.size"),
                            lambda p: widgets.Select(p, ui, options, v["window"], lambda size: setter("window", size),
                                                     width=22),
                            w("screen.size.hint")).pack(fill="x")
        slot = shown.add()
        widgets.label(slot.body, ui, displays_line(w, display, found), font=ui.fonts.small, fg=theme.MUTED,
                      wrap_margin=0).pack(fill="x")
    # The frame limits: the display's own rate, every rate up to the fastest display's, and no limit (fps_options).
    # The main display's rate as it runs a game (game_rate), for the hints when the displays are not listed.
    hz = game_rate(display)
    card = _card(parent, ui, w("screen.frames"), last=not full)
    frames = widgets.RowList(card.body, ui)
    frames.pack(fill="x")
    rows["vsync"] = widgets.setting_row(
        frames.add().body, ui, w("screen.vsync"),
        lambda p: widgets.Toggle(p, ui, v["vsync"] == "on", lambda on: setter("vsync", "on" if on else "off")), " ")
    rows["vsync"].pack(fill="x")
    rows["fps"] = widgets.setting_row(
        frames.add().body, ui, w("screen.fps"),
        lambda p: widgets.Select(p, ui, fps_options(w, found, hz, v["fps"]), v["fps"], lambda f: setter("fps", f),
                                 width=22), " ")
    rows["fps"].pack(fill="x")
    # The frame counter over the game, on or off; while on, its corner (the bottom right unless another is picked).
    rows["counter"] = widgets.setting_row(
        frames.add().body, ui, w("screen.counter"),
        lambda p: widgets.Toggle(p, ui, v["show_fps"] == "on", lambda on: setter("show_fps", "on" if on else "off")),
        " ")
    rows["counter"].pack(fill="x")
    options = [(corner, w("screen.counter.position." + corner)) for corner in choices.FPS_POSITION]
    rows["corner_slot"] = frames.add(shown=v["show_fps"] == "on")
    widgets.setting_row(rows["corner_slot"].body, ui, w("screen.counter.position"),
                        lambda p: widgets.Select(p, ui, options, v["fps_position"],
                                                 lambda corner: setter("fps_position", corner), width=22),
                        w("screen.counter.position.hint")).pack(fill="x")
    if full:
        card = _card(parent, ui, w("screen.picture"), last=True)
        picture = widgets.RowList(card.body, ui)
        picture.pack(fill="x")
        options = [(scale, w("screen.scale.full") if scale == "100" else "%s%%" % scale) for scale in choices.RENDER_SCALE]
        widgets.setting_row(picture.add().body, ui, w("screen.scale"),
                            lambda p: widgets.Select(p, ui, options, v["render_scale"],
                                                     lambda scale: setter("render_scale", scale), width=22),
                            w("screen.scale.hint")).pack(fill="x")
        # What makes the picture of a lower scale the area's size, there only below 100 %; its hint says what the
        # chosen one does.
        options = [(kind, w("screen.upscaler." + kind)) for kind in choices.UPSCALER]
        rows["upscaler_slot"] = picture.add(shown=v["render_scale"] != "100")
        rows["upscaler"] = widgets.setting_row(
            rows["upscaler_slot"].body, ui, w("screen.upscaler"),
            lambda p: widgets.Select(p, ui, options, v["upscaler"], lambda kind: setter("upscaler", kind), width=22), " ")
        rows["upscaler"].pack(fill="x")
        # The edges smoothed, at any scale; its hint says what the chosen one does.
        options = [(kind, w("screen.aa." + kind)) for kind in choices.ANTI_ALIASING]
        rows["aa"] = widgets.setting_row(
            picture.add().body, ui, w("screen.aa"),
            lambda p: widgets.Select(p, ui, options, v["anti_aliasing"], lambda kind: setter("anti_aliasing", kind),
                                     width=22), " ")
        rows["aa"].pack(fill="x")

    def follow():
        """The hints and the rows that follow from the settings as they are now, in place."""
        values = app.state.values
        if not rows["mode"].winfo_exists():
            # The page went (another page, the guide's next step) before a late change came.
            return
        rows["mode"].say(w("screen.mode.hint." + values["display"]))
        vsync = values["vsync"] == "on"
        rows["vsync"].say(w("screen.vsync.hint." + ("on" if vsync else "off")))
        rows["fps"].control.set_options(fps_options(w, found, hz, values["fps"]), values["fps"])
        rows["fps"].say(fps_hint(w, vsync, values["fps"], single_rate(found, hz)))
        counter = values["show_fps"] == "on"
        rows["counter"].say(w("screen.counter.hint." + ("on" if counter else "off")))
        frames.show(rows["corner_slot"], counter)
        if full:
            shown.show(rows["size_slot"], values["display"] == "window")
            picture.show(rows["upscaler_slot"], values["render_scale"] != "100")
            rows["upscaler"].say(w("screen.upscaler.hint." + values["upscaler"]))
            rows["aa"].say(w("screen.aa.hint." + values["anti_aliasing"]))

    follow()
    return follow


def game_rate(display):
    """The rate a display runs a game at: the highest of its modes at its size (Windows runs a panel with a dynamic
    refresh rate at 60 Hz while the desktop is still, and at its full rate once a game asks, as the player does), unless
    Windows says its rate is not dynamic, when the rate it is set to now is the one."""
    if display.get("drr") is False and display.get("hz"):
        return display["hz"]
    return display.get("top") or display.get("hz")


def displays_line(w, display, found):
    """The line under the display's rows: the main display's size and the rate it runs a game at (with its highest when
    it is set lower), then the other displays' rates when there are others ("Other displays: 180 Hz")."""
    rate = game_rate(display)
    line = w("screen.main", w=display["width"], h=display["height"]) + (w("screen.main.hz", hz=rate) if rate else "")
    top = display.get("top")
    if rate and top and top > rate:
        # Set lower than it can run: what it can run at too.
        line += w("screen.main.up_to", top=top)
    others = [d for d in found if not d.get("main")]
    if others:
        rates = ", ".join("%d Hz" % game_rate(d) for d in others if game_rate(d))
        if rates:
            line += " · " + w("screen.others", rates=rates)
    return line


def single_rate(found, hz):
    """The one rate the hints can name: the main display's game rate (game_rate) when no other display runs at another,
    else None (the game may play on either, and its rate follows the display it is on). `hz` is the main display's when
    the displays are not listed (no Windows to ask)."""
    rates = {game_rate(d) for d in found if game_rate(d)}
    if len(rates) > 1:
        return None
    if rates:
        return rates.pop()
    return hz


def fps_choices(found, current):
    """The frame limits the Screen page offers, as the settings file writes them: the display's own rate (auto), every
    rate up to the fastest connected display's (displays.frame_limits: 160, 165 and 180 Hz displays offer their own),
    and no limit; the `current` one keeps its row all the same (one set on the command line)."""
    offered = ["auto"] + [str(rate) for rate in displays.frame_limits(found)] + ["unlimited"]
    return offered + ([current] if current not in offered else [])


def fps_options(w, found, hz, current):
    """fps_choices as the drop-down's (value, words): the display's rate by its number when one rate is known."""
    rate = single_rate(found, hz)
    auto = w("screen.fps.auto.hz", hz=rate) if rate else w("screen.fps.auto")
    return [(f, auto if f == "auto" else w("screen.fps.unlimited") if f == "unlimited" else w("screen.fps.n", n=f))
            for f in fps_choices(found, current)]


def fps_hint(w, vsync, fps, hz):
    """The frame limit's hint for its value: without VSync, the game holds it itself; with VSync, the display's own
    rate, or on a display whose rate is known, what this limit gives there (exactly, very nearly, or held at the rate:
    values.vsync_refreshes, as the player paces the frames)."""
    if not vsync:
        return w("screen.fps.hint.free")
    if fps == "auto":
        return w("screen.fps.hint.vsync_rate")
    if not hz:
        return w("screen.fps.hint.vsync")
    if choices.above_rate(hz, fps):
        # Above the display's rate: every refresh, no more.
        return w("screen.fps.hint.vsync.above", hz=hz)
    refreshes = choices.vsync_refreshes(hz, fps)
    if refreshes:
        # Each frame the same number of refreshes: the rate a whole fraction of the display's.
        return w("screen.fps.hint.vsync.exact", hz=hz, fps=int(round(hz / float(refreshes))))
    return w("screen.fps.hint.vsync.near", hz=hz, n=fps)


def _focus_order(widget):
    """The widgets under `widget` that take the keyboard, in the order Tab visits them (the page's packing order)."""
    found = []
    for child in widget.winfo_children():
        # A widget that takes the keyboard (a drop-down, a toggle, a segment) is one stop; what is inside it is not.
        # Asked of Tk itself: a widget may have a `keys` of its own, and one without the option takes no keyboard.
        try:
            takes = str(child.cget("takefocus"))
        except tk.TclError:
            takes = ""
        if takes not in ("", "0"):
            found.append(child)
        else:
            found.extend(_focus_order(child))
    return found


def keep_place(area, root, rebuild):
    """A page area drawn again by `rebuild()` for a change (a choice that adds or removes rows, an answer that came),
    keeping where it was scrolled to and the control the keyboard was on: choosing a buffer at the Sound page's foot,
    or switching VSync on the guide's SOUND CHECK, does not throw the page back to its top and the keyboard out of it."""
    top = area.canvas.yview()[0]
    before = _focus_order(area.inner)
    focused = root.focus_get()
    index = before.index(focused) if focused in before else None
    rebuild()
    # Laid out first, so that the scroll's place is measured on the new page's height.
    root.update_idletasks()
    area.canvas.yview_moveto(top)
    if index is not None:
        # The rows before the changed one are the same, so the same place in the order is the same control.
        after = _focus_order(area.inner)
        if index < len(after):
            after[index].focus_set()


def redraw_in_place(app, page):
    """A page of the launcher drawn again in place (keep_place)."""
    keep_place(app.body, app.root, lambda: app.go(page))


def build_screen(app, parent):
    app.page_follow = screen_rows(app, parent)


# --------------------------------------------------------------------------------------------- Sound


def decibels(w, n):
    """A band's level as the Sound page says it: "+3 dB", "0 dB", "-3 dB"."""
    return w("sound.db", sign="+" if n > 0 else "-" if n < 0 else "", n=abs(n))


def sound_rows(app, parent, full=True):
    """The Sound page's settings in their cards, which the guide's SOUND CHECK shows too (full=False: the volumes
    alone). Made once: a choice changes its own control and the hints and controls that follow from it, in place (an
    equaliser's preset moves its bands, a band moved makes it Custom); the devices, when the player lists them, take
    the place of the line that waited for them. Returns follow(), which shows the settings as they are now (values the
    player's in-game menu wrote back)."""
    ui, w, v = app.ui, app.words, app.state.values
    rows = {}
    card = _card(parent, ui, w("sound.volume"), last=not full)
    volumes = widgets.RowList(card.body, ui)
    volumes.pack(fill="x")
    for name, key in (("volume", "master"), ("music_volume", "music"), ("effects_volume", "effects")):
        rows[name] = widgets.setting_row(
            volumes.add().body, ui, w("sound.volume." + key),
            lambda p, name=name: widgets.Slider(p, ui, v[name], lambda value, name=name: app.changed(name, value)),
            w("sound.volume.%s.hint" % key))
        rows[name].pack(fill="x")

    def follow():
        """The controls and hints as the settings are now, in place."""
        values = app.state.values
        if not rows["volume"].winfo_exists():
            # The page went before a late change came.
            return
        for name in choices.VOLUMES:
            rows[name].control.set(values[name])
        if full:
            rows["eq"].control.set(values["eq"])
            rows["eq"].say(w("sound.eq.hint." + values["eq"]))
            for band in choices.EQ_BANDS:
                rows[band].control.set(values[band])
            rows["mode"].say(w("sound.mode.hint." + values["audio_mode"]))
            rows["buffer"].say(w("sound.buffer.hint." + values["audio_buffer"]))

    if not full:
        return follow

    # The equaliser: a preset, or the player's own three bands; a preset sets the bands, a band moved makes it Custom.
    card = _card(parent, ui, w("sound.eq"))
    eq = widgets.RowList(card.body, ui)
    eq.pack(fill="x")

    def preset(value):
        app.changed("eq", value)
        follow()

    def band(name, value):
        app.changed(name, value)
        follow()

    rows["eq"] = widgets.setting_row(
        eq.add().body, ui, w("sound.eq.preset"),
        lambda p: widgets.Segmented(p, ui, [(kind, w("sound.eq." + kind)) for kind in choices.EQ], v["eq"], preset),
        w("sound.eq.hint." + v["eq"]))
    rows["eq"].pack(fill="x")
    least, most = choices.EQ_RANGE
    for name, key in zip(choices.EQ_BANDS, ("low", "mid", "high")):
        rows[name] = widgets.setting_row(
            eq.add().body, ui, w("sound.eq." + key),
            lambda p, name=name: widgets.Slider(p, ui, v[name], lambda value, name=name: band(name, value), least=least,
                                                most=most, step=1, say=lambda n: decibels(w, n)))
        rows[name].pack(fill="x")

    card = _card(parent, ui, w("sound.output"), last=True)
    output = widgets.RowList(card.body, ui)
    output.pack(fill="x")
    device_slot = output.add()

    def device_row():
        """The device's row: the line that waits for the player's list, or the drop-down once it came."""
        for child in device_slot.body.winfo_children():
            child.destroy()
        if app.devices is None:
            widgets.setting_row(device_slot.body, ui, w("sound.device"),
                                lambda p: widgets.label(p, ui, w("sound.device.looking"), fg=theme.MUTED)).pack(fill="x")
            return
        values = app.state.values
        options = [("default", w("sound.device.default"))]
        options += [(d["id"], d["name"] + (w("sound.device.now_default") if d["default"] else "")) for d in app.devices]
        if values["audio_device"] != "default" and all(d["id"] != values["audio_device"] for d in app.devices):
            # A device chosen before that is not there now (unplugged): it stays chosen, and says so.
            options.append((values["audio_device"], w("sound.device.gone")))
        widgets.setting_row(device_slot.body, ui, w("sound.device"),
                            lambda p: widgets.Select(p, ui, options, values["audio_device"],
                                                     lambda d: app.changed("audio_device", d), width=34),
                            w("sound.device.hint" if app.devices else "sound.device.none")).pack(fill="x")
        # The page's names' column counts the new row's name as it counted the one before.
        widgets.fit_names(parent, ui)

    device_row()
    if app.devices is None:
        # Asked once from the player, on a worker thread; the row alone is made again with the answer, while it is on
        # show (another page or step since leaves it be).
        app.load_devices(then=lambda: device_slot.winfo_exists() and device_row())

    def setter(name):
        def chosen(value):
            app.changed(name, value)
            follow()
        return chosen

    rows["mode"] = widgets.setting_row(
        output.add().body, ui, w("sound.mode"),
        lambda p: widgets.Segmented(p, ui, [("shared", w("sound.mode.shared")), ("exclusive", w("sound.mode.exclusive"))],
                                    v["audio_mode"], setter("audio_mode")),
        w("sound.mode.hint." + v["audio_mode"]))
    rows["mode"].pack(fill="x")
    rows["buffer"] = widgets.setting_row(
        output.add().body, ui, w("sound.buffer"),
        lambda p: widgets.Segmented(p, ui, [("low", w("sound.buffer.low")), ("normal", w("sound.buffer.normal")),
                                            ("safe", w("sound.buffer.safe"))], v["audio_buffer"], setter("audio_buffer")),
        w("sound.buffer.hint." + v["audio_buffer"]))
    rows["buffer"].pack(fill="x")
    return follow


def build_sound(app, parent):
    # Changed in place; the window keeps follow() for values the player's in-game menu writes back (app.took_back).
    app.page_follow = sound_rows(app, parent)


# ------------------------------------------------------------------------------------------ Controls


def build_controls(app, parent):
    ui, w = app.ui, app.words
    # First keyboard play, the page's one card of settings: on or off, and while on, the lanes' keys.
    lanes_card(app, parent)
    # The game's bar over it in each group by the way it comes: the pointer, a finger, and the keys it does not take.
    groups = (("controls.mouse", ("controls.click", "controls.drag", "controls.wheel", "controls.menu",
                                  "controls.minimise")),
              ("controls.touch", ("controls.fingers", "controls.edges", "controls.bar")),
              ("controls.keyboard", ("controls.esc", "controls.alt_f4", "controls.typing")))
    for n, (title, keys) in enumerate(groups):
        card = _card(parent, ui, w(title), last=n == len(groups) - 1)
        for i, key in enumerate(keys):
            # One line each, split by the card's faint lines.
            if i:
                widgets.divider(card.body, ui, pady=CHECK_GAP)
            widgets.label(card.body, ui, w(key), wrap_margin=0).pack(fill="x")


def lanes_card(app, parent):
    """Keyboard play's card: the switch for it and, while it is on, each LINE mode's lanes with their keys (LaneKeys)
    and Reset keys at the card's title. The lanes are made with the page and shown or hidden in place by the switch, the
    rest of the page as it was."""
    ui, w = app.ui, app.words
    card = _card(parent, ui, w("controls.keys"))
    on = app.state.values["keyboard"] == "on"
    # The title's line as tall as it is with Reset keys on it, whether that is there or not: the switch stays where it
    # was, under the pointer that switched it.
    tk.Frame(card.head, bg=theme.PANEL, width=1, height=ui.px(widgets.Button.HEIGHT)).pack(side="right")
    rows = widgets.RowList(card.body, ui)

    def switch(value):
        app.changed("keyboard", "on" if value else "off")
        row.say(w("controls.keys.play.hint." + ("on" if value else "off")))
        rows.show(holder, value)
        table.show_reset(value)

    row = widgets.setting_row(rows.add().body, ui, w("controls.keys.play"), lambda p: widgets.Toggle(p, ui, on, switch),
                              w("controls.keys.play.hint." + ("on" if on else "off")))
    row.pack(fill="x")
    rows.pack(fill="x")
    # Where the lanes go, under the switch: made whether shown or not, so that the switch only shows them.
    holder = rows.add(shown=on)
    table = LaneKeys(app, card, holder.body)
    table.show_reset(on)


class LaneKeys:
    """The lanes of each LINE mode, from the top, with their keys: a block for each of 2, 3 and 4 LINE, side by side
    while the card holds them so (one under another in a narrow window with long keys), each lane's number before a box
    for its key and one for a second key (widgets.KeyBox).

    A click on a box (or Enter or Space on it) makes it wait for a key; the key pressed goes in by its place on the
    keyboard (keys.place_of), unless the mode plays it in another box, or no lane takes it: refused in words on the line
    under the table, and the box waits on. Esc keeps what was there, Delete removes one of a lane's two keys, Tab goes
    on to the next control, a click on the waiting box stops the wait. A key taken is saved at once and the page drawn
    again in place, the keyboard on the same box. Reset keys, at the card's title, puts the defaults back. While a box
    waits, Windows' input method is off on the window that gets the keys (keys.typing_off), and a key held down counts
    once: its repeats count from its release on."""

    # The room between two modes' blocks side by side, or one under another, after a lane's number, between a lane's
    # two boxes, and above and under each lane (logical pixels).
    COLUMN_GAP, ROW_GAP, NUMBER_GAP, BOX_GAP, LANE_GAP = 32, 16, 12, 6, 3

    def _flow(self):
        """The modes' blocks side by side when the card holds them so, else one under another; laid out again only
        when that changes (the card's width alone decides it, never what the blocks are given)."""
        if not self.table.winfo_exists():
            return
        px = self.ui.px
        body = self.card.body
        room = body.winfo_width() - 2 * int(body.cget("padx"))
        if room <= 1:
            # Not laid out yet: once it is, the card's <Configure> asks again.
            room = None
        need = sum(block.winfo_reqwidth() for block in self.blocks) + px(self.COLUMN_GAP) * (len(self.blocks) - 1)
        across = room is None or need <= room
        if across == self.across:
            return
        self.across = across
        for i, block in enumerate(self.blocks):
            block.pack_forget()
        for i, block in enumerate(self.blocks):
            if across:
                block.pack(side="left", anchor="n", padx=(px(self.COLUMN_GAP) if i else 0, 0))
            else:
                block.pack(side="top", anchor="w", pady=(px(self.ROW_GAP) if i else 0, 0))

    def show_reset(self, shown):
        """Reset keys at the card's title while the lanes show, gone while keyboard play is off."""
        if shown and not self.reset_button.winfo_manager():
            self.reset_button.pack(side="right")
        elif not shown and self.reset_button.winfo_manager():
            self.reset_button.pack_forget()

    @staticmethod
    def clear(card, holder):
        """The lanes and Reset keys gone from the card (before they are made again)."""
        for child in holder.winfo_children():
            child.destroy()
        for child in card.head.winfo_children():
            if isinstance(child, widgets.Button):
                child.destroy()

    def __init__(self, app, card, holder):
        self.app, self.ui, self.w = app, app.ui, app.words
        self.card, self.holder = card, holder
        ui, w, px = self.ui, self.w, self.ui.px
        values = app.state.values
        # Made in the holder, which keeps its place under the switch: whatever was there before goes first.
        LaneKeys.clear(card, holder)
        # The box that waits for a key, or None.
        self.waiting = None
        # The windows whose input method is off while a box waits (keys.typing_off), given back when the wait ends.
        self.typing = []
        # A plain button, as Check again is on the PLAY page: the screen's lime action stays PLAY's.
        self.reset_button = widgets.Button(card.head, ui, w("controls.keys.reset"), self.reset)
        self.reset_button.pack(side="right")
        # The line between the switch and the table is the card's rows' own (widgets.RowList).
        table = tk.Frame(holder, bg=theme.PANEL)
        table.pack(anchor="w", fill="x")
        self.table = table
        # The page going (another page, a language, the window closing) ends a wait as well: the input method comes back.
        table.bind("<Destroy>", lambda e: self.typing_back() if e.widget is table else None)
        # Whether a box shows what the keyboard prints beside its key's name: the line under the table then says what it is.
        shown = False
        # Every box, in Tab's order (again() finds the one the keyboard was on by its place).
        self.boxes = []
        # A block for each mode: its name over its lanes, each lane's number before its boxes. Side by side while the
        # card has the room, one under another when it has not (long keys in a narrow window): _flow().
        self.blocks = []
        # Made mode by mode, each from its top lane: Tab goes down a mode's lanes, then to the next mode.
        for name in choices.LANES:
            block = tk.Frame(table, bg=theme.PANEL)
            self.blocks.append(block)
            # The mode's name, as the game's tabs name it, in the launcher's wide face for English names.
            tk.Label(block, text=choices.mode(name), font=ui.fonts.step, fg=theme.MUTED, bg=theme.PANEL).grid(
                row=0, column=0, columnspan=2, sticky="w", pady=(0, px(6)))
            for lane, lane_keys in enumerate(choices.lanes_of(name, values[name])):
                # The lane's number from the top, then its boxes.
                tk.Label(block, text=str(lane + 1), font=ui.fonts.body_bold, fg=theme.MUTED, bg=theme.PANEL).grid(
                    row=lane + 1, column=0, sticky="w", padx=(0, px(self.NUMBER_GAP)))
                cell = tk.Frame(block, bg=theme.PANEL)
                cell.grid(row=lane + 1, column=1, sticky="w", pady=px(self.LANE_GAP))
                # The lane's keys, then one empty box while it has room for a second.
                for slot in range(min(len(lane_keys) + 1, choices.LANE_KEYS)):
                    key = lane_keys[slot] if slot < len(lane_keys) else None
                    print_ = keys.beside(key, keys.printed(key, app.key_prints)) if key else None
                    shown = shown or print_ is not None
                    box = widgets.KeyBox(cell, ui, key, print_)
                    box.pack(side="left", padx=(px(self.BOX_GAP) if slot else 0, 0))
                    # Which box it is: the mode's setting, the lane from the top, the box in the lane.
                    box.odq_where = (name, lane, slot)
                    self.boxes.append(box)
                    box.bind("<Button-1>", lambda e, b=box: self.clicked(b))
                    box.bind("<KeyPress>", lambda e, b=box: self.pressed(b, e))
                    # A held key's release: its next press counts again (pressed() leaves its repeats out).
                    box.bind("<KeyRelease>", self.released)
                    box.bind("<FocusOut>", lambda e, b=box: self.left(b))
        # Laid out for the card's width now, and again as the window's width changes it.
        self.across = None
        self._flow()
        card.body.bind("<Configure>", lambda e: self._flow(), add="+")
        # What to do, said under the table; what a box waits for, or why a key was refused, said in its place. The
        # line about the grey prints only while a box shows one.
        self.hint = i18n.sentences(w("controls.keys.hint"), w("controls.keys.hint.print") if shown else "")
        self.line = widgets.label(holder, ui, self.hint, font=ui.fonts.small, fg=theme.MUTED, wrap_margin=0)
        self.line.pack(fill="x", pady=(px(12), 0))
        # Tab reaches Reset keys after the boxes: the switch stays the card's first stop whether the lanes are shown or
        # not, so the page drawn again for it keeps the keyboard on it (keep_place finds a control by its place in the
        # order). Tk's Tab goes by the stacking order, so the head goes over everything the card holds, made last.
        # (Misc's own raise: the head is a frame, raised among the card's rows.)
        tk.Misc.tkraise(card.head)

    # ------------------------------------------------------------------------------------- the line under it

    def say(self, text, colour):
        """The line under the table, unless the page went meanwhile (a key's FocusOut as the page is drawn again)."""
        if self.line.winfo_exists():
            self.line.configure(text=text, fg=colour)

    def prompt(self, box):
        """What a waiting box waits for: a key for its lane (Esc keeps the one there, Delete takes away one the lane has
        a second of), or a second key."""
        name, lane, slot = box.odq_where
        mode, w = choices.mode(name), self.w
        if box.key is None:
            return w("controls.keys.wait.second", lane=lane + 1, mode=mode)
        lane_keys = choices.lanes_of(name, self.app.state.values[name])[lane]
        return i18n.sentences(w("controls.keys.wait", lane=lane + 1, mode=mode, keyname=box.key),
                              w("controls.keys.wait.delete") if len(lane_keys) > 1 else "")

    # ------------------------------------------------------------------------------------------ the wait

    def wait(self, box):
        """`box` waits for a key, with the keyboard; another box that waited stops."""
        if self.waiting is not None and self.waiting is not box:
            self.waiting.set_waiting(False)
        self.waiting = box
        box.focus_set()
        if not self.typing:
            # The input method off on the window that gets the keys, once for the whole wait (box to box included).
            self.typing = keys.typing_off(box)
        box.set_waiting(True)
        self.say(self.prompt(box), theme.TEXT)

    def typing_back(self):
        """The input method back on the windows a wait took it from: the wait is over."""
        windows, self.typing = self.typing, []
        keys.typing_back(windows)

    def stop(self):
        """No box waits any more: the line says what to do again."""
        box, self.waiting = self.waiting, None
        self.typing_back()
        if box is not None and box.winfo_exists():
            box.set_waiting(False)
        self.say(self.hint, theme.MUTED)

    def released(self, event):
        """A key let go: the key held down since it started a wait or went in counts again at its next press."""
        if event.keycode == self.app.key_held:
            self.app.key_held = None

    def clicked(self, box):
        """A click: the box waits for a key, or a waiting box stops."""
        if self.waiting is box:
            self.stop()
        else:
            self.wait(box)

    def left(self, box):
        """The keyboard went elsewhere (Tab, another box, another window): the box that waited stops."""
        if self.waiting is box:
            self.stop()

    def pressed(self, box, event):
        """A key pressed on a box: Enter or Space makes a box wait, as a button is pressed; on a waiting box, the key
        for it. "break" for a key the box took, so that nothing else of the window acts on it. A key held down counts
        once: Windows repeats its press with no release, and its repeats would take it, or refuse it, at once."""
        if event.keycode == self.app.key_held:
            # The repeat of the key that started the wait or just went in: left out until it is let go.
            return "break"
        # Another key pressed: whatever was held is over, even when its release went to another window.
        self.app.key_held = None
        if self.waiting is not box:
            if event.keysym in ("Return", "KP_Enter", "space"):
                self.wait(box)
                # Held, its repeats would take Space, or refuse Enter, in the box it just made wait.
                self.app.key_held = event.keycode
                return "break"
            # Tab and the rest go their way.
            return None
        if event.keysym in ("Tab", "ISO_Left_Tab"):
            # Tab goes on to the next control (Tk's own binding), the box as it was.
            self.stop()
            return None
        if event.keysym == "Escape":
            self.stop()
            return "break"
        name, lane, slot = box.odq_where
        lanes = choices.lanes_of(name, self.app.state.values[name])
        if event.keysym == "Delete":
            # Delete alone takes a key away (Backspace is refused by its name, as any key no lane takes).
            if box.key is None:
                # The empty box has nothing to take away: it stops waiting.
                self.stop()
                return "break"
            self.change(name, lambda: choices.without_key(name, lanes, lane, slot))
            return "break"
        key = keys.place_of(event)
        if key is None:
            said = keys.label(event)
            self.say(self.w("controls.keys.cannot", keyname=said) if said else self.w("controls.keys.cannot.any"),
                     theme.WARN)
            return "break"
        if event.char:
            # What this PC's layout printed there, for the box to show where Windows cannot be asked (keys.printed).
            self.app.key_prints[key] = event.char
        if self.change(name, lambda: choices.with_key(name, lanes, lane, slot, key), took=(lane, slot, key)):
            # In: held down, its repeats would make the same box wait and take it again, over and over.
            self.app.key_held = event.keycode
        return "break"

    def change(self, name, make, took=None):
        """The lanes `make()` gives saved, and the page drawn again in place with the keyboard on the same box; when it
        refuses (a key another lane plays, a lane's only key), its words on the line, the box still waiting. `took` is
        (lane, box, key) for a key pressed, said in the log once it is in. True once the change is saved."""
        try:
            lanes = make()
        except choices.ChoiceError as e:
            self.say(self.w.error(e), theme.WARN)
            return False
        if took is not None:
            # The key by its place and what this PC prints there: what a player chose, as the window showed it.
            lane, slot, key = took
            log.info("keyboard play: %s lane %d box %d took %s (%r on this keyboard)", choices.mode(name), lane + 1,
                     slot + 1, key, keys.printed(key, self.app.key_prints))
        self.waiting = None
        # The wait is over: the input method back before the page is drawn again.
        self.typing_back()
        self.app.changed(name, choices.lanes_text(lanes))
        self.again()
        return True

    def again(self, where=None):
        """The table made again in its place for keys that changed, the keyboard back on the same box ("reset": on Reset
        keys): only the lanes, the rest of the page as it was."""
        focused = self.app.root.focus_get()
        where = where or getattr(focused, "odq_where", None)
        fresh = LaneKeys(self.app, self.card, self.holder)
        fresh.show_reset(True)
        if where == "reset":
            # Reset keys was pressed: the keyboard stays on it.
            fresh.reset_button.focus_set()
            return
        for box in fresh.boxes:
            if box.odq_where == where:
                box.focus_set()
                break

    def reset(self):
        """Reset keys: each mode's default keys back, saved; the page drawn again in place."""
        self.waiting = None
        # A box that waited stops with the page: the input method back.
        self.typing_back()
        for name in choices.LANES:
            if self.app.state.values[name] != choices.DEFAULTS[name]:
                self.app.changed(name, choices.DEFAULTS[name])
        # Only the lanes made again, the keyboard on Reset keys again (it is the button just pressed).
        self.again(where="reset")


# -------------------------------------------------------------------------------------------- Online


def server_line(app):
    """The one line under the server's address: (words, colour). Before the server was asked in this run, the server
    PLAY plays on; then "connecting", what it answered, or why it did not (app.server_check)."""
    w, server, check = app.words, app.state.server(), app.server_check
    if check and check["state"] == "checking":
        return w("online.connecting"), theme.MUTED
    if check and check["state"] == "failed" and not check.get("seen"):
        if not server or check["url"] != server["url"]:
            # An address the player typed, not the server in use: said this once, then the line is the server's again.
            check["seen"] = True
        return w.error(check["error"]), theme.BAD
    if server and check and check["state"] == "ok" and check["url"] == server["url"]:
        return w("online.connected", name=server["name"]), theme.OK
    if server:
        return w("online.to_play", name=server["name"]), theme.MUTED
    return "", theme.MUTED


def check_server(app, address, then=None):
    """Ask the server at `address` whether it is an OpenDMTQ server, on a worker thread, and play on it when it is.
    app.server_check follows (checking, ok, failed); then() runs on the window's thread after either answer."""
    w = app.words
    try:
        # Kept as the launcher writes every address, so the answer matches the server it is about.
        address = srv.normalize(address)
    except srv.ServerError:
        # Not an address: actions.connect says so, below.
        pass
    app.server_check = {"url": address, "state": "checking"}

    def work():
        try:
            # Known and played on from the window's own thread (app.post), before answered() below runs there.
            actions.connect(app.state, address, change=app.post)
            app.post(lambda: answered({"url": app.state.current, "state": "ok"}))
        except Exception as e:  # noqa: BLE001  (ServerError, or anything else: shown, never a silent stop)
            # The system's own words for it go to the log; the window says it plainly.
            log.info("could not connect to %s: %s", address, e)
            app.post(lambda error=e: answered({"url": address, "state": "failed", "error": error}))

    def answered(check):
        app.server_check = check
        if check["state"] == "ok":
            # Connected: the field shows the server in use again, as the launcher writes its address.
            app.address_draft = None
            # Another server, or the same one again: what the last download said is not about it.
            app.download_error, app.app_note = None, None
            app.user_acted()
            app.state.save()
            app.refresh_checks()
        if then:
            then()

    threading.Thread(target=work, daemon=True, name="connect").start()


def server_tone(app):
    """The tone of server_line's words: "ok" connected, "bad" a failure, None for a plain note (connecting, the server
    to play on)."""
    check, server = app.server_check, app.state.server()
    if check and check["state"] == "failed":
        return "bad"
    if server and check and check["state"] == "ok" and check["url"] == server["url"]:
        return "ok"
    return None


# How wide the forms' fields are, in characters of the text face: the server's address, the ID and the password.
ADDRESS_CHARS, ACCOUNT_CHARS = 38, 30


def form_label(parent, ui, text, top=0):
    """A field's name over it, in the names' face, as the setting rows name theirs."""
    name = tk.Label(parent, text=text, font=ui.fonts.body_bold, fg=theme.TEXT, bg=parent.cget("bg"), anchor="w")
    name.pack(anchor="w", pady=(ui.px(top), ui.px(FORM_LABEL_GAP)))
    return name


# The room between a field's name and the field, between one field and the next name, and above a form's button
# (logical pixels).
FORM_LABEL_GAP, FORM_FIELD_GAP, FORM_BUTTON_GAP = 6, 16, 16


def connect_panel(app, parent, rerender, forget=False):
    """The server's card: its address over a field, Connect beside the field, and one line under them that says how it
    stands (server_line: connecting, connected, or why not, with its lamp). With `forget`, the server in use can be
    forgotten there too, at the card's title (the Online page; the guide only connects)."""
    ui, w = app.ui, app.words
    card = _card(parent, ui, w("online.server"))
    parent, bg = card.body, theme.PANEL
    server = app.state.server()
    form_label(parent, ui, w("online.address"))
    row = tk.Frame(parent, bg=bg)
    row.pack(fill="x")
    field = widgets.Field(row, ui, width=ADDRESS_CHARS, placeholder=w("online.address.example"))
    field.pack(side="left")
    address = field.entry
    in_use = server["url"] if server else ""
    # The field holds what the player typed until it connects or the server in use changes (app.address_draft): a
    # failed Connect keeps it, as the line under it names it, instead of the server in use or nothing coming back.
    address.insert(0, in_use if app.address_draft is None else app.address_draft)
    field.refresh()

    def remember(event=None):
        # What the field holds, kept for the page's next drawing; the address in use again is no draft.
        text = address.get()
        app.address_draft = None if text.strip() == in_use else text

    # Each key the player types (a paste with Ctrl+V too) is in the field by the time the key comes up. A binding of the
    # field's own goes with the field, where a variable traced for it would outlive every page that drew one.
    address.bind("<KeyRelease>", remember, add="+")
    answer = widgets.Said(parent, ui)
    answer.pack(fill="x", pady=(ui.px(10), 0))
    text, _colour = server_line(app)
    tone = server_tone(app)
    answer.set(text, tone)
    # A failure is about what the field holds: its edge says so too.
    field.set_error(tone == "bad")

    def connect():
        if app.busy_now():
            answer.set(w("online.busy"), "warn")
            return
        if not address.get().strip():
            # Nothing typed: said in place, nothing asked.
            answer.set(w("error.server.empty"), "bad")
            field.set_error(True)
            address.focus_set()
            return
        # What is asked is what the field holds: kept for the page drawn again with the answer.
        remember()
        check_server(app, address.get(), then=lambda: (answered(), rerender()))
        # Said at once, before the server answers.
        answer.set(w("online.connecting"))
        field.set_error(False)

    def answered():
        """The server's answer in place: the line under the field and its edge, and the address as the launcher
        writes it once it connected."""
        if not answer.winfo_exists():
            # The card was made again for another server: the new one shows the answer.
            return
        text, _colour = server_line(app)
        tone = server_tone(app)
        answer.set(text, tone)
        field.set_error(tone == "bad")
        if app.address_draft is None and app.state.current and address.get() != app.state.current:
            address.delete(0, "end")
            address.insert(0, app.state.current)
            field.refresh()

    address.bind("<Return>", lambda e: connect())
    address.bind("<KP_Enter>", lambda e: connect())
    # The page's main action is the next step: Connect while there is no server (then Sign in, then the app's download).
    if server:
        connect_button = widgets.Button(row, ui, w("online.connect"), connect)
    else:
        connect_button = main_button(app, row, w("online.connect"), connect)
    connect_button.pack(side="left", padx=(ui.px(10), 0))
    if server and forget:
        # At the card's title, apart from Connect: the next server this launcher knows becomes the one PLAY plays on.
        widgets.Button(card.head, ui, w("online.forget"), lambda: forget_server(app, server, rerender),
                       kind="danger").pack(side="right")
    if not server:
        # Not connected yet: typing goes to the address, Enter connects.
        address.after_idle(address.focus_set)
    return address


def signin_panel(app, parent, rerender):
    """The sign-in on the current server: who is signed in and Sign out, or the form: the ID and the password, each
    named over its field, the password shown on demand, Sign in under them; Enter in either field signs in. What is
    wrong is said in place, under the field it is about (an empty one, a wrong password), or under the button."""
    ui, w = app.ui, app.words
    server = app.state.server()
    if server is None:
        return
    # The card's title says the state: signed in, or the sign-in to make.
    card = _card(parent, ui, w("online.account.signed" if app.state.signed_in(server) else "online.account"))
    parent, bg = card.body, theme.PANEL
    if app.state.signed_in(server):
        signed = tk.Frame(parent, bg=bg)
        signed.pack(fill="x")
        widgets.lamp(signed, ui, theme.OK, bg=bg).pack(side="left")

        def sign_out():
            if app.busy_now():
                # The download or the game uses the sign-in now: it stays until they are over.
                app.set_status(i18n.Said("online.busy"), "warn")
                return
            app.user_acted()
            actions.sign_out(app.state)
            app.state.save()
            app.refresh_checks()
            rerender()

        # Sign out right after the account it signs out of.
        widgets.label(signed, ui, w("online.signed", account=server["account"]), bg=bg).pack(
            side="left", padx=(ui.px(6), 0))
        widgets.Button(signed, ui, w("online.signout"), sign_out).pack(side="left", padx=(ui.px(16), 0))
        return
    if app.guide is not None:
        # In the guide, where these go: the server's name and address, in the card's first line (the Online page has the
        # server's own card right above).
        widgets.label(parent, ui, w("online.signin.on", name=st.label(server)), font=ui.fonts.small, fg=theme.MUTED,
                      wrap_margin=0).pack(fill="x", pady=(0, ui.px(FORM_FIELD_GAP)))
    fields, said = {}, {}
    for i, (key, secret) in enumerate((("online.id", False), ("online.password", True))):
        form_label(parent, ui, w(key), top=FORM_FIELD_GAP if i else 0)
        box = widgets.Field(parent, ui, width=ACCOUNT_CHARS, secret=secret,
                            reveal=(w("online.password.show"), w("online.password.hide")) if secret else None)
        box.pack(anchor="w")
        # Under each field, what is wrong with it, in place (empty until there is something to say).
        line = widgets.Said(parent, ui)
        fields[key], said[key] = box, line
    # The ID an installer brought (Play on this PC), else the account signed in before: only the password to type.
    known = server.get("fill") or server.get("account")
    if known:
        fields["online.id"].entry.insert(0, known)

    def say(key, text):
        """What is wrong with one field under it (None: nothing), its edge in the error's colour while it is."""
        line = said[key]
        if text:
            line.set(text, "bad")
            if not line.winfo_manager():
                line.pack(fill="x", pady=(ui.px(6), 0), after=fields[key])
        elif line.winfo_manager():
            line.pack_forget()
        fields[key].set_error(bool(text))

    buttons = tk.Frame(parent, bg=bg)
    buttons.pack(fill="x", pady=(ui.px(FORM_BUTTON_GAP), 0))
    message = widgets.Said(parent, ui)
    message.pack(fill="x", pady=(ui.px(10), 0))
    message.set(w("online.signin.hint"))

    # One sign-in at a time: Enter pressed twice sends one request (the server counts every try).
    asking = {"now": False}

    def sign_in():
        if asking["now"]:
            return
        user, password = fields["online.id"].entry.get(), fields["online.password"].entry.get()
        # An empty field is said under it, nothing asked of the server.
        say("online.id", None if user.strip() else w("error.signin.no_id"))
        say("online.password", None if password else w("error.signin.no_password"))
        if not user.strip() or not password:
            (fields["online.id"] if not user.strip() else fields["online.password"]).entry.focus_set()
            return
        asking["now"] = True
        message.set(w("online.signing"))

        def work():
            try:
                # The sign-in is kept on the window's own thread, before signed_in() saves it there.
                actions.sign_in(app.state, user, password, change=app.post)
                app.post(signed_in)
            except Exception as e:  # noqa: BLE001
                # The server's own words for it go to the log (never the password); the form says it plainly.
                log.info("could not sign in to %s as %s: %s", server["url"], user, e)
                app.post(lambda error=e, text=w.error(e): refused(error, text))

        threading.Thread(target=work, daemon=True, name="sign-in").start()

    def refused(error, text):
        """The server said no: a wrong ID or password under the password, ready to type again; anything else under the
        button."""
        asking["now"] = False
        if not message.winfo_exists():
            return
        password = fields["online.password"].entry
        if getattr(error, "key", None) == "error.signin.wrong":
            say("online.password", text)
            fields["online.id"].set_error(True)
            message.set(w("online.signin.hint"))
        else:
            message.set(text, "bad")
        password.focus_set()
        password.select_range(0, "end")

    def signed_in():
        asking["now"] = False
        # A sign-in is the player's doing: a message kept until then gives way (a sign-in that had ended, say).
        app.user_acted()
        app.state.save()
        app.refresh_checks()
        rerender()

    for box in fields.values():
        box.entry.bind("<Return>", lambda e: sign_in())
        box.entry.bind("<KP_Enter>", lambda e: sign_in())
    # Typing goes to the first empty field; Tab to the next, then Sign in; Enter signs in.
    first = fields["online.password"] if known else fields["online.id"]
    first.entry.after_idle(first.entry.focus_set)
    main_button(app, buttons, w("online.signin"), sign_in).pack(side="left")


def app_panel(app, parent, rerender):
    """The server's app on this PC: what it has, what the server offers, and the download with its progress."""
    ui, w = app.ui, app.words
    server = app.state.server()
    if server is None:
        return
    card = _card(parent, ui, w("online.app"))
    parent, bg = card.body, theme.PANEL
    have = apps.local(server["url"])
    offered = server.get("app")
    newer = bool(have and offered and offered.get("sha256", "").lower() != have["sha256"])
    if have and not newer:
        text, colour = w("online.app.have", date=_date(have)), theme.TEXT
    elif have:
        text, colour = w("online.app.newer", date=_date(offered)), theme.WARN
    else:
        text, colour = w("online.app.none"), theme.WARN
    widgets.label(parent, ui, text, fg=colour, bg=bg, wrap_margin=0).pack(fill="x", pady=(0, ui.px(10)))
    if app.download is None and app.app_note and not newer:
        # The last look for a newer app found none: said here, where its button is.
        widgets.label(parent, ui, w.say(app.app_note), font=ui.fonts.small, fg=theme.MUTED, bg=bg, wrap_margin=0).pack(
            fill="x", pady=(0, ui.px(10)))
    if app.download is None and app.download_error:
        # What the last try said (a stop, a sign-in that ended, a line that broke), in the same colour as the status
        # line says it: the guide has no status line to say it.
        said, tone = app.download_error
        widgets.label(parent, ui, w.say(said), font=ui.fonts.small, fg=theme.WARN if tone == "warn" else theme.BAD,
                      bg=bg, wrap_margin=0).pack(fill="x", pady=(0, ui.px(10)))
    if app.download is not None:
        # The download under way: its bar, kept moving by the app (app._download_moved), and Cancel.
        bar = widgets.Progress(parent, ui, bg=bg)
        bar.pack(anchor="w", pady=(0, ui.px(10)))
        done, total = app.download["done"], app.download["total"]
        # The status line's words (app.download_words): how far it is, the server asked first, or stopping.
        bar.set(done / float(total) if total else None, w.say(app.download_words()))
        app.download_bar = bar
        stopping = app.download.get("stopping")
        stop = widgets.Button(parent, ui, w("online.stopping") if stopping else w("common.cancel"), lambda: halt())
        stop.pack(anchor="w")
        if stopping:
            stop.enable(False)

        def halt():
            # Off at once, saying so: the download stops as soon as the next piece is in.
            app.cancel_download()
            stop.set_text(w("online.stopping"))
            stop.enable(False)
        return
    if not app.state.signed_in(server):
        widgets.label(parent, ui, w("online.app.signin_newer" if have else "online.app.signin"), font=ui.fonts.small,
                      fg=theme.MUTED, bg=bg, wrap_margin=0).pack(fill="x")
        return
    buttons = tk.Frame(parent, bg=bg)
    buttons.pack(anchor="w")
    words = w("online.app.update") if newer else w("online.app.check") if have else w("online.app.get")
    # Getting an app this PC lacks, or the newer one, is the page's main action; looking for a newer one is not.
    if not have or newer:
        get = main_button(app, buttons, words, lambda: _get(app, rerender))
    else:
        get = widgets.Button(buttons, ui, words, lambda: _get(app, rerender))
    get.pack(side="left")


def _date(details):
    """The day an app was built, as its server said ('2026-11-08'); its file name when it said none."""
    built = str((details or {}).get("built_at") or "")
    return built[:10] if built else str((details or {}).get("file") or "")


def _get(app, rerender):
    """Ask the server for its app and download it when this PC lacks it; the page shows the progress."""
    if app.busy_now():
        app.set_status(i18n.Said("online.busy"), "warn")
        return
    app.get_app(done_then=lambda error: rerender())
    rerender()


def known_servers(app, parent, rerender):
    """The other servers this launcher knows: play on one of them instead, or forget one."""
    ui, w = app.ui, app.words
    others = [s for s in app.state.servers if s["url"] != app.state.current]
    if not others:
        return
    card = _card(parent, ui, w("online.others"), last=True)
    for i, s in enumerate(others):
        # One row a server, split by the card's faint lines.
        if i:
            widgets.divider(card.body, ui, pady=CHECK_GAP)
        line = tk.Frame(card.body, bg=theme.PANEL)
        line.pack(fill="x")

        def pick(url=s["url"]):
            if app.busy_now():
                app.set_status(i18n.Said("online.busy"), "warn")
                return
            # Another server to play on: what the line said about the one before (an installer's server, a failure)
            # gives way to where PLAY stands on this one once the ready check below answers.
            app.user_acted()
            app.state.current = url
            # The server in use changed: the address field shows it, whatever was typed there before.
            app.address_draft = None
            # What the last server's download said is not this one's.
            app.download_error, app.app_note = None, None
            app.state.save()
            app.refresh_checks()
            rerender()

        forget_button = widgets.Button(line, ui, w("online.forget"), lambda s=s: forget_server(app, s, rerender),
                                       kind="danger")
        forget_button.pack(side="right")
        pick_button = widgets.Button(line, ui, w("online.pick"), pick)
        pick_button.pack(side="right", padx=(0, ui.px(8)))
        # Its name and address, or its address once when it has no name of its own.
        named = "%s  ·  %s" % (s["name"], s["url"]) if st.has_own_name(s) else s["url"]
        widgets.label(line, ui, named, wrap_margin=12, beside=(forget_button, pick_button)).pack(side="left", fill="x")


def forget_server(app, server, rerender):
    """Forget a server, its sign-in and its app on this PC, after a question that names it."""
    w = app.words
    in_use = server["url"] == app.state.current
    if in_use and app.files_in_use():
        # Its app is downloading or playing, from this window or the command line.
        app.set_status(i18n.Said("online.busy"), "warn")
        return
    # The question short, the server it is about named in the line under it.
    if not dialogs.ask(app, "danger", w("online.forget.title"), w("online.forget.ask"),
                       w("online.forget.detail", name=server["name"]), w("online.forget")):
        return
    # The player's doing: a line kept about the server that goes gives way.
    app.user_acted()
    actions.forget(app.state, server["url"])
    if in_use:
        # What the last download and the last look said was about the server that is gone; the address field shows
        # the server in use now.
        app.download_error, app.app_note, app.address_draft = None, None, None
    app.state.save()
    app.refresh_checks()
    rerender()


def online_keys(app):
    """What each card of the Online page (and the guide's steps that show them) shows, as keys for Sections: the server
    in use, its sign-in, its app and the download, and the other servers."""
    state = app.state
    server = state.server()
    url = server["url"] if server else None

    def server_key():
        return (url and state.server()["url"], server and state.server()["name"]) if state.server() else None

    def signin_key():
        current = state.server()
        return (current["url"], state.signed_in(current), current.get("account"), current.get("fill")) if current else None

    def app_key():
        current = state.server()
        if current is None:
            return None
        have = apps.local(current["url"])
        download = app.download
        return (current["url"], have and have.get("sha256"), (current.get("app") or {}).get("sha256"),
                state.signed_in(current), download is not None and bool(download.get("stopping")),
                download is None, str(app.download_error), str(app.app_note))

    def others_key():
        return tuple((s["url"], s["name"]) for s in state.servers if s["url"] != state.current)

    return server_key, signin_key, app_key, others_key


def build_online(app, parent):
    """The Online page in cards (Sections): the server, the sign-in, the server's app, the other servers; an answer
    changes its own card in place."""
    sections = Sections(parent, app.ui)
    # A change of the launcher's state redraws the cards it changed, while the page is on show.
    again = lambda: app.page == "online" and app.guide is None and sections.refresh()  # noqa: E731
    server_key, signin_key, app_key, others_key = online_keys(app)
    # The server's card is keyed by the server in use only: its line under the address follows each answer in place.
    sections.add(lambda: (app.state.current,), lambda holder: connect_panel(app, holder, again, forget=True))
    sections.add(signin_key, lambda holder: signin_panel(app, holder, again))
    sections.add(app_key, lambda holder: app_panel(app, holder, again))
    sections.add(others_key, lambda holder: known_servers(app, holder, again))
    app.page_follow = sections.refresh


# ---------------------------------------------------------------------------------------------- Help


def _player_log(app):
    """The player's log for the current server's app, and whether it is there (once the game has run with the app)."""
    server = app.state.server()
    have = apps.local(server["url"]) if server else None
    log_file = player.app_log(have)
    return log_file, bool(log_file and os.path.isfile(log_file))


def build_help(app, parent):
    ui, w = app.ui, app.words
    from opendmtq_client import installed
    sections = Sections(parent, ui, after=lambda: widgets.fit_names(parent, ui, rows_that_come("help")))
    # The ready check, its rows made again in place when they change (refresh_checks).
    sections.add(lambda: None, lambda holder: _help_checks(app, holder))
    # The lines and the tools that follow the player's log (there once the game has run) and the install.
    sections.add(lambda: _player_log(app)[1], lambda holder: _help_trouble(app, holder))
    sections.add(lambda: (_player_log(app), installed.root()), lambda holder: _help_tools(app, holder))
    sections.add(lambda: (installed.root(), bool(installed.root() and installed.updater(installed.root()))),
                 lambda holder: _help_remove(app, holder))
    app.page_follow = sections.refresh


def _help_checks(app, parent):
    ui, w = app.ui, app.words
    card = _card(parent, ui, w("help.checks"))
    # Check again at the title's right end: the server asked again too, whatever its last answer.
    widgets.Button(card.head, ui, w("help.recheck"), lambda: app.refresh_checks(force=True)).pack(side="right")
    app.check_box = tk.Frame(card.body, bg=theme.PANEL)
    app.check_box.pack(fill="x")
    app.refresh_checks()
    refresh_checks(app)


def _help_trouble(app, parent):
    ui, w = app.ui, app.words
    card = _card(parent, ui, w("help.trouble"))
    # Each line with the page it names one press away. The first line points at the player's log below, which is
    # there once the game has run with the app.
    _log_file, has_log = _player_log(app)
    first = "help.trouble.1" if has_log else "help.trouble.1.none"
    for i, (key, page) in enumerate(((first, None), ("help.trouble.2", "screen"), ("help.trouble.3", "sound"),
                                     ("help.trouble.4", None))):
        if i:
            widgets.divider(card.body, ui, pady=CHECK_GAP)
        line = tk.Frame(card.body, bg=theme.PANEL)
        line.pack(fill="x")
        beside = ()
        if page:
            # The page the line names, by the menu's own name, reached by the mouse or the keyboard.
            to = widgets.link(line, ui, TITLES[page], lambda p=page: app.nav_go(p))
            to.pack(side="right", anchor="n")
            beside = (to,)
        widgets.label(line, ui, w(key), wrap_margin=12, beside=beside).pack(side="left", fill="x")


def _help_tools(app, parent):
    ui, w = app.ui, app.words
    card = _card(parent, ui, w("help.tools"))
    log_file, has_log = _player_log(app)
    if has_log:
        widgets.setting_row(card.body, ui, w("help.player_log"),
                            lambda p: widgets.Button(p, ui, w("common.open"), lambda: actions.show_file(log_file)),
                            w("help.player_log.hint")).pack(fill="x")
        widgets.divider(card.body, ui)
    # The launcher's log's folder: its older logs are there beside it.
    logs = os.path.dirname(st.launcher_log())
    widgets.setting_row(card.body, ui, w("help.logs"),
                        lambda p: widgets.Button(p, ui, w("common.open"), lambda: actions.open_folder(logs)),
                        w("help.logs.hint")).pack(fill="x")
    from opendmtq_client import installed
    root = installed.root()
    if root:
        # Only the installed launcher has a package to put its files back from.
        widgets.divider(card.body, ui)
        widgets.setting_row(card.body, ui, w("help.repair.row"),
                            lambda p: widgets.Button(p, ui, w("help.repair"), lambda: maintenance.repair_program(app)),
                            w("help.repair.hint")).pack(fill="x")


def _help_remove(app, parent):
    ui, w = app.ui, app.words
    from opendmtq_client import installed
    root = installed.root()
    # From the least to the most: the game's data, the launcher's, the program.
    card = _card(parent, ui, w("help.remove"), last=True)
    widgets.setting_row(card.body, ui, w("help.clear.row"),
                        lambda p: widgets.Button(p, ui, w("help.clear.confirm"), lambda: maintenance.clear_game_data(app),
                                                 kind="danger"),
                        w("help.clear.hint")).pack(fill="x")
    widgets.divider(card.body, ui)

    widgets.setting_row(card.body, ui, w("help.reset.row"),
                        lambda p: widgets.Button(p, ui, w("help.reset"), lambda: maintenance.start_over(app), kind="danger"),
                        w("help.reset.hint")).pack(fill="x")
    if root and installed.updater(root):
        # Velopack's uninstaller is what takes the program; a copied folder is deleted as any folder.
        widgets.divider(card.body, ui)
        widgets.setting_row(card.body, ui, w("help.uninstall.row"),
                            lambda p: widgets.Button(p, ui, w("help.uninstall"), lambda: maintenance.uninstall_program(app),
                                                     kind="danger"),
                            w("help.uninstall.hint")).pack(fill="x")


# --------------------------------------------------------------------------------------------- About


def language_options(app):
    """The language choices: Windows' own (no choice kept), English, Korean."""
    return [("system", app.words("about.language.system")), ("en", "English"), ("ko", "한국어")]


def build_about(app, parent):
    ui, w = app.ui, app.words
    card = _card(parent, ui, w("about.general"))
    widgets.setting_row(card.body, ui, w("about.language"),
                        lambda p: widgets.Segmented(p, ui, language_options(app), app.state.picked_language or "system",
                                                    app.set_language)).pack(fill="x")
    # The updates' card, made again in place when the look at the start finds a newer launcher; the cards after it as
    # they were.
    sections = Sections(parent, ui)
    sections.add(lambda: app.update_found and app.update_found.version, lambda holder: _updates_card(app, holder))
    app.page_follow = sections.refresh
    # Its gap under it, as a card's own (the holder's card has none).
    tk.Frame(parent, bg=theme.BG, height=ui.px(CARD_GAP)).pack(fill="x")
    card = _card(parent, ui, w("about.guide"))

    def rerun():
        app.state.guide_done = False
        app.state.save()
        app.show()

    widgets.Button(card.body, ui, w("about.guide.run"), rerun).pack(anchor="w")
    card = _card(parent, ui, w("about.legal"), last=True)
    for i, key in enumerate(("about.license", "about.notice")):
        if i:
            widgets.divider(card.body, ui, pady=CHECK_GAP)
        widgets.label(card.body, ui, w(key), fg=theme.MUTED, wrap_margin=0).pack(fill="x")


def _updates_card(app, parent):
    """The About page's updates: the version, Check for updates, and the answer with Update to vX when one is on
    offer."""
    ui, w = app.ui, app.words
    card = _card(parent, ui, w("about.updates"))
    # The version the header shows beside the logo too: the installed one, else the code's.
    version = updates.shown_version()
    box = tk.Frame(card.body, bg=theme.PANEL)
    box.pack(fill="x")
    widgets.label(box, ui, w("about.version", v=version), font=ui.fonts.body_bold).pack(side="left")
    # The answer and "Update to vX" under the version, taking room only once there is an answer.
    result = tk.Frame(card.body, bg=theme.PANEL)
    answer = widgets.label(result, ui, "", fg=theme.MUTED, wrap_margin=0)
    slot = tk.Frame(result, bg=theme.PANEL)

    # One look at a time: a second press while it asks does nothing.
    checking = {"now": False}

    def check():
        if checking["now"]:
            return
        checking["now"] = True
        for child in slot.winfo_children():
            child.destroy()
        answer.configure(text=w("about.checking"), fg=theme.MUTED)
        if not answer.winfo_manager():
            answer.pack(fill="x", pady=(ui.px(10), 0))
            slot.pack(fill="x")

        def work():
            # The window's own settings: the server PLAY plays on is asked first.
            result = updates.check(app.state)
            app.post(lambda: show(result))

        threading.Thread(target=work, daemon=True, name="updates").start()

    def show(result):
        checking["now"] = False
        if not answer.winfo_exists():
            return
        # The server PLAY plays on is named when the answer is its own: what it hands out, or its version as the newest.
        server = result.source is not None and result.source.kind == "server"
        source = result.source.label() if result.source is not None else ""
        text = {
            "not_installed": w("about.not_installed"),
            "no_source": w("about.no_source"),
            "uptodate": w("about.uptodate.from", source=source) if server else w("about.uptodate"),
            # What failed and, by its kind, why: the words for the log are in the launcher's log (updates.check).
            "failed": w.failed("about.update_failed", result.error),
            "refused": w("about.refused", source=source),
            "available": w("about.available.from", v=result.version, source=source) if server
            else w("about.available", v=result.version),
        }[result.kind]
        answer.configure(text=text, fg=theme.BAD if result.kind in ("failed", "refused") else theme.MUTED)
        if result.kind == "available":
            main_button(app, slot, w("about.update_now", v=result.version), lambda: update(result)).pack(
                anchor="w", pady=(ui.px(10), 0))
            if app.update_found is None or app.update_found.version != result.version:
                # Found by this press: the status line says it too, as it says the one the start found.
                app.update_on_offer(result)

    def update(result):
        if not maintenance.update_launcher(app, result):
            # A game from this window or from the command line: the update replaces the player's files under it.
            answer.configure(text=w("about.update_busy"), fg=theme.WARN)

    widgets.Button(box, ui, w("about.check"), check).pack(side="left", padx=(ui.px(16), 0))
    result.pack(fill="x")
    if app.update_found is not None:
        # The look at the start found a newer launcher: its answer and its update are here without a press.
        answer.pack(fill="x", pady=(ui.px(10), 0))
        slot.pack(fill="x")
        show(app.update_found)


BUILDERS = {
    "play": build_play, "screen": build_screen, "sound": build_sound, "controls": build_controls,
    "online": build_online, "help": build_help, "about": build_about,
}
