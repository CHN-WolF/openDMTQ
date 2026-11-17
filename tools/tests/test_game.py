"""Tests for a player's game state on the admin pages (admin/game.py, templates/player.html, the Players page's Game card): the
player's page in both languages, each of its forms and its refusals, what the log of changes keeps of each change and the page
lists, the bans on the Players page, the server's game settings, and what a player's deletion takes with it. The API's routes
for the same are in test_api.py; what the game server makes of these tables, in tests/game/state.php.

Flask is installed in the tools image only; outside it these tests are skipped (CI runs them there)."""

import json
import os
import re
import sqlite3
import time
import unittest

from tests.test_admin import HAVE_FLASK, Install, member_rows, old_game_database

if HAVE_FLASK:
    from opendmtq_tools import admin

# The client's tables as the tools turn them into catalog.json (songs.py): two characters everyone has, a note nobody has at
# first, a skin everyone has.
CATALOG = {"items": [30001, 30002, 100001], "point_charts": [], "unlock_product": None, "products": {},
           "gear": {"C": [[30001, "Made Partner"], [30002, "Second Partner"]], "N": [[90001, "Made Note"]], "K": [[100001, "Made Skin"]]}}


def changes(inst):
    """The lines of the log of changes, oldest first, as the admin pages wrote them."""
    with open(inst.path("state/changes.log"), encoding="utf-8") as f:
        return [json.loads(line) for line in f]


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class PlayerGamePageTest(unittest.TestCase):
    """The player's own page and its forms, as a browser sends them (no script: each answers with the page again)."""

    def server(self, inst, lang="en"):
        """Three players (7 Sena, 8 Yuna, 9 nameless), the catalog, signed in in lang: the form token and Sena's seen."""
        old_game_database(admin.core.DB, [])
        member_rows(admin.core.DB, [(7, "Sena", "phone-7"), (8, "Yuna", "phone-8"), (9, " ", "phone-9")])
        inst.write("custom/catalog.json", json.dumps(CATALOG))
        inst.client.set_cookie("opendmtq_lang", lang)
        inst.sign_in()
        page = inst.client.get("/opendmtq/admin/players/7").get_data(as_text=True)
        with sqlite3.connect(admin.core.DB) as con:
            seen = admin.players.player_seen(con, 7)
        return re.search(r'name="csrf" value="([^"]*)"', page).group(1), seen

    def send(self, inst, csrf, seen, **fields):
        """One form of the page, sent as a browser sends it, and the page it comes back to."""
        r = inst.client.post(f"/opendmtq/admin/players/7/game?seen={seen}", data={"csrf": csrf, **fields})
        self.assertEqual(r.status_code, 302)
        return inst.client.get(r.headers["Location"]).get_data(as_text=True)

    def row(self, pid=7):
        with sqlite3.connect(admin.core.DB) as con:
            return con.execute("SELECT mpoint, qpoint, exp, unlimited FROM PlayerState WHERE guid = ?", (pid,)).fetchone()

    def test_the_page_shows_what_the_game_shows_in_both_languages(self):
        for lang, words in (("en", ("Currency", "MAX POINT", "Q POINT", "Level", "Items", "Ban", "Purchases", "Changes", "Characters")),
                            ("ko", ("재화", "MAX 포인트", "Q 포인트", "레벨", "아이템", "이용 정지", "구매 내역", "변경 기록", "캐릭터 파트너"))):
            with Install() as inst:
                self.server(inst, lang)
                page = inst.client.get("/opendmtq/admin/players/7").get_data(as_text=True)
                for word in words:
                    self.assertIn(word, page, (lang, word))
                # What a new player starts with: 999,999 of each, level 99 with a full gauge.
                self.assertIn('id="purse-max">999,999<', page)
                self.assertIn('aria-label="Lv.99"', page)
                self.assertIn('style="width: 100.0%"', page)
                # The items kind by kind, with how many the player has of each.
                self.assertIn("2 of 2" if lang == "en" else "2개 중 2개", page)

    def test_a_player_nobody_has_goes_back_to_the_list_with_why(self):
        with Install() as inst:
            self.server(inst)
            r = inst.client.get("/opendmtq/admin/players/99")
            self.assertEqual(r.status_code, 302)
            self.assertIn("Player 99 is no longer there", inst.client.get(r.headers["Location"]).get_data(as_text=True))

    def test_currency_set_added_and_taken_within_what_the_game_shows(self):
        with Install() as inst:
            csrf, seen = self.server(inst)
            page = self.send(inst, csrf, seen, action="currency", currency="max", how="set", amount="1,234,567")
            self.assertIn("MAX POINT of Sena: 1,234,567.", page)
            self.send(inst, csrf, seen, action="currency", currency="q", how="take", amount="99")
            self.assertEqual(self.row(), (1234567, 999900, 130408, 0))
            # Past what the top bar shows, more than they hold, not a number: refused, in words, nothing changed.
            for amount, how, words in (("99999999", "add", "and the game shows 99,999,999 at most"), ("1000000", "take", "They hold 999,900"),
                                       ("lots", "set", "Type a whole number from 0 to 99,999,999")):
                page = self.send(inst, csrf, seen, action="currency", currency="q", how=how, amount=amount)
                self.assertIn(words, page)
            self.assertEqual(self.row(), (1234567, 999900, 130408, 0))

    def test_level_and_exp_agree_as_the_games_table_has_them(self):
        with Install() as inst:
            csrf, seen = self.server(inst)
            self.send(inst, csrf, seen, action="level", level="12")
            self.assertEqual(self.row()[2], 644)
            page = self.send(inst, csrf, seen, action="exp", exp="5669")
            # Level 37 runs from 5,493 to 5,845: the gauge half way, as the game's own draws it.
            self.assertIn("Sena is Lv.37 with EXP 5,669.", page)
            self.assertIn('style="width: 50.0%"', page)
            for field, value, words in (("level", "100", "A level is from 1 to 99."), ("exp", "130409", "EXP is from 0 to 130,408.")):
                self.assertIn(words, self.send(inst, csrf, seen, action=field, **{field: value}))
            self.assertEqual(self.row()[2], 5669)

    def test_unlimited_shows_the_figure_of_no_end_and_keeps_the_balance(self):
        with Install() as inst:
            csrf, seen = self.server(inst)
            page = self.send(inst, csrf, seen, action="unlimited-on")
            self.assertIn('id="purse-max">99,999,999<', page)
            self.assertIn("Own balance 999,999", page)
            self.assertIn("Unlimited currency", page)
            page = self.send(inst, csrf, seen, action="unlimited-off")
            self.assertIn('id="purse-max">999,999<', page)
            self.assertEqual(self.row()[3], 0)

    def test_an_item_given_and_taken_and_unequipped_when_taken(self):
        with Install() as inst:
            csrf, seen = self.server(inst)
            with sqlite3.connect(admin.core.DB) as con:
                con.execute("UPDATE Member SET slot_item1 = 30001 WHERE id = 7")
            r = inst.client.post(f"/opendmtq/admin/players/7/game?seen={seen}&item=90001", data={"csrf": csrf, "action": "give"})
            self.assertIn("Made Note given to Sena.", inst.client.get(r.headers["Location"]).get_data(as_text=True))
            r = inst.client.post(f"/opendmtq/admin/players/7/game?seen={seen}&item=30001", data={"csrf": csrf, "action": "take"})
            self.assertIn("Made Partner taken from Sena.", inst.client.get(r.headers["Location"]).get_data(as_text=True))
            with sqlite3.connect(admin.core.DB) as con:
                self.assertEqual(con.execute("SELECT item_id, owned, how FROM PlayerItem ORDER BY item_id").fetchall(),
                                 [(30001, 0, "taken"), (90001, 1, "given")])
                # Out of its place on the top bar: the game shows its own default there.
                self.assertIsNone(con.execute("SELECT slot_item1 FROM Member WHERE id = 7").fetchone()[0])
            # An item the catalog does not have: refused.
            r = inst.client.post(f"/opendmtq/admin/players/7/game?seen={seen}&item=424242", data={"csrf": csrf, "action": "give"})
            self.assertIn("There is no item 424242 to give or take.", inst.client.get(r.headers["Location"]).get_data(as_text=True))

    def test_a_ban_with_its_reason_and_end_then_lifted_from_the_players_page(self):
        with Install() as inst:
            csrf, seen = self.server(inst)
            # Without a reason: refused, as the game shows it to the player.
            self.assertIn("Write the reason", self.send(inst, csrf, seen, action="ban", reason="  ", days="7"))
            page = self.send(inst, csrf, seen, action="ban", reason="Made-up\nscores", days="7")
            self.assertIn("Sena banned until", page)
            self.assertIn("Made-up scores", page)
            with sqlite3.connect(admin.core.DB) as con:
                reason, since, until, by = con.execute("SELECT reason, since, until, by FROM PlayerBan WHERE guid = 7").fetchone()
            self.assertEqual((reason, until - since, by), ("Made-up scores", 7 * 86400, "admin"))
            # The Players page: the mark after the name, the list of bans with the reason and the way to lift each.
            players = inst.client.get("/opendmtq/admin/players").get_data(as_text=True)
            self.assertIn('<span class="name-chip">Banned</span>', players)
            self.assertIn("Banned players", players)
            r = inst.client.post(f"/opendmtq/admin/players/7/game?seen={seen}", data={"csrf": csrf, "action": "unban", "back": "players"})
            self.assertEqual(r.headers["Location"], "/opendmtq/admin/players")
            self.assertNotIn("Banned players", inst.client.get("/opendmtq/admin/players").get_data(as_text=True))

    def test_every_change_is_in_the_log_of_changes_with_before_and_after_and_on_the_page(self):
        with Install() as inst:
            csrf, seen = self.server(inst)
            self.send(inst, csrf, seen, action="currency", currency="max", how="set", amount="5")
            self.send(inst, csrf, seen, action="level", level="2")
            lines = changes(inst)
            game = [line for line in lines if line["what"].startswith("player_game:")]
            self.assertEqual([(g["what"], g["player"], g["before"], g["after"], g["who"]) for g in game],
                             [("player_game:max", 7, 999999, 5, "admin"), ("player_game:level", 7, [99, 130408], [2, 10], "admin")])
            self.assertEqual(game[0]["target"], "Sena: 999,999 → 5")
            # The page lists them, newest first, in its words, with who made each.
            page = inst.client.get("/opendmtq/admin/players/7").get_data(as_text=True)
            listed = re.findall(r'<span class="ch-what">([^<]*)</span><span class="ch-target">([^<]*)</span><span class="ch-who">([^<]*)</span>', page)
            self.assertEqual(listed, [("Changed a level", "Sena: Lv.99 (130,408) → Lv.2 (10)", "admin"),
                                      ("Changed MAX POINT", "Sena: 999,999 → 5", "admin")])
            # Another player's page lists none of Sena's.
            self.assertIn("Nothing changed here yet.", inst.client.get("/opendmtq/admin/players/8").get_data(as_text=True))

    def test_a_number_that_went_to_someone_else_changes_nothing(self):
        with Install() as inst:
            csrf, seen = self.server(inst)
            page = self.send(inst, csrf, "0123456789abcdef", action="currency", currency="max", how="set", amount="5")
            self.assertIn("That page was out of date", page)
            self.assertIsNone(self.row())

    def test_the_game_reset_makes_a_backup_and_leaves_the_scores_and_the_ban(self):
        with Install() as inst:
            csrf, seen = self.server(inst)
            self.send(inst, csrf, seen, action="currency", currency="max", how="set", amount="5")
            self.send(inst, csrf, seen, action="ban", reason="Rest", days="0")
            page = self.send(inst, csrf, seen, action="reset")
            self.assertIn("Game state of Sena reset.", page)
            self.assertTrue(any("-before-player-game-reset" in name for name in os.listdir(inst.path("backups"))))
            self.assertIsNone(self.row())
            with sqlite3.connect(admin.core.DB) as con:
                self.assertEqual(con.execute("SELECT reason, until FROM PlayerBan").fetchall(), [("Rest", None)])

    def test_renaming_on_the_page_comes_back_to_the_page(self):
        with Install() as inst:
            csrf, seen = self.server(inst)
            r = inst.client.post(f"/opendmtq/admin/players/7?seen={seen}", data={"csrf": csrf, "action": "rename", "name": "Riku", "back": "player"})
            self.assertEqual(r.headers["Location"], "/opendmtq/admin/players/7")
            lines = changes(inst)
            self.assertEqual([(line["player"], line["before"], line["after"]) for line in lines if line["what"] == "player_action:rename"], [(7, "Sena", "Riku")])

    def test_a_deleted_player_takes_their_game_state_and_ban_with_them(self):
        with Install() as inst:
            csrf, seen = self.server(inst)
            self.send(inst, csrf, seen, action="currency", currency="max", how="set", amount="5")
            self.send(inst, csrf, seen, action="ban", reason="Gone", days="1")
            inst.client.post(f"/opendmtq/admin/players/7?seen={seen}", data={"csrf": csrf, "action": "delete"})
            with sqlite3.connect(admin.core.DB) as con:
                for table in ("PlayerState", "PlayerItem", "PlayerBan", "PlayerPurchase"):
                    self.assertEqual(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class GameSettingsTest(unittest.TestCase):
    """The Players page's Game card: unlimited currency for every player, and what a new player starts with."""

    def test_new_start_values_reach_new_players_alone(self):
        with Install() as inst:
            old_game_database(admin.core.DB, [])
            member_rows(admin.core.DB, [(7, "Sena", "phone-7")])
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/players").get_data(as_text=True)
            csrf = re.search(r'name="csrf" value="([^"]*)"', page).group(1)
            r = inst.client.post("/opendmtq/admin/players/game", data={"csrf": csrf, "action": "start", "start_mpoint": "0",
                                                                         "start_qpoint": "100", "start_level": "1"})
            self.assertIn("New players start with 0 MAX POINT, 100 Q POINT and Lv.1.", inst.client.get(r.headers["Location"]).get_data(as_text=True))
            with sqlite3.connect(admin.core.DB) as con:
                con.row_factory = sqlite3.Row
                # Sena, there before, keeps what she had; a player who comes after starts with the new values.
                self.assertEqual(admin.game.state(con, 7)["mpoint"], 999999)
                self.assertEqual((admin.game.state(con, 50)["mpoint"], admin.game.state(con, 50)["level"]), (0, 1))
            # A value outside its range: refused in the words the player's page gives the same field, nothing changed.
            r = inst.client.post("/opendmtq/admin/players/game", data={"csrf": csrf, "action": "start", "start_level": "0"})
            self.assertIn("A level is from 1 to 99.", inst.client.get(r.headers["Location"]).get_data(as_text=True))
            r = inst.client.post("/opendmtq/admin/players/game", data={"csrf": csrf, "action": "start", "start_qpoint": "100000000"})
            self.assertIn("Type a whole number from 0 to 99,999,999.", inst.client.get(r.headers["Location"]).get_data(as_text=True))
            with sqlite3.connect(admin.core.DB) as con:
                self.assertEqual(admin.game.settings(con)["start_qpoint"], 100)

    def test_unlimited_for_every_player(self):
        with Install() as inst:
            old_game_database(admin.core.DB, [])
            member_rows(admin.core.DB, [(7, "Sena", "phone-7")])
            inst.sign_in()
            csrf = re.search(r'name="csrf" value="([^"]*)"', inst.client.get("/opendmtq/admin/players").get_data(as_text=True)).group(1)
            r = inst.client.post("/opendmtq/admin/players/game", data={"csrf": csrf, "action": "unlimited-on"})
            self.assertIn("Unlimited currency on for every player.", inst.client.get(r.headers["Location"]).get_data(as_text=True))
            page = inst.client.get("/opendmtq/admin/players/7").get_data(as_text=True)
            # The player's page says so beside their own switch, and shows the figure of no end.
            self.assertIn("On for every player", page)
            self.assertIn('id="purse-max">99,999,999<', page)


if __name__ == "__main__":
    unittest.main()
