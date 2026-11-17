"""The API's tokens, the site's accounts and the Notices page's webhooks kept across `./opendmtq restore`, as the admin
pages' restore keeps them: the restored database gets the server's tokens, accounts and webhooks of now, and none of the
backup's. An old backup must not bring back a token revoked since, an account deleted since, an old password or a webhook
deleted since, nor end what was made since. A server with no account yet (a new machine) takes the backup's accounts. What
the webhooks' loop knew and had waiting in the backup goes: it looks at the restored data anew and sends nothing of it.

The restore runs this in the tools container, beside the database (backup.restore copies it there), before the restored
database takes the live one's place:

    python3 keep_tokens.py <the live database> <the restored database>

The standard library only, and Python 3.9 (the command line's oldest): the container runs it from the folder of the
restore, and the tests import it.
"""

import os
import sqlite3
import sys

# The table, as the server makes it (server/game/bin/setup-db.php, tools/opendmtq_tools/admin/tokens.py): for a restored
# database from before it.
TOKEN_TABLE = """CREATE TABLE IF NOT EXISTS ApiToken (id TEXT PRIMARY KEY, name TEXT NOT NULL, scope TEXT NOT NULL,
                 hash TEXT NOT NULL, admin TEXT NOT NULL COLLATE NOCASE, owner INTEGER NOT NULL DEFAULT 0,
                 admin_since INTEGER, created_at INTEGER NOT NULL, used_at INTEGER)"""

# Its columns, in order: what is copied of each token.
COLUMNS = ("id", "name", "scope", "hash", "admin", "owner", "admin_since", "created_at", "used_at")

# The accounts' table, as the server makes it (server/game/bin/setup-db.php, tools/opendmtq_tools/admin/auth.py), for a
# restored database from before it; the admin pages add the game player's column, guid, to it (ACCOUNT_GUID).
ACCOUNT_TABLE = """CREATE TABLE IF NOT EXISTS SiteUser (name TEXT PRIMARY KEY COLLATE NOCASE, pass TEXT NOT NULL,
                   note TEXT NOT NULL DEFAULT '', admin INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL,
                   signed_in_at INTEGER, off INTEGER NOT NULL DEFAULT 0)"""
ACCOUNT_GUID = "ALTER TABLE SiteUser ADD COLUMN guid INTEGER"
# The moment from which an account's sign-ins to the site count (MY PAGE's Sign out everywhere else), which the server's
# start and the admin pages add to an older table the same way.
ACCOUNT_SIGNED_OUT = "ALTER TABLE SiteUser ADD COLUMN signed_out_at INTEGER"

# What is copied of each account, as the admin pages' restore copies it (auth.ACCOUNT_COLUMNS there).
ACCOUNT_COLUMNS = ("name", "pass", "note", "admin", "created_at", "signed_in_at", "off", "guid", "signed_out_at")

# The webhooks' tables, as the admin pages make them (tools/opendmtq_tools/admin/webhooks.py: HOOK_TABLE, MESSAGE_TABLE,
# STATE_TABLE, TOP_TABLE): the chats, the queue of messages, what the loop knew at its last look, each chart's #1 it knew.
WEBHOOK_TABLES = (
    """CREATE TABLE IF NOT EXISTS Webhook (id INTEGER PRIMARY KEY, url TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
       lang TEXT NOT NULL, events TEXT NOT NULL, made_by TEXT NOT NULL DEFAULT '', made_at INTEGER NOT NULL,
       ok_at INTEGER, fail_at INTEGER, fail_code TEXT, fail_status INTEGER, gave_up INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS WebhookMessage (id INTEGER PRIMARY KEY, hook INTEGER NOT NULL, key TEXT NOT NULL,
       kind TEXT NOT NULL, event TEXT NOT NULL, made_at INTEGER NOT NULL, next_at REAL NOT NULL,
       tries INTEGER NOT NULL DEFAULT 0, claim TEXT, claim_until INTEGER, state TEXT NOT NULL DEFAULT 'waiting',
       done_at INTEGER, UNIQUE (hook, key))""",
    "CREATE TABLE IF NOT EXISTS WebhookState (name TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS WebhookTop (pattern_id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
       score INTEGER NOT NULL, judgement INTEGER)""",
)

# What is copied of each webhook, as the admin pages' restore copies it (webhooks.COLUMNS there): its address whole.
WEBHOOK_COLUMNS = ("id", "url", "kind", "lang", "events", "made_by", "made_at", "ok_at", "fail_at", "fail_code", "fail_status", "gave_up")


def tokens_now(live):
    """The live database's tokens, as rows of COLUMNS. None when there are none to know of: no database yet (a new
    machine), one without the table, or one that cannot be read (damaged): the restored database then keeps none."""
    if not os.path.isfile(live):
        return None
    try:
        con = sqlite3.connect(live)
        try:
            if not con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ApiToken'").fetchone():
                return None
            return con.execute(f"SELECT {', '.join(COLUMNS)} FROM ApiToken").fetchall()
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return None


def keep(live, restored):
    """Gives the restored database the live one's tokens, and only them: the table made when it has none. Returns how many
    were kept. A restored file that is no database is left as it is (the restore checked the archive already)."""
    rows = tokens_now(live) or []
    try:
        con = sqlite3.connect(restored)
    except sqlite3.Error:
        return 0
    try:
        with con:
            con.execute(TOKEN_TABLE)
            # The backup's own tokens go: a token's life is today's, whatever the backup held.
            con.execute("DELETE FROM ApiToken")
            con.executemany(f"INSERT INTO ApiToken ({', '.join(COLUMNS)}) VALUES ({', '.join('?' for _ in COLUMNS)})", rows)
    except sqlite3.DatabaseError:
        # No database to put them in (the restore's own checks stand before this): nothing to keep.
        return 0
    finally:
        con.close()
    return len(rows)


def accounts_now(live):
    """The live database's accounts, as dicts of their columns. None when there are none to keep: no database yet (a new
    machine), one without the table or without an account (a server not yet in use), or one that cannot be read
    (damaged): the restored database then keeps the backup's, or a move to a new machine would leave every player out."""
    if not os.path.isfile(live):
        return None
    try:
        con = sqlite3.connect(live)
        try:
            # The columns it has: a table made before the game player's column has no guid.
            have = [r[1] for r in con.execute("PRAGMA table_info(SiteUser)")]
            if not have:
                return None
            rows = con.execute(f"SELECT {', '.join(have)} FROM SiteUser").fetchall()
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return None
    return [dict(zip(have, r)) for r in rows] or None


