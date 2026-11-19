"""Tests for the Notices page's notice on the site (admin/notice.py): how it is kept and the card's form, and the Notices
page with its cards. What the site shows of it is in tests/ui/audit.js (the notice stage).

Flask is installed in the tools image only; outside it these tests are skipped (CI runs them there).
"""

import datetime
import json
import os
import re
import time
import unittest
from unittest import mock

from tests.test_admin import HAVE_FLASK, Install

if HAVE_FLASK:
    from opendmtq_tools import admin


def page_csrf(inst):
    """The Notices page's form token, signed in."""
    inst.sign_in()
    page = inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', page).group(1)


def ahead(days):
    """A moment this many days from now, to the minute, in the server's own time: as the card's field holds it
    (YYYY-MM-DDTHH:MM) and as the card says it (YYYY-MM-DD HH:MM)."""
    at = datetime.datetime.now().replace(second=0, microsecond=0) + datetime.timedelta(days=days)
    return at.strftime("%Y-%m-%dT%H:%M"), at.strftime("%Y-%m-%d %H:%M")


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class KeptTest(unittest.TestCase):
    """ADM-127: how the notice is kept beside the database, its words one line, its end, what is refused."""

    def test_kept_as_one_line_beside_the_database_whole(self):
        with Install() as inst:
            kept = admin.notice.put("  Open late tonight.\r\n\r\n New songs\ton Friday.  ", None, "admin")
            self.assertEqual(kept["text"], "Open late tonight. New songs on Friday.")
            with open(inst.path("state/notice.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"text": "Open late tonight. New songs on Friday.", "until": None, "at": kept["at"], "by": "admin"})
            # Moved into place whole: nothing half written is left beside it.
            self.assertFalse(os.path.exists(inst.path("state/notice.json.new")))
            self.assertTrue(admin.notice.shown())

    def test_korean_and_emoji_are_text_and_200_characters_the_most(self):
        with Install():
            self.assertEqual(admin.notice.put("오늘 밤에는 새벽 1시까지 서버를 엽니다 🎶")["text"], "오늘 밤에는 새벽 1시까지 서버를 엽니다 🎶")
            self.assertEqual(len(admin.notice.put("가" * 200)["text"]), 200)
            with self.assertRaises(admin.core.Refused) as e:
                admin.notice.put("가" * 201)
            self.assertEqual(e.exception.code, "notice_too_long")

    def test_a_character_that_turns_the_page_around_or_is_no_text_is_refused(self):
        with Install() as inst:
            # A right-to-left override, an isolate, a right-to-left mark, a bell and a C1 control (a line break of either
            # kind, the C1 one too, is a space first).
            for text in ("Open \u202elate", "Open \u2067late", "Open\u200f late", "Open \x07late", "Open \x9blate"):
                with self.subTest(text=repr(text)):
                    with self.assertRaises(admin.core.Refused) as e:
                        admin.notice.put(text)
                    self.assertEqual(e.exception.code, "notice_not_text")
            # Nothing was kept.
            self.assertFalse(os.path.exists(inst.path("state/notice.json")))

    def test_emoji_made_with_joiners_are_text(self):
        # A family made with zero-width joiners, a flag, a skin tone and a variation selector, and a zero-width space: all
        # of them text, as a phone's keyboard types them.
        with Install():
            for text in ("Family night \U0001F468\u200D\U0001F469\u200D\U0001F467", "\U0001F1F0\U0001F1F7 \U0001F44D\U0001F3FD \u2764\uFE0F",
                         "Open\u200b late"):
                with self.subTest(text=repr(text)):
                    self.assertEqual(admin.notice.put(text)["text"], text)

    def test_nothing_to_show_and_an_end_that_has_come_or_is_too_far_are_refused(self):
        with Install() as inst:
            far = int(time.time()) + 11 * 365 * 86400
            for text, until, code in (("", None, "notice_empty"), ("  \n ", None, "notice_empty"), ("Late.", int(time.time()) - 1, "notice_end_past"),
                                      ("Late.", far, "notice_end_far"), ("Late.", 300000000000, "notice_end_far")):
                with self.subTest(code=code, until=until):
                    with self.assertRaises(admin.core.Refused) as e:
                        admin.notice.put(text, until)
                    self.assertEqual(e.exception.code, code)
            # Refused before anything was written: no notice is up, and the page still draws.
            self.assertFalse(os.path.exists(inst.path("state/notice.json")))
            inst.sign_in()
            self.assertEqual(inst.client.get("/opendmtq/admin/maintenance").status_code, 200)

    def test_an_end_its_clock_cannot_write_is_no_reason_for_the_page_to_fail(self):
        # A file edited by hand with an end past the year 9999: the card draws, its end said as none.
        with Install() as inst:
            inst.write("state/notice.json", json.dumps({"text": "Up.", "until": 300000000000, "at": 1, "by": "admin"}))
            inst.sign_in()
            r = inst.client.get("/opendmtq/admin/maintenance")
            self.assertEqual(r.status_code, 200)
            self.assertIn("Shown on the site", r.get_data(as_text=True))

    def test_it_ends_by_itself_at_its_end(self):
        with Install():
            kept = admin.notice.put("Until nine.", int(time.time()) + 60)
            self.assertTrue(admin.notice.shown(kept))
            self.assertFalse(admin.notice.shown(kept, now=kept["until"]))
            # Its end passed: still kept (its words stay in the card's field), no longer up.
            with mock.patch.object(admin.notice.time, "time", lambda: kept["until"] + 1):
                self.assertFalse(admin.notice.shown())
                self.assertEqual(admin.notice.view()["text"], "Until nine.")

    def test_taken_down_and_none_to_take_down(self):
        with Install() as inst:
            admin.notice.put("Up.")
            self.assertEqual(admin.notice.clear()["text"], "Up.")
            self.assertFalse(os.path.exists(inst.path("state/notice.json")))
            self.assertIsNone(admin.notice.clear())

    def test_a_damaged_file_is_no_notice(self):
        with Install() as inst:
            for raw in ("{", "[]", '{"text": 5}', '{"text": ""}'):
                inst.write("state/notice.json", raw)
                self.assertIsNone(admin.notice.read(), raw)
            # An end that is no whole number is no end.
            inst.write("state/notice.json", '{"text": "Up.", "until": "soon"}')
            self.assertEqual(admin.notice.read()["until"], None)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class CardTest(unittest.TestCase):
    """ADM-128: the Notices page's notice card and its form; ADM-129: the page's places in order, one main button."""

    def test_the_page_is_called_notices_and_has_the_cards_in_order(self):
        with Install() as inst:
            inst.sign_in()
            page = inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True)
            self.assertIn("<title>Notices · ", page)
            self.assertIn('>Notices</a>', page)
            self.assertLess(page.index('id="notice"'), page.index('id="maintenance"'))
            # One main button: the maintenance card's.
            self.assertEqual(page.count("btn-primary"), 1)
            self.assertIn("No notice", page)

    def test_show_change_and_take_down_from_the_card(self):
        with Install() as inst:
            csrf = page_csrf(inst)
            r = inst.client.post("/opendmtq/admin/notice", data={"csrf": csrf, "action": "show", "text": "Open late.", "until": ""})
            self.assertEqual((r.status_code, r.headers["Location"]), (302, "/opendmtq/admin/maintenance#notice"))
            page = inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True)
            self.assertIn("Notice up: everyone signed in sees it at the top of every page.", page)
            self.assertIn("Shown on the site", page)
            self.assertIn('value="Open late."', page)
            # With an end, in the server's own time: said on the card with its zone, kept as the moment.
            field, words = ahead(400)
            r = inst.client.post("/opendmtq/admin/notice", data={"csrf": csrf, "action": "show", "text": "Open later.", "until": field})
            self.assertEqual(r.status_code, 302)
            page = inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True)
            self.assertIn("Notice updated.", page)
            self.assertIn(f"Shown on the site until {words} {admin.notice.zone()}", page)
            self.assertIn(f'value="{field}"', page)
            self.assertEqual(admin.notice.read()["by"], "admin")
            # Taken down, needing no words in the field.
            r = inst.client.post("/opendmtq/admin/notice", data={"csrf": csrf, "action": "clear", "text": ""})
            self.assertEqual(r.status_code, 302)
            page = inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True)
            self.assertIn("Notice taken down.", page)
            self.assertIsNone(admin.notice.read())
            # Pressed again from a page left open: nothing to take down, said so.
            inst.client.post("/opendmtq/admin/notice", data={"csrf": csrf, "action": "clear"})
            self.assertIn("There is no notice up.", inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True))

    def test_a_refused_notice_comes_back_to_the_card_with_its_words_and_why(self):
        # Back to the Notices page by a redirect, as every answer of the card's form (a form sent in place must land on the
        # page it was sent from, admin.js), with why and what was typed in the fields, once.
        with Install() as inst:
            csrf = page_csrf(inst)
            field, _ = ahead(30)
            r = inst.client.post("/opendmtq/admin/notice", data={"csrf": csrf, "action": "show", "text": "y" * 201, "until": field})
            self.assertEqual((r.status_code, r.headers["Location"]), (302, "/opendmtq/admin/maintenance#notice"))
            page = inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True)
            self.assertIn("The notice is longer than 200 characters.", page)
            self.assertIn('value="' + "y" * 201 + '"', page)
            self.assertIn(f'value="{field}"', page)
            # The other cards drawn whole beside it.
            self.assertIn('id="maintenance"', page)
            # Once: the page opened again has the fields as they are kept (empty), not what was typed.
            self.assertNotIn("y" * 201, inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True))
            # An end that is no date, and one that has passed: each said on the card, nothing kept.
            for typed, words in (("next week", "That is not a date and a time."), (ahead(-1)[0], "That moment has passed already.")):
                r = inst.client.post("/opendmtq/admin/notice", data={"csrf": csrf, "action": "show", "text": "Late.", "until": typed})
                self.assertEqual(r.status_code, 302)
                self.assertIn(words, inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True))
            self.assertIsNone(admin.notice.read())

    def test_the_card_names_the_servers_time_zone(self):
        with Install() as inst:
            inst.sign_in()
            with mock.patch.object(admin.notice, "zone", lambda: "KST"):
                admin.notice.put("Until nine.", int(time.time()) + 3600)
                page = inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True)
            self.assertIn("Until (optional, KST)", page)
            self.assertRegex(page, r"Shown on the site until \d{4}-\d\d-\d\d \d\d:\d\d KST")

    def test_in_korean_and_in_the_log_of_changes(self):
        with Install() as inst:
            csrf = page_csrf(inst)
            inst.client.set_cookie("opendmtq_lang", "ko")
            field, words = ahead(400)
            inst.client.post("/opendmtq/admin/notice", data={"csrf": csrf, "action": "show", "text": "늦게까지 엽니다.", "until": field})
            page = inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True)
            self.assertIn("<title>공지 · ", page)
            self.assertIn(f"{words} {admin.notice.zone()}까지 사이트에 보이는 중", page)
            inst.client.post("/opendmtq/admin/notice", data={"csrf": csrf, "action": "clear"})
            changes = inst.client.get("/opendmtq/admin/logs?tab=changes").get_data(as_text=True)
            self.assertIn("사이트 공지 올림", changes)
            self.assertIn("사이트 공지 내림", changes)
            # The end with it; never the words (the log of changes keeps no messages).
            self.assertIn(words, changes)
            self.assertNotIn("늦게까지 엽니다.", changes)

    def test_the_maintenance_card_still_works_beside_it(self):
        with Install() as inst:
            csrf = page_csrf(inst)
            r = inst.client.post("/opendmtq/admin/maintenance", data={"csrf": csrf, "action": "on", "message": "Back soon."})
            self.assertEqual((r.status_code, r.headers["Location"]), (302, "/opendmtq/admin/maintenance#maintenance"))
            self.assertEqual(admin.songs.maintenance(), (True, "Back soon."))
