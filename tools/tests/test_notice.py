"""Tests for the Notices page's notice on the site (admin/notice.py): how it is kept and the card's form, and the Notices
page with its cards. What the game reads of it is in tests/game/protocol.py, what the site shows in tests/ui/audit.js.

Flask is installed in the tools image only; outside it these tests are skipped (CI runs them there).
"""

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
            for text in ("Open ‮late", "Open​ late", "Open \x07late"):
                with self.subTest(text=repr(text)):
                    with self.assertRaises(admin.core.Refused) as e:
                        admin.notice.put(text)
                    self.assertEqual(e.exception.code, "notice_not_text")
            # Nothing was kept.
            self.assertFalse(os.path.exists(inst.path("state/notice.json")))

    def test_nothing_to_show_and_an_end_that_has_come_are_refused(self):
        with Install():
            for text, until, code in (("", None, "notice_empty"), ("  \n ", None, "notice_empty"), ("Late.", int(time.time()) - 1, "notice_end_past")):
                with self.assertRaises(admin.core.Refused) as e:
                    admin.notice.put(text, until)
                self.assertEqual(e.exception.code, code)

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
    """ADM-128: the Notices page's notice card and its form; the page's three places in order, one main button."""

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
            # With an end, in the server's own time: said on the card, kept as the moment.
            r = inst.client.post("/opendmtq/admin/notice", data={"csrf": csrf, "action": "show", "text": "Open later.", "until": "2099-12-31T21:30"})
            self.assertEqual(r.status_code, 302)
            page = inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True)
            self.assertIn("Notice updated.", page)
            self.assertIn("Shown on the site until 2099-12-31 21:30", page)
            self.assertIn('value="2099-12-31T21:30"', page)
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

    def test_a_refused_notice_comes_back_in_its_field_with_why(self):
        with Install() as inst:
            csrf = page_csrf(inst)
            r = inst.client.post("/opendmtq/admin/notice", data={"csrf": csrf, "action": "show", "text": "y" * 201, "until": "2099-01-01T00:00"})
            page = r.get_data(as_text=True)
            self.assertEqual(r.status_code, 400)
            self.assertIn("The notice is longer than 200 characters.", page)
            self.assertIn('value="' + "y" * 201 + '"', page)
            self.assertIn('value="2099-01-01T00:00"', page)
            # The other cards drawn whole beside it.
            self.assertIn('id="maintenance"', page)
            r = inst.client.post("/opendmtq/admin/notice", data={"csrf": csrf, "action": "show", "text": "Late.", "until": "next week"})
            self.assertIn("That is not a date and a time.", r.get_data(as_text=True))
            self.assertIsNone(admin.notice.read())

    def test_in_korean_and_in_the_log_of_changes(self):
        with Install() as inst:
            csrf = page_csrf(inst)
            inst.client.set_cookie("opendmtq_lang", "ko")
            inst.client.post("/opendmtq/admin/notice", data={"csrf": csrf, "action": "show", "text": "늦게까지 엽니다.", "until": "2099-12-31T21:30"})
            page = inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True)
            self.assertIn("<title>알림 · ", page)
            self.assertIn("2099-12-31 21:30까지 사이트에 보이는 중", page)
            inst.client.post("/opendmtq/admin/notice", data={"csrf": csrf, "action": "clear"})
            changes = inst.client.get("/opendmtq/admin/logs?tab=changes").get_data(as_text=True)
            self.assertIn("사이트 공지 올림", changes)
            self.assertIn("사이트 공지 내림", changes)
            # The end with it; never the words (the log of changes keeps no messages).
            self.assertIn("2099-12-31 21:30", changes)
            self.assertNotIn("늦게까지 엽니다.", changes)

    def test_the_maintenance_card_still_works_beside_it(self):
        with Install() as inst:
            csrf = page_csrf(inst)
            r = inst.client.post("/opendmtq/admin/maintenance", data={"csrf": csrf, "action": "on", "message": "Back soon."})
            self.assertEqual((r.status_code, r.headers["Location"]), (302, "/opendmtq/admin/maintenance#maintenance"))
            self.assertEqual(admin.songs.maintenance(), (True, "Back soon."))
