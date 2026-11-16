"""The installer's window (OpenDMTQ-Setup.exe, and the uninstall Windows' Settings, Apps starts), drawn as the launcher
is: a column down its left with the wordmark, the version and the steps of what it does, the page beside it with its
title in the site's leaning face over the site's field, the page's card, and a strip along the foot with the buttons,
the main one lime (or red to remove for good) and the others quiet.

installer.py decides what each page says and does; this module only draws: SetupWindow.page() starts a page,
Options a list of choices on it, Progress the work under way, and lines() what came of it. Nothing here asks the
system anything.
"""

import tkinter as tk

from PIL import ImageTk

from opendmtq_client import art, safety, theme, widgets

# The window's size when the screen has room for it, the column's width and the strip's height along the foot, and the
# room inside the column and the strip (logical pixels).
WIDTH, HEIGHT = 800, 540
COLUMN, FOOT, EDGE = 220, 72, 20
# How far down the page its lit top reaches before it has faded (logical pixels), as on the launcher's pages.
PAGE_LIGHT = 300
# The room between two lines of a card (what came of the work, a card's facts), on the launcher's spacing scale.
LINE_GAP = 12


class SetupWindow:
    """The installer's window: `words` (i18n.Words) in `language`, the version it shows beside the wordmark, and what
    closing it does (`on_close`, which may refuse while work is under way)."""

    def __init__(self, words, language, version, title, on_close):
        # A window of its own: never on a real screen from a test.
        safety.refuse_windows_in_tests("the installer's window")
        from opendmtq_client import dialogs
        theme.register_fonts()
        self.words = words
        self.root = tk.Tk()
        self.root.title(title)
        self.root.configure(bg=theme.BG)
        # The mark in the title bar and on the taskbar, as the launcher's.
        dialogs.set_icon(self.root)
        self.scale = theme.scale_of(self.root)
        self.ui = widgets.Ui(self.root, theme.Fonts(self.root, language), self.scale, words)
        # The page's scroll bar in the launcher's dark style.
        widgets.style_ttk(self.ui)
        px = self.ui.px
        from opendmtq_client.window_room import title_bar_height, window_box, work_area
        # Inside the room windows have (the screen less the taskbar), as the launcher's window opens: a third of the way
        # down, never under the taskbar.
        w, h, x, y = window_box(work_area(self.root), title_bar_height(), px(WIDTH), px(HEIGHT))
        self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))
        # One size: an installer's window is not made larger or smaller.
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", on_close)
        # Esc answers the page as its quiet button does (Cancel, Close, Back), while it has one.
        self.root.bind("<Escape>", lambda e: self._escape())
        self._build(version)

    # --------------------------------------------------------------------------------------------- the frame

    def _build(self, version):
        ui, px = self.ui, self.ui.px
        # ---- the column: the wordmark with SETUP and the version beside it, then the steps.
        column = tk.Frame(self.root, bg=theme.STRIP, width=px(COLUMN))
        column.pack(side="left", fill="y")
        # Its own width whatever it holds.
        column.pack_propagate(False)
        # The seam along its right edge, where the page begins.
        tk.Frame(column, bg="#2a3038", width=max(1, px(1))).pack(side="right", fill="y")
        brand = art.brand(self.scale, "v" + version, mark=24, label="SETUP")
        self._brand = ImageTk.PhotoImage(brand, master=column)
        mark = tk.Label(column, image=self._brand, bg=theme.STRIP, bd=0)
        # A dialog would draw the window from its widgets: the mark's own picture.
        mark.odq_picture = brand
        mark.pack(side="top", anchor="w", padx=(px(EDGE), 0), pady=(px(EDGE + 2), px(26)))
        self.steps = Steps(column, ui)
        self.steps.pack(side="top", fill="x")
        # ---- the right side: the strip with the buttons along its foot, the page over it.
        right = tk.Frame(self.root, bg=theme.BG)
        right.pack(side="left", fill="both", expand=True)
        strip = tk.Frame(right, bg=theme.STRIP, height=px(FOOT))
        strip.pack(side="bottom", fill="x")
        # One height whatever it holds.
        strip.pack_propagate(False)
        # Its seam along the top, as the column's along its side.
        tk.Frame(strip, bg="#2a3038", height=max(1, px(1))).pack(side="top", fill="x")
        self.strip = tk.Frame(strip, bg=theme.STRIP)
        self.strip.pack(fill="both", expand=True, padx=px(EDGE + 4))
        # The line at the strip's left end (what the work under way is doing, where the log is), and the buttons.
        self.note = tk.Label(self.strip, text="", font=ui.fonts.small, fg=theme.MUTED, bg=theme.STRIP, anchor="w",
                             justify="left")
        # Its room ends the strip's gap before the buttons, however long its words.
        self.note.pack(side="left", fill="x", expand=True, padx=(0, px(16)))
        self.button_row = tk.Frame(self.strip, bg=theme.STRIP)
        self.button_row.pack(side="right")
        self.page_area = widgets.ScrollArea(right, ui, offset=0, light=px(PAGE_LIGHT))
        self.page_area.pack(side="top", fill="both", expand=True)
        # Tab goes as the window reads: the page, then the strip's buttons (Tk follows the order of making; the strip
        # was made first so that it holds the foot, so it is raised after the page).
        tk.Misc.tkraise(strip)
        self.buttons = []
        self.escape = None

    def _escape(self):
        """Esc: the page's quiet answer (Cancel, Close, Back), when it has one and nothing is under way."""
        if self.escape is not None:
            self.escape()

    # ----------------------------------------------------------------------------------------------- a page

    def page(self, title, lead, steps, step):
        """A new page: its title and the line under it over the field, the column's steps with `step` lit. Returns the
        frame the page's cards go in; the strip's buttons and note are cleared for it (set_buttons, say)."""
        for child in self.page_area.inner.winfo_children():
            child.destroy()
        self.page_area.set_heading(title, lead)
        self.steps.show(steps, step)
        content = tk.Frame(self.page_area.inner, bg=theme.BG)
        content.pack(fill="both", expand=True)
        self.page_area.to_top()
        self.say("")
        self.set_buttons([])
        return content

    def card(self, parent, title=None, last=True):
        """A card on the page, as the launcher's: its title, the cut corner, the site's room inside."""
        card = widgets.Card(parent, self.ui, title)
        card.pack(fill="x", pady=(0, 0 if last else self.ui.px(16)))
        return card

    def set_buttons(self, buttons, default=None, escape=None):
        """The strip's buttons from the left: [(words, command, kind)], kind "primary" (lime), "danger" (red) or
        "secondary" (quiet); the one at `default` takes the keyboard (Enter presses it); `escape` is what Esc does."""
        for button in self.buttons:
            button.destroy()
        self.buttons = []
        px = self.ui.px
        for i, (words, command, kind) in enumerate(buttons):
            button = widgets.Button(self.button_row, self.ui, words, command, kind=kind)
            button.pack(side="left", padx=(px(10) if i else 0, 0))
            self.buttons.append(button)
        self.escape = escape
        if default is not None and 0 <= default < len(self.buttons):
            # After the window is drawn, so that the keyboard lands there and not on the page before it.
            target = self.buttons[default]
            self.root.after_idle(lambda: target.winfo_exists() and target.focus_set())
        return self.buttons

    def say(self, text, colour=theme.MUTED):
        """The line at the strip's left end."""
        # Wrapped to what the buttons leave of the strip, so that a long path breaks instead of pushing them off.
        room = max(self.ui.px(120), self.strip.winfo_width() - self.button_row.winfo_reqwidth() - self.ui.px(16))
        self.note.configure(text=text, fg=colour, wraplength=room)

    def lines(self, parent, rows):
        """What came of the work, a line each, as the launcher's ready check says a state: [(state, words)], state "ok"
        (a lime dot), "change" (a yellow ring), "bad" (a red dot), or None for a plain line in ash (where a log is)."""
        for i, (state, words) in enumerate(rows):
            # One line under another with the card's gap between rows (LINE_GAP), on the launcher's spacing scale.
            gap = (self.ui.px(LINE_GAP) if i else 0, 0)
            if state is None:
                widgets.label(parent, self.ui, words, font=self.ui.fonts.small, fg=theme.MUTED,
                              wrap_margin=0).pack(fill="x", pady=gap)
            else:
                widgets.check_line(parent, self.ui, state, words).pack(fill="x", pady=gap)

    def run(self):
        self.root.mainloop()


