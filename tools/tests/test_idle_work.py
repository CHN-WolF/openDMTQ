"""Tests for what the admin service does every few seconds while nothing happens on the server: the Discord and Slack
webhooks' loop (admin/webhooks.py) writes nothing, takes no write lock and reads no song list then, and reads the song list
once a look for a broadcast in a song; what it tells of stays as test_webhooks.py checks it.

Flask is installed in the tools image only; outside it these tests are skipped (CI runs them there)."""

import sqlite3
import unittest
from unittest import mock

from tests.test_admin import HAVE_FLASK

if HAVE_FLASK:
    from opendmtq_tools import admin
    from opendmtq_tools.admin import webhooks
    from tests.test_webhooks import Server


def broadcasts_on(guid):
    """Broadcasts on for the server and a player's switch on, their phone sending nothing: on the list, not on air."""
    con = sqlite3.connect(admin.core.DB)
    admin.recordings.live_table(con)
    con.execute(admin.recordings.SETTING_TABLE)
    con.execute("INSERT OR REPLACE INTO LiveSetting (name, value) VALUES ('on', '1')")
    con.execute("INSERT OR REPLACE INTO LiveSwitch (guid, live) VALUES (?, 1)", (guid,))
    con.commit()
    con.close()


class Traced:
    """Every statement the loop's connections run while it is on, in order."""

    def __init__(self):
        self.statements = []
        self._real = admin.core.db

    def db(self):
        con = self._real()
        con.set_trace_callback(self.statements.append)
        return con

    def writes(self):
        """The statements that write or take the write lock."""
        return [s for s in self.statements if s.split()[0].upper() in ("INSERT", "UPDATE", "DELETE", "REPLACE")
                or s.upper().startswith("BEGIN IMMEDIATE")]


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class IdleLoopTest(unittest.TestCase):
    """The loop's turns on a server where nothing happens."""

    def test_a_turn_with_nothing_new_writes_nothing_and_reads_no_song_list(self):
        with Server() as srv:
            srv.hook()
            broadcasts_on(8)
            # The loop's start (the present as its state), then a turn that has seen everything there is.
            webhooks.run_once()
            webhooks.run_once()
            traced = Traced()
            song_list = mock.Mock(side_effect=AssertionError("the song list was read"))
            with mock.patch.object(admin.core, "db", traced.db), mock.patch.object(admin.site, "song_list", song_list):
                for _ in range(3):
                    self.assertEqual(webhooks.run_once(), 0)
            # It looked (the plays, the webhooks), and wrote nothing, took no write lock and read no file of songs.
            self.assertTrue(any("FROM PlayLog" in s for s in traced.statements), traced.statements)
            self.assertEqual(traced.writes(), [])
            song_list.assert_not_called()
            self.assertEqual(srv.chat.got, [])

    def test_what_happens_after_a_quiet_while_is_still_told(self):
        with Server() as srv:
            srv.hook(events=["chart_top"])
            webhooks.run_once()
            for _ in range(3):
                webhooks.run_once()
            # Yuna takes Sena's #1 of the chart after the quiet turns: told once.
            srv.play(8, 11, 950000)
            webhooks.run_once()
            webhooks.run_once()
            self.assertEqual([m[1] for m in srv.queued()], ["chart_top"])
            self.assertEqual(len(srv.chat.got), 1)

    def test_a_broadcast_in_a_song_reads_the_song_list_once_a_look(self):
        with Server() as srv:
            srv.hook()
            srv.on_air(8, 1_700_000_000)
            con = sqlite3.connect(admin.core.DB)
            con.execute("UPDATE LiveSwitch SET playing = 1, pattern_id = 11, play_at = strftime('%s', 'now') WHERE guid = 8")
            con.commit()
            con.close()
            webhooks.run_once()
            reads = []
            real = admin.site.song_list

            def counted():
                reads.append(1)
                return real()

            with mock.patch.object(admin.site, "song_list", counted):
                on_air = admin.site.live_now(admin.core.db())
            # The song and the chart it is in, from one read of the list.
            self.assertEqual([(p["player"], p["song"]) for p in on_air], [(8, "Paper Planes")])
            self.assertEqual(len(reads), 1)
