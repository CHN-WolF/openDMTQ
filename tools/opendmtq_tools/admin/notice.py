"""The Notices page's notice on the site: one line the owner sets, with an optional end, shown above every page of the
players' site to whoever has signed in, and in the game's lobby news (server/game/src/user.php).

It is kept beside the database as notice.json ({"text", "until", "at", "by"}), written to a new file and moved into
place, so that the site and the game never read half of one. Without the file there is none. The site reads it on every
page (lib.php site_notice()); the game with the lobby's news call. Each function is what the card's form and the API both
call (api.py): the page and the API cannot differ."""

import datetime
import json
import os
import threading
import time

from flask import flash, redirect, request, url_for

from . import core, notices
from .core import Refused, app, BASE, changed, t

# The longest notice, in characters: one line above every page, on a phone too.
MOST = 200

# One write at a time in this process: two at once writing the same ".new" file could interleave.
_writing = threading.Lock()


def path():
    """Where the notice is kept: notice.json beside the database, which the site and the game read too."""
    return os.path.join(os.path.dirname(core.DB), "notice.json")


def clean(text):
    """The notice as it is kept: every run of whitespace (line breaks too) one space, nothing at the ends."""
    return " ".join(str(text or "").split())


def check(text):
    """Refuses a notice (already cleaned) longer than MOST characters, or with control or formatting characters: a
    direction override would turn the page's own words around it."""
    if len(text) > MOST:
        raise Refused(400, "notice_too_long", t("notice.too_long", max=MOST))
    if not text.isprintable():
        raise Refused(400, "notice_not_text", t("notice.not_text"))


def read():
    """The notice as kept ({"text", "until", "at", "by"}), or None: no file, an empty one, or one that cannot be read (the
    page then shows none rather than fail)."""
    try:
        with open(path(), encoding="utf-8") as f:
            kept = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(kept, dict) or not isinstance(kept.get("text"), str) or not kept["text"]:
        return None
    # An end that is no whole number is no end.
    until = kept.get("until")
    kept["until"] = until if isinstance(until, int) and not isinstance(until, bool) else None
    return kept


def shown(kept=None, now=None):
    """True while the notice is up on the site: there is one, and its end, when it has one, has not come."""
    kept = read() if kept is None else kept
    now = time.time() if now is None else now
    return bool(kept) and (kept["until"] is None or kept["until"] > now)


def put(text, until=None, who=""):
    """Shows text (cleaned, then checked) from now, until the moment until (Unix time, or None for no end). Refused: too
    long, not text, nothing to show, or an end that has come already. Returns the notice as kept."""
    text = clean(text)
    if not text:
        raise Refused(400, "notice_empty", t("notice.empty"))
    check(text)
    if until is not None and until <= time.time():
        raise Refused(400, "notice_end_past", t("notice.end_past"))
    kept = {"text": text, "until": until, "at": int(time.time()), "by": who}
    with _writing:
        # A new file moved over the old one: readers see the old notice or the new one, never half of either.
        os.makedirs(os.path.dirname(path()), exist_ok=True)
        with open(path() + ".new", "w", encoding="utf-8") as f:
            json.dump(kept, f, ensure_ascii=False)
        os.replace(path() + ".new", path())
    changed("notice:show", end_words(until))
    return kept


def clear():
    """Takes the notice down (the file goes). Returns the notice it was, or None when there was none: nothing happened
    then, and nothing goes into the log of changes."""
    kept = read()
    with _writing:
        try:
            os.remove(path())
        except FileNotFoundError:
            pass
    if kept is not None:
        changed("notice:clear")
    return kept


def view(kept=None):
    """The notice as the API answers it: its words ("" for none), whether it is up now, its end and when and by whom it
    was set (Unix times; null for none)."""
    kept = read() if kept is None else kept
    return {"text": kept["text"] if kept else "", "shown": shown(kept) if kept else False,
            "until": kept["until"] if kept else None, "set_at": kept.get("at") if kept else None,
            "by": kept.get("by") or None if kept else None}


def end_words(until):
    """The end as the log of changes keeps it: the server's own time, to the minute, or nothing for no end."""
    return datetime.datetime.fromtimestamp(until).strftime("%Y-%m-%d %H:%M") if until else ""


def parse_end(typed):
    """The end the card's field holds (the browser's date and time, YYYY-MM-DDTHH:MM, in the server's own time), as Unix
    time; None when it is empty. Refused: anything else."""
    typed = (typed or "").strip()
    if not typed:
        return None
    try:
        return int(datetime.datetime.strptime(typed[:16], "%Y-%m-%dT%H:%M").timestamp())
    except ValueError:
        raise Refused(400, "bad_end", t("notice.bad_end"))


def field_end(until):
    """An end as the card's field holds it (YYYY-MM-DDTHH:MM in the server's own time), or empty."""
    return datetime.datetime.fromtimestamp(until).strftime("%Y-%m-%dT%H:%M") if until else ""


@notices.card("notice")
def notice_card():
    """The card's values: the notice kept (its words stay in the field after it ended, for the next time), whether it is up
    now, its end in words and in the field's own form, and the most it may hold."""
    kept = read()
    up = shown(kept)
    return {"text": kept["text"] if kept else "", "shown": up, "ended": bool(kept) and not up,
            "until": end_words(kept["until"]) if kept and kept["until"] else "",
            "field_until": field_end(kept["until"]) if kept and up else "", "max": MOST}


@app.route(BASE + "/notice", methods=["POST"])
def notice_form():
    """The card's two buttons: Show (a new notice, or the same with new words or a new end) and Take down."""
    if request.form.get("action") == "clear":
        # A page left open after it was taken down elsewhere: said so, in the colour of nothing wrong.
        flash(t("notice.cleared" if clear() is not None else "notice.none_to_clear"), "ok")
        return redirect(url_for("maintenance_page") + "#notice")
    text, typed_end = request.form.get("text", ""), request.form.get("until", "")
    try:
        was_up = shown()
        put(text, parse_end(typed_end), core.acting_who())
    except Refused as e:
        # The page again with what was typed, to fix, and why.
        flash(e.words, e.tone)
        return notices.render(e.status, notice={"text": text, "field_until": typed_end})
    flash(t("notice.updated" if was_up else "notice.shown"), "ok")
    return redirect(url_for("maintenance_page") + "#notice")
