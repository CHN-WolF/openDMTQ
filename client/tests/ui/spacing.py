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
    if isinstance(widget, (widgets.Button, widgets.PlaySlab)):
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


def _whole(widget, origin):
    """The widget's whole box (not cut), inset by its ring, in the window's pixels."""
    x, y = widget.winfo_rootx() - origin[0], widget.winfo_rooty() - origin[1]
    inset = _inset(widget)
    return (x + inset, y + inset, x + widget.winfo_width() - inset, y + widget.winfo_height() - inset)


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
    texts = [f for f in found if f[1] == "text"]
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
    # ---- the gaps between siblings in a stack, on the spacing scale.
    seen = set()
    for widget, _k, _b in found:
        parent = widget.master
        if parent in seen or parent is None:
            continue
        seen.add(parent)
        for axis in ("top", "left"):
            kids = []
            for child in parent.pack_slaves() if hasattr(parent, "pack_slaves") else ():
                try:
                    if not child.winfo_ismapped():
                        continue
                    side = child.pack_info().get("side", "top")
                except tk.TclError:
                    continue
                if (side in ("top", "bottom")) != (axis == "top"):
                    continue
                if child.winfo_width() <= 1 or child.winfo_height() <= 1:
                    continue
                kids.append(child)
            boxes = sorted(((_whole(k, origin), k) for k in kids), key=lambda item: item[0][1 if axis == "top" else 0])
            for (box_a, a), (box_b, b) in zip(boxes, boxes[1:]):
                # The room between the two boxes themselves, their rings left out of neither (pack's room is box to box).
                raw_a = (a.winfo_rootx() - origin[0], a.winfo_rooty() - origin[1],
                         a.winfo_rootx() - origin[0] + a.winfo_width(), a.winfo_rooty() - origin[1] + a.winfo_height())
                raw_b = (b.winfo_rootx() - origin[0], b.winfo_rooty() - origin[1],
                         b.winfo_rootx() - origin[0] + b.winfo_width(), b.winfo_rooty() - origin[1] + b.winfo_height())
                gap = raw_b[1] - raw_a[3] if axis == "top" else raw_b[0] - raw_a[2]
                if gap < 0 or not _in_scale(gap, ui):
                    shown_a, shown_b = _shown_box(a, origin), _shown_box(b, origin)
                    if shown_a is None or shown_b is None:
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