def keep_accounts(live, restored):
    """Gives the restored database the live one's accounts, and only them: the table made when it has none, with the game
    player's column and the sign-out moment's. Returns how many were kept, or None when the backup's stay (accounts_now)."""
    rows = accounts_now(live)
    if rows is None:
        return None
    try:
        con = sqlite3.connect(restored)
    except sqlite3.Error:
        return None
    try:
        with con:
            con.execute(ACCOUNT_TABLE)
            have = {r[1] for r in con.execute("PRAGMA table_info(SiteUser)")}
            if "guid" not in have:
                con.execute(ACCOUNT_GUID)
            # The sign-out moment's column too, for a restored table from before it.
            if "signed_out_at" not in have:
                con.execute(ACCOUNT_SIGNED_OUT)
            # The backup's own accounts go: who may sign in, and with which password, is today's.
            con.execute("DELETE FROM SiteUser")
            # Each account with the columns it came with: a live table without guid leaves it empty (not linked), one
            # without the sign-out moment leaves that empty (every sign-in counts).
            con.executemany(f"INSERT INTO SiteUser ({', '.join(ACCOUNT_COLUMNS)}) VALUES ({', '.join('?' for _ in ACCOUNT_COLUMNS)})",
                            [tuple(r.get(c) for c in ACCOUNT_COLUMNS) for r in rows])
    except sqlite3.DatabaseError:
        # No database to put them in (the restore's own checks stand before this): nothing kept.
        return None
    finally:
        con.close()
    return len(rows)


def webhooks_now(live):
    """The live database's webhooks, as rows of WEBHOOK_COLUMNS: none when there is no database yet (a new machine), no
    table (nobody added a webhook), or one that cannot be read (damaged)."""
    if not os.path.isfile(live):
        return []
    try:
        con = sqlite3.connect(live)
        try:
            if not con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'Webhook'").fetchone():
                return []
            return con.execute(f"SELECT {', '.join(WEBHOOK_COLUMNS)} FROM Webhook").fetchall()
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return []


def keep_webhooks(live, restored):
    """Gives the restored database the live one's webhooks, and only them, as the admin pages' restore does (webhooks.put
    there): the backup's own go (a webhook deleted since must not post to its chat again), and with them what the backup's
    loop knew (who was on air, how far it read) and had waiting, so that the loop looks at the restored data anew and sends
    nothing of it. Returns how many were kept."""
    rows = webhooks_now(live)
    try:
        con = sqlite3.connect(restored)
    except sqlite3.Error:
        return 0
    try:
        with con:
            for statement in WEBHOOK_TABLES:
                con.execute(statement)
            for table in ("Webhook", "WebhookMessage", "WebhookState", "WebhookTop"):
                con.execute(f"DELETE FROM {table}")
            con.executemany(f"INSERT INTO Webhook ({', '.join(WEBHOOK_COLUMNS)}) VALUES ({', '.join('?' for _ in WEBHOOK_COLUMNS)})", rows)
    except sqlite3.DatabaseError:
        # No database to put them in (the restore's own checks stand before this): nothing kept.
        return 0
    finally:
        con.close()
    return len(rows)


def keep_all(live, restored):
    """All three, as the restore runs this file: (tokens kept, accounts kept or None when the backup's stay, webhooks
    kept)."""
    return keep(live, restored), keep_accounts(live, restored), keep_webhooks(live, restored)


if __name__ == "__main__":
    # Said on the way, for the restore's log: how many tokens, accounts and webhooks stay. Never the tokens, passwords or
    # webhooks' addresses themselves.
    tokens, accounts, hooks = keep_all(sys.argv[1], sys.argv[2])
    print(f"API tokens kept: {tokens}")
    print("accounts: the backup's (this server has none)" if accounts is None else f"accounts kept: {accounts}")
    print(f"webhooks kept: {hooks}")
