"""Tests for the work the admin pages do for one request (admin/core.py, players.py, insights.py, game.py, api.py): the page's
language worked out once a request, the Players page's day cells made once for each run of counts, and a player's own page
and the API's answers about one player worked out for that player alone, the same as the whole list's row for them.

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
    from opendmtq_tools.admin import api, charts, players


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


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class OnePlayerTest(unittest.TestCase):
    """A player's own page and the API's answers about one player read that player's figures alone, and say the same as
    the whole list says of them."""

    def test_the_players_page_of_one_player_works_out_no_one_else(self):
        with Install() as inst:
            players_with_plays(admin.core.DB, 30, lambda g: g % 5)
            inst.sign_in()
            asked = []
            real_activity = admin.insights.player_activity

            def activity(con, *args, **kwargs):
                asked.append(kwargs.get("only"))
                return real_activity(con, *args, **kwargs)

            def everyone(con):
                raise AssertionError("every player's devices read for one player's page")

            with mock.patch.object(players, "players_seen", everyone), mock.patch.object(admin.insights, "player_activity", activity):
                r = inst.client.get("/opendmtq/admin/players/7")
                page = r.get_data(as_text=True)
                self.assertEqual(r.status_code, 200)
                self.assertIn("Player7", page)
                # The API's game state of one player and its row of the list, the same way.
                self.assertEqual(api.game_view(7)["player"], 7)
                self.assertEqual(api.one_player(7)["id"], 7)
            self.assertTrue(asked and all(only == 7 for only in asked), asked)

    def test_one_players_row_is_the_lists_row_for_them(self):
        with Install() as inst:
            players_with_plays(admin.core.DB, 12, lambda g: (g * 3) % 7)
            inst.sign_in()
            with admin.app.test_request_context("/opendmtq/api/players"):
                everyone = {v["id"]: v for v in api.player_views()}
                # Played or not, two phones, broadcasting: each one's answer alone is its row of the whole list.
                for guid in everyone:
                    self.assertEqual(api.one_player(guid), everyone[guid], guid)
                rows, live, seen, activity, phones = players.player_rows()
                for guid in (1, 2, 3, 6):
                    one = players.player_rows(only=guid)
                    self.assertEqual([tuple(r) for r in one[0]], [tuple(r) for r in rows if r["id"] == guid])
                    self.assertEqual(one[2], {guid: seen[guid]})
                    self.assertEqual(one[3][guid], activity[guid])
                    self.assertEqual(one[4], {guid: phones[guid]})
                # A number nobody has: no row, as the list has none.
                self.assertEqual(players.player_rows(only=99)[0], [])
