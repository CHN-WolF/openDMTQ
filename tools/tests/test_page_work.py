"""Tests for the work the admin pages do for one request (admin/core.py, players.py): the page's language worked out once a
request, and the Players page's day cells made once for each run of counts.

Flask is installed in the tools image only; outside it these tests are skipped (CI runs them there)."""

import datetime
import sqlite3
import time
import unittest
from unittest import mock

from tests.test_admin import HAVE_FLASK, Install, member_rows, old_game_database

if HAVE_FLASK:
    import werkzeug.datastructures

    from opendmtq_tools import admin
    from opendmtq_tools.admin import charts, players


def players_with_plays(path, count, plays_of=lambda guid: 0):
    """count players (1, 2, ...), each with plays_of(guid) plays over the last days, a second phone for player 2 and the
    broadcast switch on for player 3: the tables the Players page reads."""
    old_game_database(path, [])
    member_rows(path, [(g, f"Player{g}", f"phone-{g}") for g in range(1, count + 1)])
    con = sqlite3.connect(path)
    # A second phone of player 2's, under the same player number.
    con.execute("INSERT INTO Member (id, nickname, guid, udid) VALUES (?, 'Player2', '2', 'phone-2b')", (count + 1,))
    con.execute("CREATE TABLE PlayLog (id INTEGER PRIMARY KEY, user_id INTEGER, pattern_id INTEGER, score INTEGER, grade TEXT, "
                "judgement INTEGER, is_record INTEGER, played_at INTEGER, keys INTEGER NOT NULL DEFAULT 0)")
    con.execute("CREATE TABLE LiveSwitch (guid INTEGER PRIMARY KEY, live INTEGER NOT NULL DEFAULT 0, token TEXT, toast TEXT, "
                "changed_at INTEGER, playing INTEGER NOT NULL DEFAULT 0, pattern_id INTEGER, play_at INTEGER, "
                "toast_id INTEGER NOT NULL DEFAULT 0, maint_seen INTEGER NOT NULL DEFAULT 0)")
    con.execute("INSERT INTO LiveSwitch (guid, live) VALUES (3, 1)")
    now = int(time.time())
    for g in range(1, count + 1):
        for k in range(plays_of(g)):
            # A play every few hours back from now, on a few charts; the best of each as the game keeps it.
            con.execute("INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at) VALUES (?, ?, ?, 'A', 950, 0, ?)",
                        (g, 100 + k % 3, 500000 + 1000 * k, now - 3600 * (5 * k + g)))
        if plays_of(g):
            con.execute("INSERT INTO Play SELECT pattern_id, user_id, MAX(score), 'A', 'N', 'N', 950 FROM PlayLog WHERE user_id = ? GROUP BY pattern_id", (g,))
    con.commit()
    con.close()


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class PageLanguageTest(unittest.TestCase):
    """A page asks for its language for every word it shows: the visitor's choice is read from the cookie once a request."""

    def test_a_page_reads_its_language_once_in_either_language(self):
        real_get = werkzeug.datastructures.ImmutableMultiDict.get
        for lang, word in (("en", "Players"), ("ko", "플레이어")):
            with Install() as inst:
                players_with_plays(admin.core.DB, 30, lambda g: g % 4)
                inst.client.set_cookie("opendmtq_lang", lang)
                inst.sign_in()
                looks = []

                def counted(self, key, *args, **kwargs):
                    # Every look at the language's cookie, whichever dictionary it is made on.
                    if key == admin.core.LANG_COOKIE:
                        looks.append(key)
                    return real_get(self, key, *args, **kwargs)

                with mock.patch.object(werkzeug.datastructures.ImmutableMultiDict, "get", counted):
                    page = inst.client.get("/opendmtq/admin/players").get_data(as_text=True)
                # The page in its language, its hundreds of words from one look.
                self.assertIn(word, page, lang)
                self.assertEqual(len(looks), 1, lang)

    def test_the_api_speaks_english_whatever_the_cookie(self):
        with Install() as inst:
            players_with_plays(admin.core.DB, 3)
            with admin.app.test_request_context("/opendmtq/api/players", headers={"Cookie": "opendmtq_lang=ko"}):
                self.assertEqual(admin.core.lang(), "en")
            with admin.app.test_request_context("/opendmtq/admin/players", headers={"Cookie": "opendmtq_lang=ko"}):
                self.assertEqual(admin.core.lang(), "ko")


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class DayCellsTest(unittest.TestCase):
    """The Players page's cells of each player's last days: a day's words made once for each count on that day, a run of
    counts once, and every row's cells as they were made row by row."""

    def test_many_players_with_the_same_days_ask_for_each_days_words_once(self):
        with Install() as inst:
            # Forty players who have not played lately: one run of counts, all of them nought.
            players_with_plays(admin.core.DB, 40)
            inst.sign_in()
            said = []
            real_tp = players.tp

            def counted(key, **values):
                if key == "players.day_tip":
                    said.append(values["day"])
                return real_tp(key, **values)

            with mock.patch.object(players, "tp", counted):
                page = inst.client.get("/opendmtq/admin/players").get_data(as_text=True)
            self.assertIn('class="daycells"', page)
            # Fourteen days, each said once, not once a player.
            self.assertEqual(len(said), 14)
            self.assertEqual(len(set(said)), 14)

    def test_each_rows_cells_are_the_ones_made_row_by_row(self):
        with Install() as inst:
            inst.sign_in()
            for lang in ("en", "ko"):
                with admin.app.test_request_context("/opendmtq/admin/players", headers={"Cookie": f"opendmtq_lang={lang}"}):
                    cells = players.day_cells(7)
                    today = datetime.date.today()
                    for counts in ([0] * 14, [1] + [0] * 13, [0, 3, 0, 7, 1, 0, 0, 0, 2, 0, 0, 0, 0, 5], [1] + [0] * 13):
                        # As the page made them before: each cell's words asked for row by row, day by day.
                        tips = [admin.core.tp("players.day_tip", day=(today - datetime.timedelta(days=len(counts) - 1 - i)).strftime("%m-%d"), n=n)
                                for i, n in enumerate(counts)]
                        self.assertEqual(str(cells(counts)), str(charts.days(counts, 7, tips, admin.core.tp("players.days_label"))), (lang, counts))
