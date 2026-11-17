"""The Notices page's Discord and Slack card: the chats the server tells of what happens on it, through webhooks.

The owner adds a webhook's address and picks what its chat hears of: a player starting a broadcast and its end, a new #1 on
a song's chart, a new #1 of the month, maintenance on and off. A loop in this service (not the game's PHP, whose saves must
never wait on a chat) looks every few seconds at what the server keeps: the play log (PlayLog) and the best scores (Play),
who is on air (site.live_now()), and the maintenance notice. What happened since its last look goes into a queue in the
database, a message for each webhook that takes it, and each queued message is sent once, with retries.

Once only, even with two of these services on one database (a restart that overlaps the old run, two pods on one volume):
each look writes what it found and how far it read in one transaction that first checks nobody else wrote since (a number
that rises with each write), and each message is claimed in a transaction of its own before it is sent.

A webhook's address is a secret (whoever has it can post to the chat): it stays in the database and leaves it only for the
chat. Pages, the API and the log of changes show it masked. Each webhook speaks one language, the admin page's when it was
added (the server has no language of its own), and can be changed."""

import calendar
import datetime
import http.client
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from flask import flash, has_request_context, redirect, request, session, url_for

from .. import songs, strings, windows_client
from . import core, notices, site
from .core import Refused, ago, app, BASE, changed, t, tp

# What a chat can hear of, in the card's order. live_off: a broadcast's end, unticked as a new webhook comes.
EVENTS = ("live_on", "live_off", "chart_top", "month_top", "maint_on", "maint_off")
DEFAULT_EVENTS = ("live_on", "chart_top", "month_top", "maint_on", "maint_off")
# Each event's words on the card, as keys of strings.py (written out: the strings' test finds them so).
EVENT_WORDS = {"live_on": "hook.ev_live_on", "live_off": "hook.ev_live_off", "chart_top": "hook.ev_chart_top",
               "month_top": "hook.ev_month_top", "maint_on": "hook.ev_maint_on", "maint_off": "hook.ev_maint_off"}

# The languages a webhook speaks, with their names as the language switch names them.
LANGUAGES = ("en", "ko")
LANGUAGE_WORDS = {"en": "hook.lang_en", "ko": "hook.lang_ko"}

# The hosts whose chats take Discord's messages; every other host gets Slack's (Slack, and the chats that take Slack's
# incoming webhooks).
DISCORD_HOSTS = {"discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com", "ptb.discordapp.com",
                 "canary.discordapp.com"}

# The longest address taken: a Discord or Slack webhook's is about 120 characters.
URL_MAX = 1000

# How often the loop looks, in seconds.
EVERY = 5
# The plays read at one look at most: a burst after a long pause is read over a few looks.
BATCH = 500
# How long a player must be off air before their broadcast counts as ended: a short drop of the phone's upload is no end.
OFF_AIR = 60
# How long to wait for a chat's answer, in seconds.
TIMEOUT = 5
# The waits before each next try of a message that did not go through, in seconds; after the last one it is given up.
BACKOFF = (10, 30, 60, 120, 300, 600, 1200)
# A message still not sent this long after its event is given up (news an hour late reads as news of now).
GIVE_UP = 1800
# How long a claimed message is another process's: longer than a send can take.
CLAIM = 60
# The messages sent at one look, at most, and to one chat (Discord lets a webhook post about 5 every 2 seconds).
SEND_AT_ONCE, SEND_PER_CHAT = 20, 5
# How long sent and given-up messages stay in the queue's table, for the card's counts.
KEEP_DONE = 86400

# The tables, made at the first use (CREATE ... IF NOT EXISTS), beside the game's. A webhook: its address, the format its
# host takes, its language, the events it takes (a comma list), who added it and when, its last message sent and its last
# failure (when, what kind, the HTTP status), and how many messages it gave up on.
HOOK_TABLE = """CREATE TABLE IF NOT EXISTS Webhook (id INTEGER PRIMARY KEY, url TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
                lang TEXT NOT NULL, events TEXT NOT NULL, made_by TEXT NOT NULL DEFAULT '', made_at INTEGER NOT NULL,
                ok_at INTEGER, fail_at INTEGER, fail_code TEXT, fail_status INTEGER, gave_up INTEGER NOT NULL DEFAULT 0)"""
# The queue: one message for one webhook, by the event's key (one event is queued once per webhook), its data as JSON,
# when it was queued and when it is next due (to the fraction of a second), its tries, which process holds it and until when, where it ended (waiting,
# sent, failed, dropped) and when.
MESSAGE_TABLE = """CREATE TABLE IF NOT EXISTS WebhookMessage (id INTEGER PRIMARY KEY, hook INTEGER NOT NULL, key TEXT NOT NULL,
                   kind TEXT NOT NULL, event TEXT NOT NULL, made_at INTEGER NOT NULL, next_at REAL NOT NULL,
                   tries INTEGER NOT NULL DEFAULT 0, claim TEXT, claim_until INTEGER, state TEXT NOT NULL DEFAULT 'waiting',
                   done_at INTEGER, UNIQUE (hook, key))"""
# What the loop knew at its last look (one row, JSON): its number (rev), how far it read the play log, this month's #1,
# who was on air, the maintenance notice.
STATE_TABLE = "CREATE TABLE IF NOT EXISTS WebhookState (name TEXT PRIMARY KEY, value TEXT NOT NULL)"
# Each chart's #1 as the loop last knew it (as the site's leaderboard orders them).
TOP_TABLE = """CREATE TABLE IF NOT EXISTS WebhookTop (pattern_id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
               score INTEGER NOT NULL, judgement INTEGER)"""
MESSAGE_INDEX = "CREATE INDEX IF NOT EXISTS WebhookMessage_due ON WebhookMessage (state, next_at)"

# The webhooks' columns, for a restore that keeps today's (kept() and put()).
COLUMNS = ("id", "url", "kind", "lang", "events", "made_by", "made_at", "ok_at", "fail_at", "fail_code", "fail_status", "gave_up")

# Adding, changing and deleting webhooks one at a time in this process, and a restore with them: none comes or goes
# between a restore's look at today's webhooks and the database taking the restored one's place.
LOCK = threading.RLock()

# A failure's kinds, with their words (keys of strings.py, written out).
FAIL_WORDS = {"gone": "hook.fail_gone", "refused": "hook.fail_refused", "bad": "hook.fail_bad", "limited": "hook.fail_limited",
              "server": "hook.fail_server", "timeout": "hook.fail_timeout", "unreachable": "hook.fail_unreachable",
              "redirect": "hook.fail_redirect"}

