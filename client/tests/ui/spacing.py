"""The launcher's boxes and the room round them, measured on the screen as a person sees them: two boxes or borders that
touch or overlap without meaning to (cards, fields, buttons, switches, the opened drop-down, the menu column and its
foot), text closer to the edge of the box it sits in than the padding the theme sets for that box, text over a box it is
no part of, and gaps between siblings that break the launcher's own spacing scale (SCALE).

shots.py runs it on every screen and state it shows (measure()), at every size and in both languages, and on the open
dialog of a screen; it reads the widgets' places from Tk, never from the code that put them there.

  problems = spacing.check(app.root, ui, name)       (a list of words, empty when all is well)
"""

import tkinter as tk

from opendmtq_client import widgets

# The launcher's spacing scale, in logical pixels: what one box may keep from the next beside or under it in a stack
# (a page's cards, a card's rows, a form's names and fields, a column's foot). 0 is two boxes that meet on purpose (a
# row's name over its own control's line, a line under a row).
SCALE = (0, 2, 4, 6, 8, 10, 12, 16, 20, 24, 28, 32, 40, 48)
# The least room between two boxes side by side or one under the other that are no part of each other (logical pixels):
# closer, they read as one box touching another.
LEAST_GAP = 4
# The least room between words and a box beside them on their line that they are no part of (logical pixels).
LEAST_TEXT_GAP = 4
# A card's padding: its words and boxes this far inside its edges, at the sides and at its top and foot (widgets.Card's
# 24 and 24 - 4 logical pixels).
CARD_SIDES, CARD_ENDS = 24, 20
# The menu column's padding: its room either side (widgets.Rail.EDGE), and above and under what it holds (its foot
# stands 20 above the window's foot, the wordmark 22 under its top).
RAIL_SIDES, RAIL_ENDS = 18, 18
# Any other band of its own colour: words at least this far from its edges (logical pixels).
BAND_SIDES, BAND_ENDS = 8, 4
# A pixel either way: Tk rounds a scaled size to whole pixels.
SLACK = 1


def _kind(widget):
    """What a widget is to the eye: "card", "field", "button", "control", "rail", "foot", "menu", "text", or None (a frame
    that only holds others, a picture of no box of its own)."""
    rail = getattr(widgets, "Rail", None)
    rail_list = getattr(widgets, "RailList", None)
    if isinstance(widget, widgets.Card):
        return "card"
    if rail is not None and isinstance(widget, rail):
        return "rail"
    if rail_list is not None and isinstance(widget, rail_list):
        return "menu"
    if getattr(widget, "odq_foot", False):
        return "foot"
    if isinstance(widget, (widgets.Field, widgets.KeyBox)) or widget.winfo_class() == "TCombobox":
        return "field"
    if isinstance(widget, (widgets.Button, widgets.PlaySlab)) or getattr(widget, "odq_button", False):
        # The launcher's buttons, and any other that says it is one (the installer's own minimise and close).
        return "button"
    if isinstance(widget, (widgets.Toggle, widgets.Segmented)):
        return "control"
    if isinstance(widget, tk.Canvas) and isinstance(widget.master, widgets.Slider):
        return "control"
    if isinstance(widget, tk.Label) and str(widget.cget("text")).strip() and not str(widget.cget("image")):
        return "text"
    return None


def _inset(widget):
    """How far inside a widget's box what shows of it begins: a switch's or a row of tabs' keyboard ring and halo, a
    link's ring (its words start inside it)."""
    inset = getattr(widget, "odq_inset", None)
    if inset is not None:
        return int(inset)
    try:
        # Tk answers a screen distance as its own object: in pixels through winfo_pixels.
        return widget.winfo_pixels(str(widget.cget("highlightthickness")))
    except (tk.TclError, ValueError, TypeError):
        return 0


