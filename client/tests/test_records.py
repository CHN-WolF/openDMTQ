"""My records on PLAY and My page on the site: the one-time link the server makes for the launcher's sign-in, and the
records it lists for the account's player (server.py, actions.py), against the stand-in site."""

import time
from unittest import mock

from opendmtq_client import actions, i18n
from opendmtq_client import server as srv
from opendmtq_client import state as st
from tests import stub
from tests.base import Folder


class Records(Folder):
    def setUp(self):
        super().setUp()
        self.site = stub.Site().start()
        self.state = st.LauncherState()
        self.state.add_server(self.site.url, "Stand-in")
        actions.sign_in(self.state, stub.ACCOUNT, stub.PASSWORD)

    def tearDown(self):
        self.site.stop()
        super().tearDown()

    def test_my_page_is_a_one_time_link_on_the_server(self):
        url = actions.my_page(self.state)
        self.assertEqual(url, self.site.url + "/opendmtq/login.php?once=" + stub.LINK_TOKEN)
        # Asked for with the launcher's sign-in, as a POST: a link is a sign-in.
        self.assertIn(("POST", "/opendmtq/client.php?link", self.site.cookie), self.site.requests)

    def test_a_server_from_before_links_opens_its_site(self):
        self.site.links = False
        self.assertEqual(actions.my_page(self.state), self.site.url + "/opendmtq/")
        with self.assertRaises(srv.ServerError) as said:
            srv.sign_in_link(self.site.url, self.site.cookie)
        self.assertEqual(said.exception.key, "error.link.none")

    def test_a_link_that_leads_elsewhere_is_never_opened(self):
        # Only a path on the server's own site, with a token of the site's shape.
        for url in ("https://elsewhere.example/login.php?once=" + stub.LINK_TOKEN, "//elsewhere.example/x",
                    "/opendmtq/login.php?once=short", "/opendmtq/player.php?id=7"):
            with mock.patch.object(srv, "_call", lambda *a, url=url, **k: (200, {"url": url}, {})):
                with self.assertRaises(srv.ServerError, msg=url):
                    srv.sign_in_link(self.site.url, self.site.cookie)

    def test_a_sign_in_that_ended_is_forgotten(self):
        self.site.signed_cookies.clear()
        for ask in (actions.my_page, actions.records):
            self.state.server().update(cookie=self.site.cookie, expires=1999999999)
            with self.assertRaises(srv.SignedOut):
                ask(self.state)
            self.assertFalse(self.state.signed_in())
            # The account's name stays, to fill the form in again.
            self.assertEqual(self.state.server()["account"], stub.ACCOUNT)

    def test_signed_out_nothing_is_asked(self):
        self.state.forget_sign_in()
        asked = len(self.site.requests)
        for ask in (actions.my_page, actions.records):
            with self.assertRaises(srv.SignedOut):
                ask(self.state)
        self.assertEqual(len(self.site.requests), asked)

    def test_the_records_as_the_play_page_shows_them(self):
        answer = actions.records(self.state)
        self.assertEqual(answer["player"], {"id": 7, "name": "SENA", "rank": 2})
        first = answer["recent"][0]
        self.assertEqual((first["title"], first["chart_name"], first["score"], first["keys"], first["rank"],
                          first["players"], first["new_record"]), ("Neon Rain", "3LINE Hard 9", 987654, True, 1, 4, True))
        self.assertEqual([r["score"] for r in answer["best"]], [987654, 954210, 812300])
        # A best older than the play log has no time.
        self.assertIsNone(answer["best"][2]["at"])

    def test_an_account_linked_to_no_player(self):
        self.site.records = {"account": stub.ACCOUNT, "player": None, "recent": [], "best": []}
        self.assertEqual(actions.records(self.state),
                         {"account": stub.ACCOUNT, "player": None, "recent": [], "best": []})

    def test_a_server_from_before_records_has_none(self):
        self.site.records = None
        self.assertIsNone(actions.records(self.state))

    def test_what_is_no_record_is_left_out(self):
        # The server's lists go on a page: only what is a record, its words as words.
        records = stub.made_up_records()
        records["recent"] = [{"score": "lots"}, "a row", None, {"score": 5, "title": 7, "keys": "yes", "rank": 0},
                             {"score": 1, "title": "x" * 500}]
        with mock.patch.object(srv, "_call", lambda *a, **k: (200, records, {})):
            answer = srv.records(self.site.url, self.site.cookie)
        self.assertEqual(len(answer["recent"]), 2)
        odd, long_title = answer["recent"]
        self.assertEqual((odd["title"], odd["keys"], odd["rank"]), (None, False, None))
        self.assertEqual(len(long_title["title"]), 200)

    def test_how_long_ago_in_both_languages(self):
        now = 1795400000
        for seconds, en, ko in ((10, "just now", "방금"), (300, "5 min ago", "5분 전"), (3 * 3600, "3 h ago", "3시간 전"),
                                (2 * 86400, "2 d ago", "2일 전"), (65 * 86400, "2 mo ago", "2개월 전")):
            said = i18n.ago(now - seconds, now=now)
            self.assertEqual((i18n.Words("en").say(said), i18n.Words("ko").say(said)), (en, ko))

    def test_a_chart_names_its_mode_as_the_launcher_does(self):
        # The site writes a chart "3LINE Hard 9"; PLAY's records say "3 LINE Hard 9", as How to play and Controls name a
        # mode (main showed both spellings on one page).
        from opendmtq_client import values
        self.assertEqual(values.chart_words("3LINE Hard 9"), "3 LINE Hard 9")
        self.assertEqual(values.chart_words("2LINE Normal 5"), values.mode("keys_2line") + " Normal 5")
        # Already spaced, or no mode at its start: as it is.
        self.assertEqual(values.chart_words("4 LINE Expert 12"), "4 LINE Expert 12")
        self.assertEqual(values.chart_words("Chart 7"), "Chart 7")

    def test_the_records_place_in_both_languages(self):
        self.assertEqual(i18n.Words("en")("play.records.place", n=2, all=5), "#2 of 5")
        self.assertEqual(i18n.Words("ko")("play.records.place", n=2, all=5), "5명 중 2위")
        # The stand-in's own times are made up from now, as a page shows them.
        self.assertLess(abs(stub.made_up_records(now=time.time())["recent"][0]["at"] - (time.time() - 300)), 5)