# The zero-width space that breaks a mention: "@everyone" in a name stays text, it calls nobody.
ZW = "​"
# What Discord reads as formatting in an embed's text: escaped with a backslash, so a name shows as it is.
DISCORD_MARKUP = re.compile(r"([\\*_~`|<>\[\]#\-])")

# Each event's colour on Discord: the colour of the site's part its link leads to (style.css), and the warning colour for
# maintenance; an end in the plain grey.
COLOURS = {"live_on": 0xFF5F72, "live_off": 0x5C6773, "chart_top": 0x6FD6FF, "month_top": 0xC491FF, "maint_on": 0xFFCF3D,
           "maint_off": 0x8CF23D, "test": 0x8CF23D}


# ------------------------------------------------------------------------------ the tables

def tables(con):
    """The webhooks' tables, made where they are not yet."""
    for statement in (HOOK_TABLE, MESSAGE_TABLE, STATE_TABLE, TOP_TABLE, MESSAGE_INDEX):
        con.execute(statement)


def connect():
    """The database, in autocommit: each write below opens its own transaction (BEGIN IMMEDIATE) and ends it."""
    con = core.db()
    # No transaction opened behind the code's back: the ones below are explicit.
    con.isolation_level = None
    return con


def has_table(con):
    """True when the webhooks' table is there (a server that never had one has none)."""
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'Webhook'").fetchone())


# ------------------------------------------------------------------------------ an address

def kind_of(url):
    """The format a webhook's address takes: Discord's for Discord's hosts, Slack's for every other."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return "discord" if host in DISCORD_HOSTS else "slack"


def check_url(raw):
    """An address as typed, as a webhook's: http or https, a host, no name or password in it, no spaces or other unseen
    characters, and not longer than URL_MAX. Refused (400 bad_url) otherwise."""
    url = (raw or "").strip()
    try:
        parts = urllib.parse.urlsplit(url)
        # The port, read now: a port that is no number fails here, not when a message is sent.
        _ = parts.port
    except ValueError:
        raise Refused(400, "bad_url", t("hook.bad_url"))
    # Printable and without spaces: a pasted address with a line break or a space in it is no address.
    if (not url or len(url) > URL_MAX or not url.isprintable() or re.search(r"\s", url) or parts.scheme.lower() not in ("http", "https")
            or not parts.hostname or parts.username is not None or parts.password is not None):
        raise Refused(400, "bad_url", t("hook.bad_url"))
    return url


def masked(url):
    """An address as the pages show it: its host and path, the last part of the path (the secret both Discord's and Slack's
    keep there) as dots and its last four characters; a query, which can hold a key too, the same way."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    # A port the address names, as it names it.
    if parts.port:
        host += f":{parts.port}"
    pieces = [p for p in parts.path.split("/") if p]
    # The last piece is the secret: dots, then its end.
    if pieces:
        pieces[-1] = "••••" + pieces[-1][-4:]
    shown = host + ("/" + "/".join(pieces) if pieces else "")
    if parts.query:
        shown += "?••••" + parts.query[-4:]
    return shown


def check_events(events):
    """The events a webhook takes, in the card's order: each one known, at least one. Refused (400) otherwise."""
    picked = list(events or [])
    if not picked or any(e not in EVENTS for e in picked):
        raise Refused(400, "bad_events", t("hook.no_events") if not picked else t("hook.bad_events"))
    return [e for e in EVENTS if e in picked]


def check_language(language):
    """A webhook's language: one of LANGUAGES. Refused (400) otherwise."""
    if language not in LANGUAGES:
        raise Refused(400, "bad_language", t("hook.bad_language"))
    return language


# ------------------------------------------------------------------------------ what the card and the API show

def failure_words(code, status, language=None):
    """A failure in words, in the page's language (or language), for the card and the API."""
    key = FAIL_WORDS.get(code, "hook.fail_unreachable")
    values = {"status": status or "", "seconds": TIMEOUT}
    return strings.text(language, key, **values) if language else tp(key, **values)


def view(row, waiting=0):
    """A webhook as the card and the API show it: its address masked, never whole."""
    # A success clears the failure before it (note_result): one there is the last result.
    failing = bool(row["fail_at"])
    return {"id": int(row["id"]), "address": masked(row["url"]), "kind": row["kind"], "language": row["lang"],
            "events": [e for e in EVENTS if e in row["events"].split(",")], "made_by": row["made_by"], "made_at": int(row["made_at"]),
            "last_sent": int(row["ok_at"]) if row["ok_at"] else None,
            # The last failure, while nothing went through since.
            "last_failure": {"at": int(row["fail_at"]), "code": row["fail_code"], "status": row["fail_status"],
                             "message": failure_words(row["fail_code"], row["fail_status"])} if failing else None,
            "waiting": int(waiting), "given_up": int(row["gave_up"] or 0)}


def listing():
    """Every webhook as view() shows it, the first added first, with how many messages wait for each."""
    con = connect()
    try:
        if not has_table(con):
            return []
        waiting = dict(con.execute("SELECT hook, COUNT(*) FROM WebhookMessage WHERE state = 'waiting' GROUP BY hook").fetchall())
        return [view(r, waiting.get(r["id"], 0)) for r in con.execute("SELECT * FROM Webhook ORDER BY id")]
    finally:
        con.close()


def failing():
    """The webhooks whose last try failed, as view() shows them: the status page's things to look at name them."""
    try:
        return [h for h in listing() if h["last_failure"]]
    except sqlite3.Error:
        return []


def find(con, hook):
    """A webhook's row by its id, or Refused (404)."""
    row = con.execute("SELECT * FROM Webhook WHERE id = ?", (hook,)).fetchone() if has_table(con) else None
    if not row:
        raise Refused(404, "webhook_not_found", t("hook.gone"))
    return row


# ------------------------------------------------------------------------------ what the owner does