def _shown_box(widget, origin):
    """The part of the widget's box that shows, in the window's pixels (left, top, right, bottom), or None: cut by every
    widget round it that is smaller (the page area scrolled), and inset by its own ring."""
    x, y = widget.winfo_rootx() - origin[0], widget.winfo_rooty() - origin[1]
    inset = _inset(widget)
    box = [x + inset, y + inset, x + widget.winfo_width() - inset, y + widget.winfo_height() - inset]
    parent = widget.master
    while parent is not None:
        try:
            px, py = parent.winfo_rootx() - origin[0], parent.winfo_rooty() - origin[1]
            pw, ph = parent.winfo_width(), parent.winfo_height()
        except tk.TclError:
            break
        box = [max(box[0], px), max(box[1], py), min(box[2], px + pw), min(box[3], py + ph)]
        parent = parent.master
    if box[0] >= box[2] or box[1] >= box[3]:
        return None
    return tuple(box)


def _raw(widget, origin):
    """The widget's box as Tk places it, its ring and all, in the window's pixels."""
    x, y = widget.winfo_rootx() - origin[0], widget.winfo_rooty() - origin[1]
    return (x, y, x + widget.winfo_width(), y + widget.winfo_height())


def _text_box(label, origin):
    """Where a label's words are: its box as wide as the words ask (a label packed to fill its line is wider than its
    words), from its left, its right or its middle as it is anchored."""
    box = _shown_box(label, origin)
    if box is None:
        return None
    inset = _inset(label)
    words = label.winfo_reqwidth() - 2 * inset
    room = box[2] - box[0]
    if words >= room:
        return box
    anchor = str(label.cget("anchor"))
    if "w" in anchor:
        return (box[0], box[1], box[0] + words, box[3])
    if "e" in anchor:
        return (box[2] - words, box[1], box[2], box[3])
    middle = (box[0] + box[2]) // 2
    return (middle - words // 2, box[1], middle + words - words // 2, box[3])


def _whole(widget, origin):
    """The widget's whole box (not cut), inset by its ring, in the window's pixels."""
    x, y = widget.winfo_rootx() - origin[0], widget.winfo_rooty() - origin[1]
    inset = _inset(widget)
    return (x + inset, y + inset, x + widget.winfo_width() - inset, y + widget.winfo_height() - inset)


def _all(root):
    """Every widget under `root`, without recursion."""
    found, stack = [], [root]
    while stack:
        widget = stack.pop()
        for child in widget.winfo_children():
            found.append(child)
            stack.append(child)
    return found


def _surface(widget, page_fields):
    """The visible box `widget`'s words sit on, and what it is: ("card"), the menu column ("rail", its foot measured with
    it), the page's field outside any card ("page"), or a band whose colour differs from what is round it ("band");
    (None, None) for words on the window itself."""
    rail = getattr(widgets, "Rail", None)
    parent = widget.master
    while parent is not None:
        if isinstance(parent, widgets.Card):
            return parent, "card"
        if rail is not None and isinstance(parent, rail):
            return parent, "rail"
        foot = getattr(parent, "odq_foot", None)
        if foot is not None and not isinstance(foot, bool):
            # The column's foot lies over the column: its words keep the column's padding.
            return foot, "rail"
        if parent in page_fields:
            return parent, "page"
        try:
            colour, round_it = str(parent.cget("bg")).lower(), str(parent.master.cget("bg")).lower()
        except (tk.TclError, AttributeError):
            colour = round_it = None
        if parent.master is not None and colour and round_it and colour != round_it and parent.winfo_class() == "Frame":
            return parent, "band"
        parent = parent.master
    return None, None


def _inside(child, parent):
    return any(p is parent for p in _ancestors(child))


def _ancestors(widget):
    found, parent = [], widget.master
    while parent is not None:
        found.append(parent)
        parent = parent.master
    return found


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _gap(a, b):
    """The room between two boxes that do not overlap: across when they share rows, down when they share columns, else
    None (diagonal, no line between them to measure)."""
    rows = a[1] < b[3] and b[1] < a[3]
    cols = a[0] < b[2] and b[0] < a[2]
    if rows:
        return max(b[0] - a[2], a[0] - b[2])
    if cols:
        return max(b[1] - a[3], a[1] - b[3])
    return None


def _contains(outer, inner):
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def _name(widget):
    """A widget as a person would point at it, for the problems' words."""
    words = getattr(widget, "words", None)
    if isinstance(words, str) and words:
        return "%s %r" % (type(widget).__name__, words[:30])
    try:
        text = str(widget.cget("text"))
    except tk.TclError:
        text = ""
    if text.strip():
        return "%r" % text[:40]
    try:
        names = [str(c.cget("text")) for c in widget.master.winfo_children() if isinstance(c, tk.Label)]
    except tk.TclError:
        names = []
    named = next((n for n in names if n.strip()), "")
    return type(widget).__name__ + (" by %r" % named[:30] if named else "")


def _in_scale(gap, ui):
    return any(abs(gap - ui.px(step)) <= 0 for step in SCALE)


def check(root, ui, name):
    """The problems of the window's boxes and room as they show now (see the module's words)."""
    problems = []
    root.update_idletasks()
    origin = (root.winfo_rootx(), root.winfo_rooty())
    found = []
    stack = [root]
    while stack:
        widget = stack.pop()
        for child in widget.winfo_children():
            try:
                if not child.winfo_ismapped() or not child.winfo_viewable() or getattr(child, "odq_skip", False):
                    continue
            except tk.TclError:
                continue
            if isinstance(child, tk.Toplevel):
                # Another window (a drop-down's list): measured by its own check, never against this window's boxes.
                continue
            stack.append(child)
            kind = _kind(child)
            if kind is None:
                continue
            box = _shown_box(child, origin)
            if box is not None:
                found.append((child, kind, box))
    solids = [f for f in found if f[1] in ("card", "field", "button", "control", "menu", "foot")]
    texts = [(t, k, _text_box(t, origin)) for t, k, _b in found if k == "text"]
    texts = [t for t in texts if t[2] is not None]
    # ---- two boxes that touch or overlap, neither part of the other.
    for i, (a, kind_a, box_a) in enumerate(solids):
        for b, kind_b, box_b in solids[i + 1:]:
            if _inside(a, b) or _inside(b, a):
                continue
            if _overlap(box_a, box_b):
                problems.append("%s: %s and %s overlap" % (name, _name(a), _name(b)))
                continue
            gap = _gap(box_a, box_b)
            if gap is not None and gap < ui.px(LEAST_GAP):
                problems.append("%s: %s and %s touch (%d px apart)" % (name, _name(a), _name(b), gap))
    # ---- words over a box they are no part of, or right against one beside them.
    for text, _kind_t, box_t in texts:
        for b, kind_b, box_b in solids:
            if kind_b in ("card", "menu", "foot") or _inside(text, b) or _inside(b, text):
                continue
            if _overlap(box_t, box_b):
                problems.append("%s: the words %s run over %s" % (name, _name(text), _name(b)))
                continue
            rows = box_t[1] < box_b[3] and box_b[1] < box_t[3]
            gap = _gap(box_t, box_b)
            if rows and gap is not None and gap < ui.px(LEAST_TEXT_GAP):
                problems.append("%s: the words %s touch %s (%d px apart)" % (name, _name(text), _name(b), gap))
    # ---- a card's faint lines: never two in a row with nothing between them (a line a list adds under one the rows
    # already draw).
    from opendmtq_client import theme
    lines = []
    for widget in [f[0] for f in found] + [w for w in _all(root) if isinstance(w, tk.Frame)]:
        try:
            if (isinstance(widget, tk.Frame) and widget.winfo_ismapped() and widget.winfo_height() <= 2
                    and str(widget.cget("bg")).lower() == theme.DIVIDER.lower()):
                box = _shown_box(widget, origin)
                if box is not None:
                    lines.append((box, widget))
        except tk.TclError:
            continue
    lines = sorted(set(lines), key=lambda item: (item[0][1], item[0][0]))
    others = [f[2] for f in found if f[1] != "card"]
    for (a, wa), (b, wb) in zip(lines, lines[1:]):
        if not (a[0] < b[2] and b[0] < a[2]) or b[1] <= a[3]:
            continue
        between = [o for o in others if o[1] >= a[3] and o[3] <= b[1] and o[0] < a[2] and a[0] < o[2]]
        if not between:
            problems.append("%s: two faint lines in a row (%d px apart), nothing between them" % (name, b[1] - a[3]))
    # ---- words inside the padding of the visible box they sit in, whatever box it is: a card, the menu column (its foot
    # with it), the page's own field outside any card (no words belong there: the page's title and the line under it
    # are drawn on its picture, everything else in a card), or any band whose colour differs from what is round it.
    page_fields = set()
    for area in [w for w in _all(root) if isinstance(w, widgets.ScrollArea)]:
        # The column and every frame of the field under it (the page's own frame, its rows, the gaps): frames in the
        # field's colour that are no card's (the column itself has no colour of its own).
        page_fields.add(area.inner)
        stack = [area.inner]
        while stack:
            frame = stack.pop()
            for child in frame.winfo_children():
                if isinstance(child, widgets.Card) or child.winfo_class() != "Frame":
                    continue
                if str(child.cget("bg")).lower() == str(area.cget("bg")).lower():
                    page_fields.add(child)
                    stack.append(child)
    for text, _kind_t, box_t in texts:
        surface, kind = _surface(text, page_fields)
        if surface is None:
            continue
        if kind == "page":
            problems.append("%s: the words %s lie on the page's field, outside any card" % (name, _name(text)))
            continue
        if kind == "card":
            # A card's own words are measured with the rest of what it holds, below.
            continue
        sides, ends = {"rail": (RAIL_SIDES, RAIL_ENDS), "band": (BAND_SIDES, BAND_ENDS)}[kind]
        whole = _whole(surface, origin) if kind != "band" else _raw(surface, origin)
        room = (whole[0] + ui.px(sides), whole[1] + ui.px(ends), whole[2] - ui.px(sides), whole[3] - ui.px(ends))
        short = [room[0] - box_t[0], room[1] - box_t[1], box_t[2] - room[2], box_t[3] - room[3]]
        edges = [side for side, by in zip(("left", "top", "right", "foot"), short) if by > SLACK]
        if edges:
            problems.append("%s: the words %s are closer to the %s of the %s they sit in than its padding (%s px)" % (
                name, _name(text), "/".join(edges), {"rail": "menu column", "band": "band"}[kind],
                "/".join(str(by) for by in short if by > SLACK)))
    # ---- what a card holds, inside its padding.
    for card, kind, card_box in found:
        if kind != "card":
            continue
        whole = _whole(card, origin)
        room = (whole[0] + ui.px(CARD_SIDES), whole[1] + ui.px(CARD_ENDS), whole[2] - ui.px(CARD_SIDES),
                whole[3] - ui.px(CARD_ENDS))
        for child, kind_c, box_c in found:
            if child is card or not _inside(child, card) or kind_c in ("card",):
                continue
            # Only what shows whole: a box the page's scroll cuts is measured where it is whole.
            if _whole(child, origin) != box_c:
                continue
            short = [room[0] - box_c[0], room[1] - box_c[1], box_c[2] - room[2], box_c[3] - room[3]]
            sides = [side for side, by in zip(("left", "top", "right", "foot"), short) if by > SLACK]
            if sides:
                problems.append("%s: %s is closer to its card's %s than the card's padding (%s px)" % (
                    name, _name(child), "/".join(sides), "/".join(str(by) for by in short if by > SLACK)))
    # ---- the gaps between siblings in a stack, on the spacing scale: each pair packed one after the other on the same
    # side (the room between a left and a right one is the stretch between them, no gap of the scale).
    seen = set()
    for widget, _k, _b in found:
        parent = widget.master
        if parent in seen or parent is None:
            continue
        seen.add(parent)
        sides = {}
        try:
            slaves = parent.pack_slaves()
        except tk.TclError:
            continue
        for child in slaves:
            try:
                if not child.winfo_ismapped() or getattr(child, "odq_skip", False):
                    continue
                side = child.pack_info().get("side", "top")
            except tk.TclError:
                continue
            if child.winfo_width() <= 1 and child.winfo_height() <= 1:
                # Nothing to see (an empty frame).
                continue
            sides.setdefault(side, []).append(child)
        for side, kids in sides.items():
            for a, b in zip(kids, kids[1:]):
                ra, rb = _raw(a, origin), _raw(b, origin)
                gap = {"top": rb[1] - ra[3], "bottom": ra[1] - rb[3], "left": rb[0] - ra[2],
                       "right": ra[0] - rb[2]}[side]
                if gap < 0 or not _in_scale(gap, ui):
                    if _shown_box(a, origin) is None or _shown_box(b, origin) is None:
                        continue
                    problems.append("%s: %d px between %s and %s, off the spacing scale" % (
                        name, gap, _name(a), _name(b)))
    return sorted(set(problems))


def check_list(droplist, ui, name):
    """An opened drop-down's list: inside the screen, its box clear of the closed box by its own gap, and its rows'
    words inside its padding."""
    problems = []
    select = droplist.select
    lx, ly = droplist.winfo_rootx(), droplist.winfo_rooty()
    lw, lh = droplist.winfo_width(), droplist.winfo_height()
    sx, sy = select.winfo_rootx(), select.winfo_rooty()
    sw, sh = select.winfo_width(), select.winfo_height()
    screen = (droplist.winfo_screenwidth(), droplist.winfo_screenheight())
    if lx < 0 or ly < 0 or lx + lw > screen[0] or ly + lh > screen[1]:
        problems.append("%s: the opened list reaches past the screen" % name)
    gap = ly - (sy + sh) if ly >= sy else sy - (ly + lh)
    if gap < ui.px(LEAST_GAP):
        problems.append("%s: the opened list touches its box (%d px apart)" % (name, gap))
    return problems


def check_dialog(dialog, name):
    """A dialog's words and buttons inside its panel's padding, its buttons clear of each other and of the words."""
    from opendmtq_client import dialogs
    problems = []
    ui, c = dialog.ui, dialog.canvas
    x0, y0 = dialog.origin
    panel = (x0, y0, x0 + dialog.panel_size[0], y0 + dialog.panel_size[1])
    pad = ui.px(dialogs.PAD)
    room = (panel[0] + pad, panel[1] + pad, panel[2] - pad, panel[3] - ui.px(LEAST_GAP))
    for item in c.find_withtag("words"):
        box = c.bbox(item)
        if "button" in " ".join(c.gettags(item)):
            continue
        if box[0] < room[0] - SLACK or box[2] > room[2] + SLACK or box[1] < room[1] - ui.px(8):
            problems.append("%s: the dialog's words %r are closer to its edge than its padding" % (
                name, c.itemcget(item, "text")[:40]))
    buttons = [(x0 + b[0], y0 + b[1], x0 + b[2], y0 + b[3]) for b in dialog._boxes]
    for i, a in enumerate(buttons):
        if a[2] > room[2] + SLACK or a[0] < room[0] - SLACK:
            problems.append("%s: the dialog's button %d is closer to its side than its padding" % (name, i + 1))
        for b in buttons[i + 1:]:
            gap = _gap(a, b)
            if _overlap(a, b) or (gap is not None and gap < ui.px(LEAST_GAP)):
                problems.append("%s: the dialog's buttons touch" % name)
    words = [c.bbox(item) for item in c.find_withtag("words") if "button" not in " ".join(c.gettags(item))]
    if buttons and words:
        lowest = max(box[3] for box in words)
        if min(b[1] for b in buttons) - lowest < ui.px(12):
            problems.append("%s: the dialog's buttons are %d px under its words" % (
                name, min(b[1] for b in buttons) - lowest))
    return problems