class Steps(tk.Canvas):
    """The column's steps of what the installer does (READY, INSTALL, DONE), one under another, as the launcher's guide
    sets its steps: each number large and leaning with its name beside it; the step on show on a raised slab with a
    lime rule, its number lime and its name white; the steps taken with their numbers lime; the ones to come grey."""

    # A step's height and the gap between two, the room before its number, the number's column, the slab's cut corner
    # and its rule (logical pixels).
    STEP_H, GAP, PAD, NUMBER_W, CUT, RULE = 46, 4, 14, 32, 10, 3

    def __init__(self, parent, ui):
        super().__init__(parent, height=1, bg=theme.STRIP, highlightthickness=0, bd=0, takefocus=0)
        self.ui = ui
        self.names, self.index = [], 0
        self.bind("<Configure>", lambda e: self._draw())

    def show(self, names, index):
        """These steps, the one at `index` on show."""
        px = self.ui.px
        self.names, self.index = list(names), index
        height = len(self.names) * px(self.STEP_H) + max(0, len(self.names) - 1) * px(self.GAP)
        self.configure(height=max(1, height))
        self._draw()

    def _draw(self):
        from PIL import Image, ImageDraw
        px = self.ui.px
        width, height = max(1, self.winfo_width()), max(1, int(self.cget("height")))
        self.delete("all")
        picture = Image.new("RGB", (width, height), art._rgb(theme.STRIP))
        draw = ImageDraw.Draw(picture)
        left, right = px(EDGE) - px(6), width - px(EDGE) + px(6) - max(1, px(1))
        texts = []
        for i, name in enumerate(self.names):
            top = i * (px(self.STEP_H) + px(self.GAP))
            bottom = top + px(self.STEP_H)
            done, now = i < self.index, i == self.index
            if now:
                # The slab under the step on show, its top-right corner cut as the cards' are, its lime rule.
                cut = px(self.CUT)
                draw.polygon([(left, top), (right - cut, top), (right - 1, top + cut), (right - 1, bottom - 1),
                              (left, bottom - 1)], fill=art._rgb(theme.PANEL))
                draw.rectangle([left, top, left + px(self.RULE) - 1, bottom - 1], fill=art._rgb(theme.OK))
            colour = theme.OK if (done or now) else theme.STEP_TO_COME
            numeral = art.numeral(str(i + 1), colour, self.ui.scale, size=24, bg=None)
            nx, ny = left + px(self.PAD), (top + bottom - numeral.height) // 2
            picture.paste(numeral, (nx, ny), numeral)
            texts.append((nx + px(self.NUMBER_W), (top + bottom) // 2, name,
                          theme.TEXT if now else (theme.MUTED if done else theme.FAINT)))
        self._picture = picture
        self._image = ImageTk.PhotoImage(picture, master=self)
        # A dialog would draw the window from its widgets: the column's steps as they look now.
        self.odq_picture = picture
        self.create_image(0, 0, image=self._image, anchor="nw")
        for x, y, name, colour in texts:
            # The names in the launcher's wide face, English in both languages as its menu's.
            self.create_text(x, y, text=name, anchor="w", font=self.ui.fonts.step, fill=colour)