def add(url, language, events):
    """Adds a webhook: its address (check_url), its language and the events it takes. Returns it as view() shows it.
    Refused: no address of a webhook, an address there already, no events or an unknown one, an unknown language."""
    url, language, events = check_url(url), check_language(language), check_events(events)
    with LOCK:
        con = connect()
        try:
            tables(con)
            con.execute("BEGIN IMMEDIATE")
            try:
                # The first webhook: the loop starts from now, with nothing of what happened before it.
                if not con.execute("SELECT 1 FROM Webhook").fetchone():
                    forget_state(con)
                # Who adds it: the admin signed in, or the API's token's; nobody outside a request (a test, a command).
                who = core.acting_who() if core.has_request_context() else ""
                cur = con.execute("INSERT INTO Webhook (url, kind, lang, events, made_by, made_at) VALUES (?, ?, ?, ?, ?, ?)",
                                  (url, kind_of(url), language, ",".join(events), who, int(time.time())))
                con.execute("COMMIT")
            except sqlite3.IntegrityError:
                con.execute("ROLLBACK")
                raise Refused(409, "webhook_taken", t("hook.taken"))
            except BaseException:
                con.execute("ROLLBACK")
                raise
            row = find(con, cur.lastrowid)
        finally:
            con.close()
    changed("webhook_new:", masked(url))
    return view(row)


def change(hook, language=None, events=None):
    """Changes a webhook's language and the events it takes (each when given). Returns it as view() shows it."""
    with LOCK:
        con = connect()
        try:
            row = find(con, hook)
            language = row["lang"] if language is None else check_language(language)
            events = row["events"].split(",") if events is None else check_events(events)
            con.execute("UPDATE Webhook SET lang = ?, events = ? WHERE id = ?", (language, ",".join(events), hook))
            row = find(con, hook)
            waiting = con.execute("SELECT COUNT(*) FROM WebhookMessage WHERE hook = ? AND state = 'waiting'", (hook,)).fetchone()[0]
        finally:
            con.close()
    changed("webhook_action:save", masked(row["url"]))
    return view(row, waiting)


def delete(hook):
    """Deletes a webhook, and the messages waiting for it. Returns its address masked."""
    with LOCK:
        con = connect()
        try:
            row = find(con, hook)
            con.execute("BEGIN IMMEDIATE")
            con.execute("DELETE FROM WebhookMessage WHERE hook = ?", (hook,))
            con.execute("DELETE FROM Webhook WHERE id = ?", (hook,))
            # The last one gone: nothing is followed any more, and a webhook added later starts from its own moment.
            if not con.execute("SELECT 1 FROM Webhook").fetchone():
                forget_state(con)
            con.execute("COMMIT")
        finally:
            con.close()
    changed("webhook_action:delete", masked(row["url"]))
    return masked(row["url"])


def send_test(hook):
    """Sends a test message to a webhook now, and notes how it went on it as any message is noted. Returns
    {"sent", "status", "code", "message"}: whether the chat took it, its HTTP status and, when it did not, why in words."""
    con = connect()
    try:
        row = find(con, hook)
    finally:
        con.close()
    result = post(row["url"], payload(row["kind"], row["lang"], "test", {"events": row["events"].split(",")}, int(time.time())))
    note_result(hook, result)
    changed("webhook_action:test", masked(row["url"]))
    return {"sent": result["ok"], "status": result["status"], "code": None if result["ok"] else result["code"],
            # A test is not sent again: a chat that asked to wait has its own words for it.
            "message": t("hook.test_sent", address=masked(row["url"])) if result["ok"] else
            (tp("hook.fail_limited_test", status=result["status"]) if result["code"] == "limited" else failure_words(result["code"], result["status"]))}


# ------------------------------------------------------------------------------ the messages

def unmention(text):
    """A name or a message as text that calls nobody: every @ broken (a zero-width space after it)."""
    return str(text if text is not None else "").replace("@", "@" + ZW)


def discord_text(text):
    """Text for a Discord embed: mentions broken, its formatting characters escaped, so it shows as it is."""
    return DISCORD_MARKUP.sub(r"\\\1", unmention(text))