class Options(tk.Frame):
    """A list of choices of which one is chosen, on a card: each a row with its name and a line under it, a ring before
    it, the chosen one on a raised slab with a lime rule and its ring lit. A click chooses a row; the keyboard reaches
    the list with Tab (a cyan ring round it), the arrow keys move the choice, Enter does what the page's main button
    does (`on_enter`). `options` are [(value, name, line)]; on_change(value) runs on each new choice."""

    RULE, PAD = 3, 14

    def __init__(self, parent, ui, options, value, on_change, on_enter):
        bg = parent.cget("bg")
        super().__init__(parent, bg=bg)
        self.ui, self.on_change, self.on_enter = ui, on_change, on_enter
        self.values = [option[0] for option in options]
        self.value = value if value in self.values else self.values[0]
        px = ui.px
        # Its own lamps: a lime dot for the choice, a grey ring for the others.
        self._lamps = {on: ImageTk.PhotoImage(art.lamp(theme.OK if on else theme.FAINT, ui.scale, bg=theme.PANEL_HI if on
                                                       else theme.PANEL, hollow=not on), master=self)
                       for on in (True, False)}
        self.rows = {}
        for i, (key, name, line) in enumerate(options):
            row = tk.Frame(self, bg=theme.PANEL, cursor="hand2")
            row.pack(fill="x", pady=(px(6) if i else 0, 0))
            rule = tk.Frame(row, bg=theme.PANEL, width=px(self.RULE))
            rule.pack(side="left", fill="y")
            lamp = tk.Label(row, image=self._lamps[False], bg=theme.PANEL, bd=0)
            lamp.pack(side="left", anchor="n", padx=(px(self.PAD), px(10)), pady=(px(13), 0))
            words = tk.Frame(row, bg=theme.PANEL)
            words.pack(side="left", fill="x", expand=True, pady=px(10), padx=(0, px(self.PAD)))
            title = tk.Label(words, text=name, font=ui.fonts.body_bold, fg=theme.TEXT, bg=theme.PANEL, anchor="w")
            title.pack(fill="x")
            said = widgets.label(words, ui, line, font=ui.fonts.small, fg=theme.MUTED, bg=theme.PANEL, wrap_margin=0)
            said.pack(fill="x", pady=(px(2), 0))
            self.rows[key] = {"row": row, "rule": rule, "lamp": lamp, "words": words, "title": title, "line": said}
            for widget in (row, lamp, words, title, said):
                widget.bind("<Button-1>", lambda e, k=key: self.choose(k))
        # Tab reaches the list; the arrow keys move the choice; Enter does the page's main thing.
        widgets.focus_ring(self, ui, bg)
        self.bind("<Up>", lambda e: self._step(-1))
        self.bind("<Down>", lambda e: self._step(1))
        self.bind("<Return>", lambda e: self.on_enter())
        self.bind("<KP_Enter>", lambda e: self.on_enter())
        self._paint()

    def _paint(self):
        """Each row's look: the chosen one raised with its rule, the others flat."""
        for key, parts in self.rows.items():
            on = key == self.value
            fill = theme.PANEL_HI if on else theme.PANEL
            for name in ("row", "words", "title", "line"):
                parts[name].configure(bg=fill)
            parts["lamp"].configure(bg=fill, image=self._lamps[on])
            parts["rule"].configure(bg=theme.OK if on else fill)

    def choose(self, value):
        """Choose a row (a click, an arrow key), and say so."""
        if value in self.values and value != self.value:
            self.value = value
            self._paint()
            self.on_change(value)
        # A click puts the keyboard on the list too, so that the arrow keys go on from there.
        self.focus_set()

    def _step(self, by):
        """The choice before or after this one (no wrap at either end)."""
        i = self.values.index(self.value) + by
        if 0 <= i < len(self.values):
            self.choose(self.values[i])
        return "break"

    def set_line(self, value, text):
        """Another line under a row (a size counted after the page showed)."""
        if value in self.rows:
            self.rows[value]["line"].configure(text=text)


class Progress(tk.Frame):
    """The work under way: a bar that fills as the work does, its share in figures at its right, and the work's steps
    under it, each with a lamp: done a lime dot, under way a lime ring, to come a grey ring. set(fraction, step) moves
    it; the bar eases toward the fraction it is given, a little at a time, so that it moves as the work does and never
    jumps back."""

    def __init__(self, parent, ui, steps):
        bg = parent.cget("bg")
        super().__init__(parent, bg=bg)
        self.ui, self.bg = ui, bg
        px = ui.px
        self.shown, self.target, self.step = 0.0, 0.0, 0
        top = tk.Frame(self, bg=bg)
        top.pack(fill="x")
        self.figure = tk.Label(top, text="0%", font=ui.fonts.body_bold, fg=theme.TEXT, bg=bg, width=5, anchor="e")
        self.figure.pack(side="right")
        self.bar = tk.Label(top, bg=bg, bd=0)
        self.bar.pack(side="left", fill="x", expand=True, padx=(0, px(12)))
        self.bar.bind("<Configure>", lambda e: self._draw_bar())
        # The steps under the bar, the card's gap between them (on the launcher's spacing scale).
        tk.Frame(self, bg=bg, height=px(16)).pack(fill="x")
        self._lamps = {state: ImageTk.PhotoImage(art.lamp(colour, ui.scale, bg=bg, hollow=hollow), master=self)
                       for state, colour, hollow in (("done", theme.OK, False), ("now", theme.OK, True),
                                                     ("later", theme.FAINT, True))}
        self.rows = []
        for i, name in enumerate(steps):
            row = tk.Frame(self, bg=bg)
            row.pack(fill="x", pady=(px(8) if i else 0, 0))
            lamp = tk.Label(row, image=self._lamps["later"], bg=bg, bd=0)
            lamp.pack(side="left")
            words = tk.Label(row, text=name, font=ui.fonts.body, fg=theme.FAINT, bg=bg, anchor="w")
            words.pack(side="left", padx=(px(8), 0))
            self.rows.append((lamp, words))
        self._paint_steps()
        self._job = self.after(30, self._tick)
        # Its easing stops with it: a timer left behind would call a bar that is gone.
        self.bind("<Destroy>", lambda e: e.widget is self and self._job is not None and self.after_cancel(self._job))

    def set(self, fraction, step):
        """Where the work is: its share done (0 to 1) and the step under way (an index of the steps)."""
        # Never back: a step that measures afresh (a folder emptied before it fills) does not move the bar back.
        self.target = max(self.target, min(1.0, max(0.0, fraction)))
        if step != self.step:
            self.step = step
            self._paint_steps()

    def _tick(self):
        """One frame of the bar's easing toward its target (30 ms)."""
        self._job = None
        if not self.winfo_exists():
            return
        gap = self.target - self.shown
        if gap > 0.0005:
            # A share of what is left each frame, at least a little: quick at first, gentle at the end.
            self.shown = min(self.target, self.shown + max(0.004, gap * 0.18))
            self._draw_bar()
        self._job = self.after(30, self._tick)

    def _draw_bar(self):
        width = self.bar.winfo_width()
        if width <= 1:
            return
        px = self.ui.px
        picture = art.bar(width, px(8), self.shown, theme.OK)
        self._image = ImageTk.PhotoImage(picture, master=self)
        self.bar.configure(image=self._image, height=px(8))
        # A dialog would draw the window from its widgets: the bar as it looks now.
        self.bar.odq_picture = picture
        self.figure.configure(text="%d%%" % int(round(self.shown * 100)))

    def _paint_steps(self):
        for i, (lamp, words) in enumerate(self.rows):
            state = "done" if i < self.step else ("now" if i == self.step else "later")
            lamp.configure(image=self._lamps[state])
            words.configure(fg=theme.TEXT if state == "now" else (theme.MUTED if state == "done" else theme.FAINT))

    def finish(self):
        """All done: every step lit and the bar full."""
        self.target, self.step = 1.0, len(self.rows)
        self._paint_steps()