def slack_text(text):
    """Text for Slack's markup (the message's fallback): mentions broken, its three control characters escaped."""
    return unmention(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def length_words(language, seconds):
    """How long a broadcast ran, in words: seconds, minutes, or hours and minutes."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return strings.text(language, "hook.len_sec", n=seconds)
    if seconds < 3600:
        return strings.text(language, "hook.len_min", n=seconds // 60)
    return strings.text(language, "hook.len_h_min", h=seconds // 3600, m=seconds // 60 % 60)


def month_words(language, start):
    """A month by its rankings' start (UTC, as the game counts it), in words: November 2026, 2026년 11월."""
    month = datetime.datetime.fromtimestamp(start, datetime.timezone.utc)
    return f"{month.year}년 {month.month}월" if language == "ko" else f"{calendar.month_name[month.month]} {month.year}"


def number(n):
    """A score with separators, as the site writes it."""
    return f"{int(n):,}"


def site_address():
    """Where players reach the site, as the installer and the launcher keep it: HTTPS where the server has it and is not
    on a local network address, plain HTTP otherwise."""
    return windows_client.site_url(core.site_scheme(core.server_health()) == "https", core.PUBLIC_HOST)


def words_of(language, kind, data):
    """An event in words for its chat: (title, sentence, the link's words, the link's path on the site). The sentence holds
    names and songs as they are; each format escapes them its own way."""
    server = core.server_name()
    say = lambda key, **values: strings.text(language, key, **values)
    if kind == "live_on":
        sentence = say("hook.msg_live_on_song", name=data["name"], song=data["song"], chart=data["chart"]) if data.get("song") \
            else say("hook.msg_live_on", name=data["name"])
        return say("hook.msg_live_on_title"), sentence, say("hook.link_live"), f"/opendmtq/live.php?p={int(data['player'])}"
    if kind == "live_off":
        # Watched again from its recording; one with none leads to the player on the live page, with their past broadcasts.
        link = (say("hook.link_replay"), f"/opendmtq/live.php?r={int(data['player'])}-{int(data['rec'])}") if data.get("rec") \
            else (say("hook.link_live"), f"/opendmtq/live.php?p={int(data['player'])}")
        return (say("hook.msg_live_off_title"), say("hook.msg_live_off", name=data["name"], length=length_words(language, data.get("seconds", 0))))\
            + link
    if kind == "chart_top":
        return (say("hook.msg_chart_title"),
                say("hook.msg_chart", name=data["name"], song=data["song"], chart=data["chart"], score=number(data["score"]),
                    before=data["before"], before_score=number(data["before_score"])),
                say("hook.link_chart"), f"/opendmtq/song.php?id={int(data['song_id'])}&chart={int(data['pattern'])}")
    if kind == "month_top":
        month = month_words(language, data["start"])
        # Ahead of the leader before, when that one is next now; the month's first leader; or the leader alone.
        if data.get("before"):
            sentence = say("hook.msg_month", name=data["name"], score=number(data["score"]), month=month, before=data["before"],
                           before_score=number(data["before_score"]))
        elif data.get("first"):
            sentence = say("hook.msg_month_first", name=data["name"], score=number(data["score"]), month=month)
        else:
            sentence = say("hook.msg_month_plain", name=data["name"], score=number(data["score"]), month=month)
        return say("hook.msg_month_title", month=month), sentence, say("hook.link_month"), "/opendmtq/ranking.php?sort=month"
    if kind == "maint_on":
        return (say("hook.msg_maint_on_title"), say("hook.msg_maint_on", server=server, message=data.get("message") or songs.DEFAULT_MAINTENANCE),
                say("hook.link_site"), "/opendmtq/")
    if kind == "maint_off":
        return say("hook.msg_maint_off_title"), say("hook.msg_maint_off", server=server), say("hook.link_site"), "/opendmtq/"
    # The test message: what this chat takes, in the card's words.
    picked = [strings.text(language, EVENT_WORDS[e]) for e in EVENTS if e in data.get("events", [])]
    # In English the card's words start a sentence; in the list after a colon they start in lower case.
    if language == "en":
        picked = [w[:1].lower() + w[1:] for w in picked]
    return (say("hook.msg_test_title"), say("hook.msg_test", server=server, events=", ".join(picked)), say("hook.link_site"),
            "/opendmtq/")


def payload(chat, language, kind, data, at):
    """The body a chat takes for an event: an embed for Discord (no mention made of anyone), blocks for Slack (names as plain
    text, the fallback escaped)."""
    title, sentence, link_words, path = words_of(language, kind, data)
    url = site_address() + path
    footer = strings.text(language, "hook.msg_footer", server=core.server_name())
    if chat == "discord":
        return {"embeds": [{"title": discord_text(title), "description": discord_text(sentence) + f"\n[{discord_text(link_words)}]({url})",
                            "url": url, "color": COLOURS.get(kind, 0x8CF23D), "footer": {"text": unmention(footer)},
                            "timestamp": datetime.datetime.fromtimestamp(at, datetime.timezone.utc).isoformat()}],
                # Nobody is called, whatever the words hold: @everyone, @here, a role or a user.
                "allowed_mentions": {"parse": []}}
    # Slack: the words as plain text (nothing in them is read as markup, mentions or links), then the link.
    return {"text": slack_text(f"{title}: {sentence}"),
            "blocks": [{"type": "section", "text": {"type": "plain_text", "text": unmention(f"{title}\n{sentence}"), "emoji": False}},
                       {"type": "context", "elements": [{"type": "mrkdwn", "text": f"<{url}|{slack_text(link_words)}> · {slack_text(footer)}"}]}]}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A webhook's address is the chat's own: one that sends elsewhere is not followed (a redirect would turn the POST into
    a GET to another address)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Requests without following redirects; the system's proxy settings as urllib reads them.
_opener = urllib.request.build_opener(_NoRedirect)


def post(url, body, timeout=TIMEOUT):
    """Sends one body to a chat. {"ok", "status", "code", "retry_after"}: whether it took it, the HTTP status (None without an
    answer), the kind of failure (FAIL_WORDS) and, when the chat asked to wait, for how many seconds."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json; charset=utf-8",
        # A name of its own: some chats refuse urllib's.
        "User-Agent": f"OpenDMTQ/{os.environ.get('OPENDMTQ_VERSION') or 'server'} (webhook)"})
    try:
        with _opener.open(req, timeout=timeout) as answer:
            status = answer.status
            if 200 <= status < 300:
                return {"ok": True, "status": status, "code": None, "retry_after": None}
            # A redirect not followed comes back as an answer of its own.
            return {"ok": False, "status": status, "code": "redirect" if 300 <= status < 400 else "bad", "retry_after": None}
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            raw = e.read(4096)
        except OSError:
            raw = b""
        finally:
            e.close()
        if status == 429:
            # Discord says how long in its body (seconds, a fraction too), Slack and others in Retry-After.
            wait = None
            try:
                wait = float(json.loads(raw or b"{}").get("retry_after"))
            except (ValueError, TypeError, AttributeError):
                pass
            if wait is None:
                try:
                    wait = float(e.headers.get("Retry-After", ""))
                except (TypeError, ValueError):
                    wait = None
            return {"ok": False, "status": 429, "code": "limited", "retry_after": max(1.0, min(wait or 10.0, 600.0))}
        code = {404: "gone", 401: "refused", 403: "refused"}.get(status)
        if code is None:
            code = "redirect" if 300 <= status < 400 else ("server" if status >= 500 else "bad")
        return {"ok": False, "status": status, "code": code, "retry_after": None}
    except (TimeoutError, OSError, ValueError, urllib.error.URLError, http.client.HTTPException) as e:
        # No answer at all: the time ran out, or the chat could not be reached.
        reason = getattr(e, "reason", e)
        timed_out = isinstance(e, TimeoutError) or isinstance(reason, TimeoutError) or "timed out" in str(reason)
        app.logger.warning("webhook: %s: %s", masked(url), reason)
        return {"ok": False, "status": None, "code": "timeout" if timed_out else "unreachable", "retry_after": None}


def note_result(hook, result):
    """How a message to a webhook went, on the webhook: when the last one went through, or the last failure. A chat that
    asked to wait (429) failed nothing: the message waits, and the card counts it."""
    if result["code"] == "limited":
        return
    con = connect()
    try:
        if result["ok"]:
            # Through: the failure before it is over.
            con.execute("UPDATE Webhook SET ok_at = ?, fail_at = NULL, fail_code = NULL, fail_status = NULL WHERE id = ?", (int(time.time()), hook))
        else:
            con.execute("UPDATE Webhook SET fail_at = ?, fail_code = ?, fail_status = ? WHERE id = ?",
                        (int(time.time()), result["code"], result["status"], hook))
    finally:
        con.close()


# ------------------------------------------------------------------------------ what the loop follows

def forget_state(con):
    """The loop's memory gone (the last webhook deleted, the first added, a restore): its next look starts from the present,
    sending nothing of the past. In the caller's transaction."""
    con.execute("DELETE FROM WebhookState")
    con.execute("DELETE FROM WebhookTop")
    con.execute("DELETE FROM WebhookMessage")


def read_state(con):
    """What the loop knew at its last look, or None before its first."""
    row = con.execute("SELECT value FROM WebhookState WHERE name = 'state'").fetchone()
    try:
        state = json.loads(row[0]) if row else None
    except ValueError:
        state = None
    return state if isinstance(state, dict) and isinstance(state.get("rev"), int) else None


def has_playlog(con):
    """True when the play log is there (the game server makes it at its start)."""
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'PlayLog'").fetchone())


# The #1 of one chart as the site's leaderboard orders it (site.board(): the score, then the accuracy, then the older
# account), among players with an account, the server's own check account left out.
TOP_OF = f"""SELECT p.user_id, p.score, p.judgement, m.nickname FROM Play p JOIN ({core.PLAYER_ROWS}) m ON m.guid = p.user_id
              WHERE p.pattern_id = ? ORDER BY p.score DESC, p.judgement DESC, p.user_id ASC LIMIT 1"""
# The next after one player: who was #1 before them.
NEXT_OF = f"""SELECT p.user_id, p.score, p.judgement, m.nickname FROM Play p JOIN ({core.PLAYER_ROWS}) m ON m.guid = p.user_id
               WHERE p.pattern_id = ? AND p.user_id != ? ORDER BY p.score DESC, p.judgement DESC, p.user_id ASC LIMIT 1"""
# Every chart's #1 at once, for the loop's first look.
ALL_TOPS = f"""SELECT pattern_id, user_id, score, judgement FROM (
                   SELECT p.pattern_id, p.user_id, p.score, p.judgement,
                          ROW_NUMBER() OVER (PARTITION BY p.pattern_id ORDER BY p.score DESC, p.judgement DESC, p.user_id ASC) AS place
                     FROM Play p JOIN ({core.PLAYER_ROWS}) m ON m.guid = p.user_id WHERE p.pattern_id IS NOT NULL)
                WHERE place = 1"""


def on_air(con, now):
    """Who is on air now, as the site shows it (site.live_now()): {guid: {"rec", "name", "song", "chart", "began"}}. rec is
    the recording the server makes of it now (the moment it began), from the stream's own file, or 0 while there is none:
    the server holds a new one back for a while after a quick end and start, and goes on unrecorded when it cannot make
    one. began: when the site counts the broadcast from (its recording's start), or now without a recording."""
    out = {}
    for p in site.live_now(con):
        guid = int(p["player"])
        try:
            with open(os.path.join(site.recordings.live_folder(guid), "stream.json"), encoding="utf-8") as f:
                rec = int(json.load(f).get("rec") or 0)
        except (OSError, ValueError, TypeError, AttributeError):
            rec = 0
        # The site counts the broadcast's seconds from its recording; without one it says none.
        seconds = int(p.get("seconds") or 0)
        out[guid] = {"rec": rec, "name": p["name"], "song": p.get("song"), "chart": p.get("chart"),
                     "began": int(now) - seconds if seconds else int(now)}
    return out


def maintenance_now():
    """The maintenance notice now: {"on", "id" (its last change's number), "message"}."""
    on, message = songs.maintenance()
    stamp = songs.maintenance_stamp() or {}
    return {"on": bool(on), "id": int(stamp.get("id") or 0), "message": message if on else ""}


def month_leader(con, start):
    """This month's first two as the site's This month ranking ranks them, from start: [{"id", "name", "score"}]."""
    if not has_playlog(con):
        return []
    return site.month_players(con, start, 2 ** 63 - 1, shown=2)


def mark_of(con, cursor):
    """The play under the id cursor as a look leaves it (when, who, which chart), or None for none: the next look sees by it
    whether the log changed under the cursor (that play deleted, its id given again to a newer one)."""
    row = con.execute("SELECT played_at, user_id, pattern_id FROM PlayLog WHERE id = ?", (cursor,)).fetchone() if cursor else None
    return [row[0], row[1], row[2]] if row else None


def read_plays(con, state):
    """The plays since the last look, in the order they were saved, BATCH at most. By their ids after the cursor; but when
    the play the last look read last is gone or another (the newest plays deleted, a player's records reset or a year-old
    log emptied, and the log giving their ids again to newer plays), by their time: those saved since the last look."""
    if not has_playlog(con):
        return []
    cursor, mark = int(state.get("cursor") or 0), state.get("mark")
    if cursor and mark is not None and mark_of(con, cursor) != mark:
        # A little before the last look, for a clock a second apart: a play read twice makes no second message (each
        # event's key is its own).
        return con.execute("SELECT id, user_id, pattern_id, score, played_at FROM PlayLog WHERE played_at >= ? ORDER BY id LIMIT ?",
                           (int(state.get("at") or 0) - 2, BATCH)).fetchall()
    return con.execute("SELECT id, user_id, pattern_id, score, played_at FROM PlayLog WHERE id > ? ORDER BY id LIMIT ?",
                       (cursor, BATCH)).fetchall()


def refresh_tops(con, guid):
    """A player's best scores gone (reset or deleted on the Players page, in con's transaction): every chart whose #1 the
    loop knew as theirs knows its #1 as it is now, so that the next to take it is told of as taking it from that one."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'WebhookTop'").fetchone():
        return
    for (pattern,) in con.execute("SELECT pattern_id FROM WebhookTop WHERE user_id = ?", (int(guid),)).fetchall():
        top = con.execute(TOP_OF, (core.CHECK_UDID, pattern)).fetchone()
        if top is None:
            con.execute("DELETE FROM WebhookTop WHERE pattern_id = ?", (pattern,))
        else:
            con.execute("UPDATE WebhookTop SET user_id = ?, score = ?, judgement = ? WHERE pattern_id = ?",
                        (int(top["user_id"]), int(top["score"] or 0), top["judgement"], pattern))


def present(con, now):
    """The state of things now, for the loop's first look: how far the play log goes, this month's #1, who is on air, the
    maintenance notice; and every chart's #1 (returned beside it)."""
    cursor = con.execute("SELECT COALESCE(MAX(id), 0) FROM PlayLog").fetchone()[0] if has_playlog(con) else 0
    start = site.month_start()
    board = month_leader(con, start)
    air = {str(g): broadcast(p, now) for g, p in on_air(con, now).items()}
    tops = [tuple(r) for r in con.execute(ALL_TOPS, (core.CHECK_UDID,))]
    state = {"rev": 0, "cursor": int(cursor), "mark": mark_of(con, int(cursor)) if cursor else None, "at": int(now),
             "month": {"start": start, "leader": board[0]["id"] if board else None}, "air": air, "maint": maintenance_now()}
    return state, tops


def broadcast(p, now):
    """A broadcast as the loop keeps it, from the first look that saw it on air (on_air()'s p): when it began, its first
    recording (0 until there is one), who, and when a look last saw it on air."""
    return {"began": int(p["began"]), "rec": int(p["rec"]), "name": p["name"], "seen": int(now)}


def ended(guid, was, now):
    """A broadcast's end as its message tells it: who, its first recording (to watch it again; 0 for none), and how long it
    ran, from its start to the last look that saw it on air."""
    return {"player": int(guid), "name": was["name"], "rec": int(was.get("rec") or 0),
            "seconds": max(0, int(was.get("seen", now)) - int(was.get("began", now)))}


def look(con, state, now):
    """What happened since the last look (state), read without writing anything: [(kind, key, data)] and the state and
    the charts' #1s to keep. Each event's key is the same whoever looks, so that a message is queued once."""
    events, tops = [], {}
    new = json.loads(json.dumps(state))
    # The plays since the last look, in the order they were saved; the cursor and its mark at the last of them.
    plays = read_plays(con, state)
    if plays:
        new["cursor"] = int(plays[-1]["id"])
        new["mark"] = [plays[-1]["played_at"], plays[-1]["user_id"], plays[-1]["pattern_id"]]
    # When this look was: the next reads by time from here when the log changed under its cursor.
    new["at"] = int(now)
    # The charts they were on, with who played each.
    touched = {}
    for p in plays:
        if p["pattern_id"] is not None and p["user_id"] is not None:
            touched.setdefault(int(p["pattern_id"]), set()).add(int(p["user_id"]))
    # The song list only when a chart was played: a look with nothing new reads no file.
    charts, by_id = (site.chart_map(), site.songs_by_id()) if touched else ({}, {})
    for pattern, players in touched.items():
        current = con.execute(TOP_OF, (core.CHECK_UDID, pattern)).fetchone()
        known = con.execute("SELECT user_id, score, judgement FROM WebhookTop WHERE pattern_id = ?", (pattern,)).fetchone()
        if current is None:
            tops[pattern] = None
            continue
        holder = int(current["user_id"])
        # The best scores are read as they are now, past this look's share of the plays: a holder whose play this look has
        # not read yet is not known as the holder until a look reads it, which then tells of it. Known so: the holder
        # before, the same holder (their own record), or a holder who played in this look's share.
        if known is None and holder not in players:
            continue
        if known is not None and holder != int(known["user_id"]) and holder not in players:
            continue
        tops[pattern] = (holder, int(current["score"] or 0), current["judgement"])
        # A chart nobody held before (its first clear) has nobody to take its #1 from; the same player again is their own
        # record.
        if known is None or int(known["user_id"]) == holder:
            continue
        # Who it was taken from: the #1 the loop knew, still there with the score it held. A #1 gone otherwise (their
        # scores reset, their player deleted) was taken from nobody.
        before = con.execute(NEXT_OF, (core.CHECK_UDID, pattern, int(current["user_id"]))).fetchone()
        if before is None or int(before["user_id"]) != int(known["user_id"]) or int(before["score"] or 0) < int(known["score"]):
            continue
        info = site.chart_info(pattern, charts, by_id)
        # A chart the server's song list no longer has is no news either, nor one of a song the owner hid from players:
        # its name stays off the chat as it stays off the site.
        if info["song"] is None or by_id[info["song"]].get("hidden_yn", "N") == "Y":
            continue
        guid = int(current["user_id"])
        events.append(("chart_top", f"chart_top:{pattern}:{guid}:{int(current['score'] or 0)}:{current['judgement']}",
                       {"player": guid, "name": site.player_name(current["nickname"], guid), "pattern": pattern, "song_id": info["song"],
                        "song": info["title"], "chart": info["chart_name"], "score": int(current["score"] or 0),
                        "before_player": int(before["user_id"]), "before": site.player_name(before["nickname"], before["user_id"]),
                        "before_score": int(before["score"] or 0)}))
    # This month's #1, once someone played this month: whoever leads now, against whom the loop knew to lead.
    start = site.month_start()
    month_plays = [p for p in plays if int(p["played_at"] or 0) >= start]
    if month_plays or new["month"].get("start") != start:
        known = new["month"].get("leader") if new["month"].get("start") == start else None
        board = month_leader(con, start) if month_plays else []
        leader = board[0] if board else None
        players = {int(p["user_id"]) for p in month_plays if p["user_id"] is not None}
        # A new leader who played in this look's share of the plays took it; the first of a new month too. One whose plays
        # this look has not read yet (the board is read as it is now) leads from the look that reads them, which tells of
        # it: until then the leader the loop knew stays.
        if leader and leader["id"] != known and leader["id"] in players:
            before = next((b for b in board[1:] if b["id"] == known), None) if known is not None else None
            # The one before: the runner-up now, when that is the leader the loop knew.
            events.append(("month_top", f"month_top:{start}:{leader['id']}:{leader['score']}",
                           {"player": leader["id"], "name": leader["name"], "score": leader["score"], "start": start, "first": known is None,
                            "before": before["name"] if before else None, "before_score": before["score"] if before else None}))
            new["month"] = {"start": start, "leader": leader["id"]}
        elif leader and leader["id"] != known:
            new["month"] = {"start": start, "leader": known}
        else:
            new["month"] = {"start": start, "leader": leader["id"] if leader else known}
    # Who is on air. A broadcast is a player on air, from the first look that sees them until they have been off air for
    # OFF_AIR seconds: whatever its recordings do meanwhile (none for a while, a new one each hour, a new one after a short
    # drop), it is one start and one end. Its key is when it began, as the look that first saw it kept it.
    air_now = on_air(con, now)
    air = new.get("air", {})
    for guid, p in air_now.items():
        was = air.get(str(guid))
        if was is None:
            started = air[str(guid)] = broadcast(p, now)
            events.append(("live_on", f"live_on:{guid}:{started['began']}", {"player": guid, "name": p["name"], "song": p["song"],
                                                                             "chart": p["chart"], "rec": p["rec"]}))
            continue
        # The same broadcast, seen now: its end counts from the last look that saw it. Its first recording is the one it
        # is watched again from, kept once there is one.
        was.update(seen=int(now), name=p["name"])
        if not was.get("rec") and p["rec"]:
            was["rec"] = p["rec"]
    for guid in list(air):
        # Off air for OFF_AIR seconds: ended. One on air at the loop's first look ends too, though its start was before.
        if int(guid) not in air_now and now - int(air[guid].get("seen", now)) >= OFF_AIR:
            was = air.pop(guid)
            events.append(("live_off", f"live_off:{guid}:{was['began']}", ended(int(guid), was, now)))
    new["air"] = air
    # The maintenance notice turned on or off since the last look.
    maint = maintenance_now()
    if maint["on"] != bool(new.get("maint", {}).get("on")):
        kind = "maint_on" if maint["on"] else "maint_off"
        events.append((kind, f"{kind}:{maint['id'] or int(now)}", {"message": maint["message"]}))
    new["maint"] = maint
    return events, new, tops


def write(con, rev, events, new, tops, now):
    """Queues the events for every webhook that takes them and keeps the new state, in one transaction, unless another
    process wrote since rev (then it found the same, and nothing is done here). Returns how many messages were queued."""
    con.execute("BEGIN IMMEDIATE")
    try:
        kept = read_state(con)
        if kept is None or kept["rev"] != rev:
            con.execute("ROLLBACK")
            return 0
        queued = 0
        hooks = [(int(h["id"]), h["events"].split(",")) for h in con.execute("SELECT id, events FROM Webhook")]
        for kind, key, data in events:
            for hook, wanted in hooks:
                if kind in wanted:
                    cur = con.execute("INSERT OR IGNORE INTO WebhookMessage (hook, key, kind, event, made_at, next_at) VALUES (?, ?, ?, ?, ?, ?)",
                                      (hook, key, kind, json.dumps(data, ensure_ascii=False), int(now), now))
                    queued += cur.rowcount
        for pattern, top in tops.items():
            if top is None:
                con.execute("DELETE FROM WebhookTop WHERE pattern_id = ?", (pattern,))
            else:
                con.execute("INSERT OR REPLACE INTO WebhookTop (pattern_id, user_id, score, judgement) VALUES (?, ?, ?, ?)", (pattern,) + top)
        new["rev"] = rev + 1
        con.execute("INSERT OR REPLACE INTO WebhookState (name, value) VALUES ('state', ?)", (json.dumps(new, ensure_ascii=False),))
        con.execute("COMMIT")
        return queued
    except BaseException:
        con.execute("ROLLBACK")
        raise


def detect(now=None):
    """One look at what happened, queued for the webhooks that take it. With no webhook, nothing is followed. The first look
    (or the first after the loop forgot, at a restore) takes the present as its start. Returns how many messages it
    queued."""
    now = time.time() if now is None else now
    con = connect()
    try:
        if not has_table(con) or not con.execute("SELECT 1 FROM Webhook").fetchone():
            return 0
        state = read_state(con)
        if state is None:
            start, tops = present(con, now)
            con.execute("BEGIN IMMEDIATE")
            try:
                # Another process took its start first: that one stays.
                if read_state(con) is None:
                    con.execute("DELETE FROM WebhookTop")
                    con.executemany("INSERT INTO WebhookTop (pattern_id, user_id, score, judgement) VALUES (?, ?, ?, ?)", tops)
                    con.execute("INSERT OR REPLACE INTO WebhookState (name, value) VALUES ('state', ?)", (json.dumps(start, ensure_ascii=False),))
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
            return 0
        # Everything the look reads, from one moment of the database: the plays and the best scores they made, together.
        con.execute("BEGIN")
        try:
            events, new, tops = look(con, state, now)
        finally:
            con.execute("COMMIT")
        return write(con, state["rev"], events, new, tops, now)
    finally:
        con.close()


# ------------------------------------------------------------------------------ the sending

def claim(con, me, now):
    """The next message due, claimed for this process (me) until CLAIM seconds from now, in one transaction: nobody else
    sends it meanwhile. First the messages too old to send are given up and counted on their webhooks, and what ended a day
    ago leaves the table. None when nothing is due."""
    con.execute("BEGIN IMMEDIATE")
    try:
        old = con.execute("SELECT hook, COUNT(*) FROM WebhookMessage WHERE state = 'waiting' AND made_at < ? GROUP BY hook",
                          (int(now) - GIVE_UP,)).fetchall()
        for hook, n in old:
            con.execute("UPDATE Webhook SET gave_up = gave_up + ? WHERE id = ?", (n, hook))
        con.execute("UPDATE WebhookMessage SET state = 'dropped', done_at = ? WHERE state = 'waiting' AND made_at < ?", (int(now), int(now) - GIVE_UP))
        con.execute("DELETE FROM WebhookMessage WHERE state != 'waiting' AND done_at < ?", (int(now) - KEEP_DONE,))
        row = con.execute("""SELECT m.id, m.hook, m.kind, m.event, m.made_at, m.tries, w.url, w.kind AS chat, w.lang
                               FROM WebhookMessage m JOIN Webhook w ON w.id = m.hook
                              WHERE m.state = 'waiting' AND m.next_at <= ? AND (m.claim_until IS NULL OR m.claim_until < ?)
                              ORDER BY m.id LIMIT 1""", (now, now)).fetchone()
        if row:
            con.execute("UPDATE WebhookMessage SET claim = ?, claim_until = ? WHERE id = ?", (me, int(now) + CLAIM, row["id"]))
        con.execute("COMMIT")
        return row
    except BaseException:
        con.execute("ROLLBACK")
        raise


def settle(con, row, me, result, now):
    """A claimed message's end: sent; or tried again after its wait (the chat's own when it asked for one), its webhook's
    other messages after it, so that they keep their order; or stopped (the webhook gone, refused, the message refused, the
    last wait over). Only while this process still holds it."""
    if result["ok"]:
        con.execute("UPDATE WebhookMessage SET state = 'sent', done_at = ?, claim = NULL WHERE id = ? AND claim = ?", (int(now), row["id"], me))
        return
    stop = result["code"] in ("gone", "refused", "bad", "redirect") or row["tries"] + 1 > len(BACKOFF)
    if stop:
        con.execute("UPDATE WebhookMessage SET state = 'failed', done_at = ?, claim = NULL, tries = tries + 1 WHERE id = ? AND claim = ?",
                    (int(now), row["id"], me))
        return
    wait = result["retry_after"] if result["code"] == "limited" else BACKOFF[row["tries"]]
    # To the fraction of a second: a chat that asks for 2.5 seconds gets them, no more.
    due = now + wait
    con.execute("UPDATE WebhookMessage SET next_at = ?, claim = NULL, claim_until = NULL, tries = tries + 1 WHERE id = ? AND claim = ?",
                (due, row["id"], me))
    # The webhook's later messages wait as long: a chat hears of things in the order they happened.
    con.execute("UPDATE WebhookMessage SET next_at = MAX(next_at, ?) WHERE hook = ? AND state = 'waiting' AND id != ?", (due, row["hook"], row["id"]))


def deliver(now=None, me=None):
    """Sends what is due, SEND_AT_ONCE at most and SEND_PER_CHAT to one webhook, each claimed first. Returns how many went
    through."""
    me = me or f"{os.getpid()}-{secrets.token_hex(4)}"
    con = connect()
    sent, per_chat = 0, {}
    try:
        if not has_table(con):
            return 0
        for _ in range(SEND_AT_ONCE):
            at = time.time() if now is None else now
            row = claim(con, me, at)
            if row is None:
                break
            per_chat[row["hook"]] = per_chat.get(row["hook"], 0) + 1
            try:
                data = json.loads(row["event"])
            except ValueError:
                data = {}
            result = post(row["url"], payload(row["chat"], row["lang"], row["kind"], data, row["made_at"]))
            settle(con, row, me, result, time.time() if now is None else now)
            note_result(row["hook"], result)
            sent += 1 if result["ok"] else 0
            # Enough for one chat at one look: the next look goes on.
            if per_chat[row["hook"]] >= SEND_PER_CHAT:
                con.execute("UPDATE WebhookMessage SET next_at = MAX(next_at, ?) WHERE hook = ? AND state = 'waiting'",
                            (at + EVERY, row["hook"]))
        return sent
    finally:
        con.close()


def run_once(now=None):
    """One turn of the loop: a look, then the sending."""
    detect(now)
    return deliver(now)


def _loop():
    """The thread: a turn every EVERY seconds. A turn that fails (the database busy or away) is tried again at the next; the
    log says why once, not every few seconds while it lasts."""
    said = ""
    while True:
        time.sleep(EVERY)
        try:
            run_once()
            said = ""
        except Exception as e:  # pylint: disable=broad-except
            # The next turn tries again; the log says why, once for the same reason.
            why = f"{e.__class__.__name__}: {e}"
            if why != said:
                app.logger.warning("webhooks: %s", why)
            said = why


# The loop runs in this service from its start, with or without a page open. OPENDMTQ_WEBHOOK_LOOP=off leaves it out: the
# unit tests turn it themselves (run_once).
if os.environ.get("OPENDMTQ_WEBHOOK_LOOP", "on") != "off":
    threading.Thread(target=_loop, name="webhooks", daemon=True).start()


# ------------------------------------------------------------------------------ a restore

def kept(con):
    """Today's webhooks, for a restore to put back (put())."""
    tables(con)
    return con.execute(f"SELECT {', '.join(COLUMNS)} FROM Webhook").fetchall()


def put(con, rows):
    """con's webhooks made exactly rows (today's, read by kept()), and the loop's memory and queue gone: a restore keeps
    the chats as they are now, and nothing it brings back is sent again. In the caller's transaction."""
    tables(con)
    con.execute("DELETE FROM Webhook")
    con.executemany(f"INSERT INTO Webhook ({', '.join(COLUMNS)}) VALUES ({', '.join('?' for _ in COLUMNS)})",
                    [tuple(r[c] for c in COLUMNS) for r in rows])
    forget_state(con)


# ------------------------------------------------------------------------------ the card

# What a refused Add had typed, for the page it comes back to: once, ten minutes at most, in this process's memory, the
# session holding only the way to it (the address is a secret: never in the browser's cookie).
_typed = {}
_typed_lock = threading.Lock()


def keep_typed(values):
    """Keeps what the add form sent for the next drawing of the card in this session."""
    now = time.time()
    token = secrets.token_urlsafe(12)
    with _typed_lock:
        # What nobody came back for is forgotten.
        for old in [k for k, (at, _) in _typed.items() if now - at > 600]:
            del _typed[old]
        _typed[token] = (now, values)
    session["hooks_typed"] = token


def take_typed():
    """What keep_typed() kept for this session, once; None when there is nothing (or it is older than ten minutes)."""
    if not has_request_context():
        return None
    with _typed_lock:
        kept = _typed.pop(session.pop("hooks_typed", ""), None)
    return kept[1] if kept and time.time() - kept[0] <= 600 else None


@notices.card("hooks")
def hooks_card():
    """The Notices page's Discord and Slack card: every webhook, and what the form to add one offers (with what a refused
    one had typed)."""
    try:
        items, broken = listing(), False
    except sqlite3.Error:
        items, broken = [], True
    for h in items:
        # How long ago, in the page's words.
        h["sent_ago"] = ago(h["last_sent"]) if h["last_sent"] else ""
        h["made_ago"] = ago(h["made_at"])
        if h["last_failure"]:
            h["last_failure"]["ago"] = ago(h["last_failure"]["at"])
    return {"chats": items, "broken": broken, "events": EVENTS, "defaults": DEFAULT_EVENTS, "event_words": EVENT_WORDS,
            "languages": LANGUAGES, "language_words": LANGUAGE_WORDS, "language": core.lang(), "url_max": URL_MAX,
            "typed": take_typed()}


def back():
    """The page again, at the card."""
    return redirect(url_for("maintenance_page") + "#hooks")


@app.route(BASE + "/webhooks", methods=["POST"])
def webhook_new():
    """The card's form: a webhook added. A refused one comes back to the page with what was typed, and why: by a redirect,
    as a form sent in place (admin.js) needs the page's own address back."""
    url, language, events = request.form.get("url", ""), request.form.get("language", core.lang()), request.form.getlist("event")
    try:
        made = add(url, language, events)
    except Refused as e:
        flash(e.words, e.tone)
        keep_typed({"url": url[:URL_MAX], "language": language, "events": events})
        return back()
    flash(t("hook.added", address=made["address"]), "ok")
    return back()


@app.route(BASE + "/webhooks/<int:hook>", methods=["POST"])
def webhook_action(hook):
    """A webhook's buttons: save (its language and events), test, delete."""
    action = request.form.get("action", "")
    try:
        if action == "save":
            done = change(hook, request.form.get("language"), request.form.getlist("event"))
            flash(t("hook.saved", address=done["address"]), "ok")
        elif action == "test":
            result = send_test(hook)
            flash(result["message"] if result["sent"] else t("hook.test_failed", why=result["message"]), "ok" if result["sent"] else "bad")
        elif action == "delete":
            flash(t("hook.deleted", address=delete(hook)), "ok")
    except Refused as e:
        flash(e.words, e.tone)
    return back()
