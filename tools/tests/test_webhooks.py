"""Tests for the Discord and Slack webhooks (admin/webhooks.py): what an address may be and how it shows, the messages each
chat gets with nobody called by a name, what the loop tells of (a broadcast, a chart's #1, the month's #1, maintenance) and
what it leaves out, once only with two processes on one database, the retries, a restore, the card and the log of changes.

Every message goes to a stand-in chat on this machine's loopback (Chat below), never to Discord or Slack. Flask is installed
in the tools image only; outside it these tests are skipped (CI runs them there)."""

import http.server
import json
import multiprocessing
import os
import sqlite3
import threading
import time
import unittest
from unittest import mock

from tests.test_admin import HAVE_FLASK, HOST, Install, member_rows, old_game_database, page_token

if HAVE_FLASK:
    from opendmtq_tools import admin
    from opendmtq_tools.admin import webhooks

# The zero-width space that breaks a mention.
ZW = "​"


class Chat:
    """A stand-in chat on the loopback: takes every POST, keeps its body, and answers as told (answers: a list of
    (status, body, headers) to give in turn, the last one again and again; delay: seconds before each answer)."""

    def __init__(self, answers=((204, b"", {}),), delay=0.0):
        self.answers, self.delay, self.got = list(answers), delay, []
        self._lock = threading.Lock()
        chat = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                with chat._lock:
                    chat.got.append({"path": self.path, "body": json.loads(body or b"{}"), "agent": self.headers.get("User-Agent", "")})
                    status, text, headers = chat.answers[0] if len(chat.answers) == 1 else chat.answers.pop(0)
                time.sleep(chat.delay)
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(text)))
                self.end_headers()
                self.wfile.write(text)

            def log_message(self, *args):
                pass

        class Quiet(http.server.ThreadingHTTPServer):
            # A sender that gave up before the answer (a test of the time running out): nothing to say of it.
            def handle_error(self, request, client_address):
                pass

        self.server = Quiet(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def title_of(body):
    """A message's title, as Discord's embed or Slack's fallback text has it."""
    return body["embeds"][0]["title"] if "embeds" in body else body["text"].split(": ", 1)[0]


def songs_json(inst):
    """The imported songs: two, one with two charts; the second hidden by the owner later in some tests."""
    os.makedirs(inst.path("content"), exist_ok=True)
    inst.write("content/songs.json", json.dumps([
        {"song_id": 1, "name": "paperplanes", "full_name": "Paper Planes", "song_patterns": [
            {"pattern_id": 11, "line": 3, "signature": 1, "difficulty": 3}, {"pattern_id": 12, "line": 5, "signature": 2, "difficulty": 7}]},
        {"song_id": 2, "name": "neonrain", "full_name": "Neon Rain", "song_patterns": [{"pattern_id": 21, "line": 4, "signature": 3, "difficulty": 9}]}]))


class Server(Install):
    """A server with three players (Sena 7, Yuna 8, Riku 9), their best scores and plays, songs, and the database brought
    up to date; the stand-in chat beside it."""

    def __enter__(self):
        super().__enter__()
        # The stand-in chat is on this machine's loopback, which a real webhook may not be.
        self._loopback = mock.patch.object(webhooks, "LOOPBACK_OK", True)
        self._loopback.start()
        songs_json(self)
        self._content = mock.patch.object(admin.songs, "CONTENT", self.path("content"))
        self._content.start()
        db = admin.core.DB
        old_game_database(db, [(11, 7, 900000, "S", "Y", "N", 950), (12, 7, 800000, "A", "N", "N", 900)])
        member_rows(db, [(7, "Sena", "phone-a"), (8, "Yuna", "phone-b"), (9, "Riku", "phone-c")])
        con = sqlite3.connect(db)
        admin.backups.bring_schema_up_to_date(con)
        con.execute("INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at) VALUES (7, 11, 900000, 'S', 950, 1, ?)",
                    (int(time.time()) - 3600,))
        con.commit()
        con.close()
        self.chat = Chat()
        return self

    def __exit__(self, *exc):
        self.chat.close()
        self._content.stop()
        self._loopback.stop()
        return super().__exit__(*exc)

    def play(self, guid, pattern, score, judgement=900, at=None):
        """A play saved as the game server saves it: the log's row, and the best kept per player and chart."""
        at = int(time.time()) if at is None else at
        con = sqlite3.connect(admin.core.DB)
        best = con.execute("SELECT score FROM Play WHERE user_id = ? AND pattern_id = ?", (guid, pattern)).fetchone()
        record = best is None or score > best[0]
        con.execute("INSERT INTO PlayLog (user_id, pattern_id, score, grade, judgement, is_record, played_at) VALUES (?, ?, ?, 'A', ?, ?, ?)",
                    (guid, pattern, score, judgement, int(record), at))
        if best is None:
            con.execute("INSERT INTO Play (pattern_id, user_id, score, grade, isAllCombo, isPerfectPlay, judgement) VALUES (?, ?, ?, 'A', 'N', 'N', ?)",
                        (pattern, guid, score, judgement))
        elif record:
            con.execute("UPDATE Play SET score = ?, judgement = MAX(judgement, ?) WHERE user_id = ? AND pattern_id = ?", (score, judgement, guid, pattern))
        con.commit()
        con.close()

    def hook(self, events=None, language="en", path="/api/webhooks/1234/secret-part-9876"):
        """A webhook to the stand-in chat, as the card adds one."""
        with admin.app.test_request_context():
            return webhooks.add(self.chat.url + path, language, list(events or webhooks.EVENTS))

    def queued(self):
        """The messages queued, oldest first: (hook, kind, data, state)."""
        con = sqlite3.connect(admin.core.DB)
        try:
            return [(h, k, json.loads(e), s) for h, k, e, s in con.execute("SELECT hook, kind, event, state FROM WebhookMessage ORDER BY id")]
        finally:
            con.close()

    def on_air(self, guid, rec, on=True):
        """A player on air as the server keeps it: broadcasts on, their switch on, and their phone's upload fresh."""
        con = sqlite3.connect(admin.core.DB)
        admin.recordings.live_table(con)
        con.execute(admin.recordings.SETTING_TABLE)
        con.execute("INSERT OR REPLACE INTO LiveSetting (name, value) VALUES ('on', '1')")
        con.execute("INSERT OR REPLACE INTO LiveSwitch (guid, live) VALUES (?, 1)", (guid,))
        con.commit()
        con.close()
        folder = admin.recordings.live_folder(guid)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "stream.json"), "w", encoding="utf-8") as f:
            json.dump({"rec": rec, "updated": int(time.time()), "ended": not on}, f)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class AddressTest(unittest.TestCase):
    """What a webhook's address may be, its format by its host, and how the pages show it (ADM-120)."""

    def test_this_servers_own_and_link_local_addresses_are_no_chat(self):
        # A webhook to the server itself or to its network link's own addresses (a cloud's metadata) would let the test's
        # answers say what answers there: refused, by name and by number; a chat on the local network is one.
        with admin.app.test_request_context():
            for url in ("http://127.0.0.1:8080/hook", "http://localhost/hook", "http://chat.localhost/hook", "http://[::1]/hook",
                        "http://169.254.169.254/latest/meta-data", "http://0.0.0.0/hook", "http://[::ffff:127.0.0.1]/hook", "http://[fe80::1]/hook"):
                with self.assertRaises(webhooks.Refused, msg=url) as e:
                    webhooks.check_url(url)
                self.assertEqual((e.exception.code, e.exception.words), ("bad_url", admin.core.t("hook.local")), url)
            self.assertEqual(webhooks.check_url("http://192.168.1.20:8065/hooks/abc"), "http://192.168.1.20:8065/hooks/abc")
        # A name that leads to one of them is not sent to either: found out when a message would go.
        with mock.patch.object(webhooks.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            self.assertEqual(webhooks.post("https://chat.example/hook", {})["code"], "local")

    def test_an_address_of_a_webhook_is_taken_and_anything_else_refused(self):
        with admin.app.test_request_context(), mock.patch.object(webhooks, "LOOPBACK_OK", True):
            for url in ("https://discord.com/api/webhooks/1/abc", "http://127.0.0.1:8080/hook", "https://hooks.slack.com/services/T/B/x"):
                self.assertEqual(webhooks.check_url(f"  {url} "), url)
            for url in ("", "ftp://chat.example/hook", "javascript:alert(1)", "https://name:pw@chat.example/hook", "https://:pw@chat.example/x",
                        "https://chat.example/a b", "https://chat.example/a\nb", "https:///nohost", "https://chat.example:99999/x",
                        "https://chat.example/" + "x" * 1000, "discord.com/api/webhooks/1/abc"):
                with self.assertRaises(webhooks.Refused, msg=url) as e:
                    webhooks.check_url(url)
                self.assertEqual((e.exception.status, e.exception.code), (400, "bad_url"), url)

    def test_the_host_decides_the_format(self):
        for host in ("discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com", "DISCORD.COM"):
            self.assertEqual(webhooks.kind_of(f"https://{host}/api/webhooks/1/x"), "discord", host)
        for url in ("https://hooks.slack.com/services/T/B/x", "https://chat.example/hooks/abc", "https://discord.com.example/x"):
            self.assertEqual(webhooks.kind_of(url), "slack", url)

    def test_discords_own_endings(self):
        # Discord's webhook takes Slack's messages under /slack (and GitHub's under /github): the token before them stays
        # masked, and /slack gets Slack's format.
        url = "https://discord.com/api/webhooks/123456/TOKENsecretTOKEN/slack"
        self.assertEqual(webhooks.masked(url), "discord.com/api/webhooks/123456/••••OKEN/slack")
        self.assertEqual(webhooks.kind_of(url), "slack")
        self.assertEqual(webhooks.masked("https://discord.com/api/webhooks/123456/TOKENsecretTOKEN?thread_id=99"),
                         "discord.com/api/webhooks/123456/••••OKEN?••••d=99")
        with admin.app.test_request_context():
            with self.assertRaises(webhooks.Refused) as e:
                webhooks.check_url("https://discord.com/api/webhooks/123456/TOKENsecretTOKEN/github")
        self.assertEqual(e.exception.code, "bad_url")

    def test_another_chats_address_shows_only_its_first_part(self):
        # Where the secret is in another chat's address is not known: all of it past its first part is masked.
        self.assertEqual(webhooks.masked("https://chat.example/hooks/LONGSECRETVALUE/abc"), "chat.example/hooks/••••/abc")
        self.assertEqual(webhooks.masked("https://chat.example/LONGSECRETVALUE"), "chat.example/••••ALUE")
        for url in ("https://chat.example/hooks/LONGSECRETVALUE/abc", "https://chat.example/LONGSECRETVALUE"):
            self.assertNotIn("SECRET", webhooks.masked(url))

    def test_shown_masked_never_whole(self):
        cases = {"https://discord.com/api/webhooks/1234/secret-part-9876": "discord.com/api/webhooks/1234/••••9876",
                 "https://hooks.slack.com/services/T01/B02/xyzsecret5432": "hooks.slack.com/services/T01/B02/••••5432",
                 "http://127.0.0.1:8080/hook?token=abcdefgh": "127.0.0.1:8080/••••hook?••••efgh",
                 "https://chat.example": "chat.example"}
        for url, shown in cases.items():
            self.assertEqual(webhooks.masked(url), shown)
        self.assertNotIn("secret-part", webhooks.masked("https://discord.com/api/webhooks/1234/secret-part-9876"))


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class MessageTest(unittest.TestCase):
    """The message each chat gets: Discord's embed, Slack's blocks, in the webhook's language, with the server's names, the
    score with separators, the site's link, and nobody called by what a name holds (ADM-121)."""

    def setUp(self):
        self.patch = mock.patch.multiple(admin.core, PUBLIC_HOST="192.168.1.10:8791", server_health=lambda fresh=False: None)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def chart(self, name="Sena", before="Yuna"):
        return {"player": 7, "name": name, "pattern": 11, "song_id": 1, "song": "Paper Planes", "chart": "2LINE Normal 3",
                "score": 1234567, "before_player": 8, "before": before, "before_score": 900000}

    def test_discord_an_embed_that_calls_nobody(self):
        body = webhooks.payload("discord", "en", "chart_top", self.chart(name="@everyone *bold* [x](http://e.example) <@123>"), 1800000000)
        self.assertEqual(body["allowed_mentions"], {"parse": []})
        embed = body["embeds"][0]
        text = embed["description"]
        # The mention broken, the formatting escaped: the name shows as it is and calls nobody.
        self.assertIn("@" + ZW + "everyone", text)
        self.assertNotIn("@everyone", text)
        self.assertIn(r"\*bold\*", text)
        self.assertIn(r"\[x\](http://e.example)", text)
        self.assertIn(r"\<@" + ZW + r"123\>", text)
        # The score with separators, the one before, and the chart's page on the address players use.
        self.assertIn("1,234,567", text)
        self.assertIn("900,000", text)
        self.assertEqual(embed["url"], "http://192.168.1.10:8791/opendmtq/song.php?id=1&chart=11")
        self.assertTrue(text.endswith("(http://192.168.1.10:8791/opendmtq/song.php?id=1&chart=11)"))
        self.assertEqual(embed["color"], 0x6FD6FF)

    def test_slack_blocks_with_names_as_plain_text_and_the_fallback_escaped(self):
        body = webhooks.payload("slack", "en", "chart_top", self.chart(name="<!here> & @channel"), 1800000000)
        section = body["blocks"][0]["text"]
        self.assertEqual(section["type"], "plain_text")
        self.assertIn("<!here> & @" + ZW + "channel", section["text"])
        # The fallback is read as markup: its three control characters escaped, the mention broken (and Markdown's marks).
        self.assertIn("&lt;\\!here&gt; &amp; @" + ZW + "channel", body["text"])
        self.assertNotIn("<!here>", body["text"])
        self.assertIn("<http://192.168.1.10:8791/opendmtq/song.php?id=1&chart=11|The chart's ranking>", body["blocks"][1]["elements"][0]["text"])

    def test_a_long_name_is_cut(self):
        # Nicknames are the players' own and the game sets no length: Discord refuses an embed whose text is too long.
        body = webhooks.payload("discord", "en", "chart_top", self.chart(name="x" * 5000, before="y" * 5000), 1800000000)
        text = body["embeds"][0]["description"]
        self.assertLess(len(text), 600, len(text))
        self.assertIn("x" * (webhooks.NAME_MAX - 1) + "…", text)

    def test_the_slack_fallback_shows_markdown_as_written(self):
        # Chats that take Slack's messages and read Markdown (Mattermost) would make a link and a picture of a name.
        body = webhooks.payload("slack", "en", "chart_top", self.chart(name="[gift](https://phish.example) ![](https://t.example/p.png) *b*"), 1800000000)
        text = body["text"]
        self.assertNotIn("[gift](", text)
        self.assertIn(r"\[gift\]\(https://phish.example\) \!\[\]\(https://t.example/p.png\) \*b\*", text)

    def test_in_the_webhooks_language(self):
        en = webhooks.payload("discord", "en", "live_on", {"player": 7, "name": "Sena", "song": "Paper Planes", "chart": "2LINE Normal 3", "rec": 1}, 0)
        ko = webhooks.payload("discord", "ko", "live_on", {"player": 7, "name": "Sena", "song": "Paper Planes", "chart": "2LINE Normal 3", "rec": 1}, 0)
        self.assertIn("Sena started broadcasting: Paper Planes · 2LINE Normal 3.", en["embeds"][0]["description"])
        self.assertIn("Sena님이 방송을 시작했어요: Paper Planes · 2LINE Normal 3", ko["embeds"][0]["description"])
        self.assertTrue(ko["embeds"][0]["description"].endswith("(http://192.168.1.10:8791/opendmtq/live.php?p=7)"))
        month = webhooks.payload("slack", "ko", "month_top", {"player": 8, "name": "Yuna", "score": 2000000, "start": 1793491200, "first": True}, 0)
        self.assertIn("Yuna님이 2,000,000점으로 2026년 11월 첫 1위가 됐어요.", month["blocks"][0]["text"]["text"])
        ended = webhooks.payload("discord", "en", "live_off", {"player": 7, "name": "Sena", "rec": 1793000000, "seconds": 3720}, 0)
        self.assertIn("Sena's broadcast ended after 1 h 2 min.", ended["embeds"][0]["description"])
        self.assertIn("live.php?r=7-1793000000", ended["embeds"][0]["url"])
        maint = webhooks.payload("discord", "en", "maint_on", {"message": "Back at nine."}, 0)
        self.assertIn("Maintenance on 192.168.1.10:8791: Back at nine.", maint["embeds"][0]["description"])


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class RulesTest(unittest.TestCase):
    """What the loop tells of and what it leaves out, each by the rule the card names (SRV-50)."""

    def test_the_first_look_takes_the_present_and_sends_nothing_old(self):
        with Server() as inst:
            inst.hook()
            webhooks.detect()
            webhooks.detect()
            self.assertEqual(inst.queued(), [])

    def test_a_chart_taken_from_another_player(self):
        with Server() as inst:
            inst.hook(events=["chart_top"])
            webhooks.detect()
            # Yuna beats Sena's 900,000 on chart 11: news, with who held it and their score.
            inst.play(8, 11, 950000)
            webhooks.detect()
            (hook, kind, data, state), = inst.queued()
            self.assertEqual((kind, data["name"], data["score"], data["before"], data["before_score"], data["song"], data["chart"]),
                             ("chart_top", "Yuna", 950000, "Sena", 900000, "Paper Planes", "2LINE Normal 3"))
            # Yuna beats her own record: no news. Sena plays below her: none either.
            inst.play(8, 11, 990000)
            inst.play(7, 11, 910000)
            webhooks.detect()
            self.assertEqual(len(inst.queued()), 1)

    def test_a_first_place_taken_by_a_play_past_a_looks_share_is_told_at_the_next(self):
        # A look reads so many plays (BATCH), and the best scores as they are: the one who took first place by a play past
        # that look's share is told of when a look reads that play, not taken for the first place's holder before it.
        with Server() as inst, mock.patch.object(webhooks, "BATCH", 2):
            inst.hook(events=["chart_top"])
            webhooks.detect()
            inst.play(9, 11, 100000)
            inst.play(9, 21, 100000)
            inst.play(8, 11, 950000)
            for _ in range(3):
                webhooks.detect()
            self.assertEqual([(k, d["name"], d["before"]) for _, k, d, _ in inst.queued()], [("chart_top", "Yuna", "Sena")])

    def test_the_months_leader_by_a_play_past_a_looks_share_is_told_at_the_next(self):
        with Server() as inst, mock.patch.object(webhooks, "BATCH", 2):
            inst.hook(events=["month_top"])
            month = admin.site.month_start()
            con = sqlite3.connect(admin.core.DB)
            con.execute("UPDATE PlayLog SET played_at = ?", (month - 100,))
            con.commit()
            con.close()
            webhooks.detect()
            base = max(month, int(time.time()) - 600)
            inst.play(7, 12, 100, at=base + 10)
            inst.play(7, 21, 100, at=base + 11)
            inst.play(8, 11, 960000, at=base + 20)
            for _ in range(3):
                webhooks.detect()
            self.assertEqual([(d["name"], d["first"]) for _, k, d, _ in inst.queued()], [("Yuna", True)])

    def test_a_first_place_holder_reset_leaves_the_place_to_the_next(self):
        # Sena held chart 11; her records reset on the Players page: Yuna, second, holds it now, and Riku takes it from her.
        with Server() as inst:
            inst.hook(events=["chart_top"])
            webhooks.detect()
            inst.play(8, 11, 850000)
            webhooks.detect()
            with admin.app.test_request_context():
                admin.players.act(7, "reset", None)
            inst.play(9, 11, 870000)
            webhooks.detect()
            self.assertEqual([(k, d["name"], d["before"]) for _, k, d, _ in inst.queued()], [("chart_top", "Riku", "Yuna")])

    def test_plays_under_ids_the_log_gave_again_are_read(self):
        # The newest plays deleted (a player's records reset), the next ones saved under the same ids again (the log
        # gives the next id after its highest): read all the same.
        with Server() as inst:
            inst.hook(events=["chart_top"])
            webhooks.detect()
            inst.play(9, 21, 500000)
            inst.play(9, 12, 100)
            webhooks.detect()
            con = sqlite3.connect(admin.core.DB)
            con.execute("DELETE FROM PlayLog WHERE user_id = 9")
            con.execute("DELETE FROM Play WHERE user_id = 9")
            con.commit()
            con.close()
            webhooks.detect()
            inst.play(8, 11, 950000)
            webhooks.detect()
            self.assertEqual([(k, d["name"], d["before"]) for _, k, d, _ in inst.queued()], [("chart_top", "Yuna", "Sena")])

    def test_a_first_clear_a_tie_and_a_hidden_song_are_no_news(self):
        with Server() as inst:
            inst.hook(events=["chart_top"])
            webhooks.detect()
            # Chart 21 has nobody yet: Riku's first clear takes it from nobody.
            inst.play(9, 21, 500000)
            webhooks.detect()
            # The same score and accuracy as Sena's on chart 11: the older account stays first, as the site shows it.
            inst.play(9, 11, 900000, judgement=950)
            webhooks.detect()
            self.assertEqual(inst.queued(), [])
            # Song 2 hidden by the owner: Yuna takes chart 21 from Riku, and its name stays off the chat.
            with open(inst.path("content/songs.json"), encoding="utf-8") as f:
                listed = json.load(f)
            listed[1]["hidden_yn"] = "Y"
            inst.write("content/songs.json", json.dumps(listed))
            inst.play(8, 21, 700000)
            webhooks.detect()
            self.assertEqual(inst.queued(), [])

    def test_a_better_accuracy_on_the_same_score_takes_the_first_place_the_site_shows(self):
        with Server() as inst:
            inst.hook(events=["chart_top"])
            webhooks.detect()
            inst.play(9, 11, 900000, judgement=980)
            webhooks.detect()
            self.assertEqual([(k, d["name"], d["before"]) for _, k, d, _ in inst.queued()], [("chart_top", "Riku", "Sena")])

    def test_the_months_first_leader_and_each_new_one(self):
        with Server() as inst:
            inst.hook()
            month = admin.site.month_start()
            # Sena's play of the fixture last month: this month nobody has played yet.
            con = sqlite3.connect(admin.core.DB)
            con.execute("UPDATE PlayLog SET played_at = ?", (month - 100,))
            con.commit()
            con.close()
            webhooks.detect()
            # This month's plays, a few minutes old.
            base = max(month, int(time.time()) - 600)
            inst.play(7, 12, 500000, at=base + 10)
            webhooks.detect()
            inst.play(8, 11, 960000, at=base + 20)
            webhooks.detect()
            # Sena raises her own month: still second, no news.
            inst.play(7, 11, 300000, at=base + 30)
            webhooks.detect()
            months = [(d["name"], d["first"], d.get("before")) for _, k, d, _ in inst.queued() if k == "month_top"]
            self.assertEqual(months, [("Sena", True, None), ("Yuna", False, "Sena")])

    def test_a_broadcast_starts_and_ends_a_minute_after_its_last_upload(self):
        with Server() as inst:
            inst.hook()
            now = time.time()
            # Its recording began a moment ago, as the server opens one.
            rec = int(now) - 3
            webhooks.detect(now)
            inst.on_air(7, rec)
            webhooks.detect(now + 5)
            inst.on_air(7, rec, on=False)
            # Off air for less than a minute: a drop, no end.
            webhooks.detect(now + 30)
            webhooks.detect(now + 60)
            kinds = [k for _, k, _, _ in inst.queued()]
            self.assertEqual(kinds, ["live_on"])
            webhooks.detect(now + 70)
            (_, k1, on, _), (_, k2, off, _) = inst.queued()
            self.assertEqual((k1, on["name"], on["rec"]), ("live_on", "Sena", rec))
            self.assertEqual((k2, off["rec"]), ("live_off", rec))

    def test_one_broadcast_is_one_start_and_one_end_whatever_its_recordings(self):
        with Server() as inst:
            inst.hook(events=["live_on", "live_off"])
            now = time.time()
            webhooks.detect(now)
            # On air without a recording (the server's hold after a quick end and start, or one it could not open): one
            # start, not one at every look.
            for i in range(4):
                inst.on_air(7, 0)
                webhooks.detect(now + 5 * (i + 1))
            # Its recording opens, then the next hour's: the same broadcast still.
            first = int(now) + 20
            inst.on_air(7, first)
            webhooks.detect(now + 25)
            inst.on_air(7, first + 3600)
            webhooks.detect(now + 30)
            self.assertEqual([k for _, k, _, _ in inst.queued()], ["live_on"])
            # Ended, and on again within the minute: still the one broadcast.
            inst.on_air(7, first + 3600, on=False)
            webhooks.detect(now + 50)
            inst.on_air(7, first + 7200)
            webhooks.detect(now + 60)
            self.assertEqual([k for _, k, _, _ in inst.queued()], ["live_on"])
            # Off air for a minute: one end, watched again from its first recording.
            inst.on_air(7, first + 7200, on=False)
            webhooks.detect(now + 130)
            self.assertEqual([(k, d.get("rec")) for _, k, d, _ in inst.queued()], [("live_on", 0), ("live_off", first)])
            # On again after that: a new broadcast, its recording opened a moment ago.
            inst.on_air(7, int(time.time()) - 2)
            webhooks.detect(now + 140)
            self.assertEqual([k for _, k, _, _ in inst.queued()], ["live_on", "live_off", "live_on"])

    def test_an_unrecorded_broadcasts_end_leads_to_the_players_live_page(self):
        with mock.patch.multiple(admin.core, PUBLIC_HOST="192.168.1.10:8791", server_health=lambda fresh=False: None):
            body = webhooks.payload("discord", "en", "live_off", {"player": 7, "name": "Sena", "rec": 0, "seconds": 300}, 0)
        self.assertEqual(body["embeds"][0]["url"], "http://192.168.1.10:8791/opendmtq/live.php?p=7")

    def test_maintenance_on_and_off(self):
        with Server() as inst:
            inst.hook()
            webhooks.detect()
            admin.songs.set_maintenance(True, "Back at nine.", HOST)
            webhooks.detect()
            admin.songs.set_maintenance(True, "Back at ten.", HOST)
            webhooks.detect()
            admin.songs.set_maintenance(False, "", HOST)
            webhooks.detect()
            self.assertEqual([(k, d.get("message")) for _, k, d, _ in inst.queued()], [("maint_on", "Back at nine."), ("maint_off", "")])

    def test_each_webhook_hears_what_it_takes(self):
        with Server() as inst:
            inst.hook(events=["maint_on"], path="/a")
            inst.hook(events=["chart_top"], path="/b")
            webhooks.detect()
            inst.play(8, 11, 950000)
            admin.songs.set_maintenance(True, "", HOST)
            webhooks.detect()
            self.assertEqual(sorted((h, k) for h, k, _, _ in inst.queued()), [(1, "maint_on"), (2, "chart_top")])

    def test_nothing_is_followed_without_a_webhook(self):
        with Server():
            self.assertEqual(webhooks.detect(), 0)
            con = sqlite3.connect(admin.core.DB)
            try:
                # Not even its tables: a server nobody added a webhook to is left as it was.
                self.assertIsNone(con.execute("SELECT 1 FROM sqlite_master WHERE name = 'WebhookState'").fetchone())
            finally:
                con.close()


def _turns(db, content, custom, start, done):
    """Another admin process's loop (multiprocessing): its own turns of detect and deliver on the same database, from the
    moment every process is ready (start, a barrier) until no message waits; then how many it sent, on done."""
    with mock.patch.multiple(admin.core, DB=db, PUBLIC_HOST=HOST, server_health=lambda fresh=False: None), \
            mock.patch.object(admin.songs, "CONTENT", content), mock.patch.object(admin.songs, "CUSTOM", custom), \
            mock.patch.object(webhooks, "LOOPBACK_OK", True):
        start.wait()
        done.put(_until_sent())


def _until_sent():
    """Turns of the loop until nothing waits or is being sent; how many messages this process sent."""
    sent = 0
    for _ in range(400):
        sent += webhooks.run_once()
        con = sqlite3.connect(admin.core.DB)
        try:
            left = con.execute("SELECT COUNT(*) FROM WebhookMessage WHERE state IN ('waiting', 'sending')").fetchone()[0]
        finally:
            con.close()
        if not left:
            break
        time.sleep(0.01)
    return sent


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class OnceTest(unittest.TestCase):
    """Two admin processes on one database: each event is queued once and each message sent once (SRV-51)."""

    def test_two_processes_send_each_message_once(self):
        # Twenty chats hear of maintenance; three processes (two spawned, this one) turn the loop from one moment on, each
        # message taking a tenth of a second at the chat, so that their sends overlap. Each chat gets its message once.
        with Server() as inst:
            inst.chat.delay = 0.1
            for i in range(20):
                inst.hook(events=["maint_on"], path=f"/hooks/{i}")
            webhooks.detect()
            admin.songs.set_maintenance(True, "Back soon.", HOST)
            # Processes of their own (spawned: nothing of this one's threads), each importing the admin service anew, and
            # all three starting together.
            ctx = multiprocessing.get_context("spawn")
            start, done = ctx.Barrier(3), ctx.Queue()
            others = [ctx.Process(target=_turns, args=(admin.core.DB, inst.path("content"), inst.path("custom"), start, done)) for _ in range(2)]
            for p in others:
                p.start()
            start.wait()
            mine = _until_sent()
            theirs = [done.get(timeout=120) for _ in others]
            for p in others:
                p.join(60)
            paths = sorted(m["path"] for m in inst.chat.got)
            self.assertEqual(paths, sorted(f"/hooks/{i}" for i in range(20)))
            self.assertEqual(mine + sum(theirs), 20)
            # The sends overlapped: more than one process sent some.
            self.assertGreater(sum(1 for n in [mine] + theirs if n), 1, [mine] + theirs)
            self.assertTrue(all(state == "sent" for _, _, _, state in inst.queued()))

    def test_two_looks_from_one_state_write_once(self):
        # Two looks from the same state, at two moments, each finding Sena newly on air (without a recording, each look's
        # start is its own moment, so their messages' keys differ): only the first written counts.
        with Server() as inst:
            inst.hook(events=["live_on"])
            now = time.time()
            webhooks.detect(now)
            inst.on_air(7, 0)
            looks = []
            con1, con2 = webhooks.connect(), webhooks.connect()
            try:
                state = webhooks.read_state(con1)
                for con, at in ((con1, now + 5), (con2, now + 7)):
                    events, new, tops = webhooks.look(con, state, at)
                    events += webhooks.look_live(con, new, at)
                    looks.append((con, events, new, tops, at))
                self.assertEqual({e[1] for _, events, _, _, _ in looks for e in events}, {f"live_on:7:{int(now + 5)}", f"live_on:7:{int(now + 7)}"})
                written = [webhooks.write(con, state, events, new, tops, at) for con, events, new, tops, at in looks]
            finally:
                con1.close()
                con2.close()
            self.assertEqual((written, [k for _, k, _, _ in inst.queued()]), ([1, 0], ["live_on"]))

    def test_a_look_begun_before_the_loop_forgot_writes_nothing(self):
        # A look found Yuna's first place; before it writes, the owner deletes the webhook and adds another, whose first
        # look takes the present as its start: the old look's finding is no news for the new webhook.
        with Server() as inst:
            inst.hook(events=["chart_top"])
            webhooks.detect()
            inst.play(8, 11, 950000)
            real_write = webhooks.write

            def write_after_the_loop_forgot(*args, **kw):
                with admin.app.test_request_context():
                    webhooks.delete(1)
                    inst.hook(events=["chart_top"], path="/new")
                # The new webhook's first look, in another process: the present is its start.
                webhooks.detect()
                return real_write(*args, **kw)

            with mock.patch.object(webhooks, "write", write_after_the_loop_forgot):
                webhooks.detect()
            self.assertEqual(inst.queued(), [])

    def test_two_looks_at_once_queue_one_message(self):
        with Server() as inst:
            inst.hook(events=["chart_top"])
            webhooks.detect()
            inst.play(8, 11, 950000)
            start, failed = threading.Barrier(4), []

            def one():
                start.wait()
                try:
                    webhooks.detect()
                except Exception as e:  # pylint: disable=broad-except
                    # A look that fails (a database that waits on itself) fails the test.
                    failed.append(repr(e))

            threads = [threading.Thread(target=one) for _ in range(4)]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
            self.assertEqual((failed, [k for _, k, _, _ in inst.queued()]), ([], ["chart_top"]))


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class SendingTest(unittest.TestCase):
    """The retries: a wait after each failure, the chat's own when it asks, the order kept, a message given up after half an
    hour, and a webhook gone said as such (SRV-52)."""

    def test_a_failure_waits_and_the_next_try_sends_it(self):
        with Server() as inst:
            inst.chat.answers = [(500, b"oops", {}), (204, b"", {})]
            inst.hook()
            now = time.time()
            webhooks.detect(now)
            admin.songs.set_maintenance(True, "", HOST)
            webhooks.detect(now)
            self.assertEqual(webhooks.deliver(now), 0)
            # Due again ten seconds later, not before.
            self.assertEqual(webhooks.deliver(now + 5), 0)
            self.assertEqual(len(inst.chat.got), 1)
            failing = webhooks.listing()[0]["last_failure"]
            self.assertEqual((failing["code"], failing["status"]), ("server", 500))
            self.assertEqual(webhooks.deliver(now + 11), 1)
            self.assertIsNone(webhooks.listing()[0]["last_failure"])
            self.assertEqual(len(inst.chat.got), 2)

    def test_the_chat_asks_to_wait_and_its_later_messages_keep_their_order(self):
        with Server() as inst:
            inst.chat.answers = [(429, json.dumps({"retry_after": 2.5}).encode(), {}), (204, b"", {})]
            inst.hook()
            now = time.time()
            webhooks.detect(now)
            admin.songs.set_maintenance(True, "", HOST)
            webhooks.detect(now)
            admin.songs.set_maintenance(False, "", HOST)
            webhooks.detect(now)
            webhooks.deliver(now)
            # The second message waits with the first: nothing goes before the time the chat asked for.
            self.assertEqual(webhooks.deliver(now + 2), 0)
            self.assertEqual(webhooks.deliver(now + 3), 2)
            titles = [title_of(m["body"]) for m in inst.chat.got]
            self.assertEqual(titles, ["Maintenance", "Maintenance", "Maintenance is over"])
            # Asked to wait is no failure: the card never showed one.
            self.assertIsNone(webhooks.listing()[0]["last_failure"])

    def test_a_chat_that_keeps_asking_to_wait_is_no_failure(self):
        # Nine 429s in a row: still waiting, each try after the chat's own wait; given up half an hour after its news, and
        # counted then.
        with Server() as inst:
            inst.chat.answers = [(429, json.dumps({"retry_after": 1}).encode(), {})]
            inst.hook(events=["maint_on"])
            now = time.time()
            webhooks.detect(now)
            admin.songs.set_maintenance(True, "", HOST)
            webhooks.detect(now)
            for i in range(9):
                webhooks.deliver(now + i * 2)
            self.assertEqual((len(inst.chat.got), [s for _, _, _, s in inst.queued()]), (9, ["waiting"]))
            self.assertEqual(webhooks.listing()[0]["given_up"], 0)
            webhooks.deliver(now + webhooks.GIVE_UP + 1)
            self.assertEqual(([s for _, _, _, s in inst.queued()], webhooks.listing()[0]["given_up"]), (["dropped"], 1))

    def test_a_webhook_gone_stops_its_message_and_says_so(self):
        with Server() as inst:
            inst.chat.answers = [(404, json.dumps({"message": "Unknown Webhook"}).encode(), {})]
            inst.hook()
            now = time.time()
            webhooks.detect(now)
            admin.songs.set_maintenance(True, "", HOST)
            webhooks.detect(now)
            webhooks.deliver(now)
            webhooks.deliver(now + 3600)
            self.assertEqual(len(inst.chat.got), 1)
            self.assertEqual([s for _, _, _, s in inst.queued()], ["failed"])
            words = webhooks.listing()[0]["last_failure"]["message"]
            self.assertIn("not there", words)

    def test_given_up_after_half_an_hour_and_counted(self):
        with Server() as inst:
            inst.chat.answers = [(503, b"", {})]
            inst.hook()
            now = time.time()
            webhooks.detect(now)
            admin.songs.set_maintenance(True, "", HOST)
            webhooks.detect(now)
            for wait in (0, 10, 40, 100, 220, 520, 1120):
                webhooks.deliver(now + wait + 1)
            webhooks.deliver(now + webhooks.GIVE_UP + 1)
            hook = webhooks.listing()[0]
            self.assertEqual((hook["waiting"], hook["given_up"]), (0, 1))

    def test_a_message_the_chat_may_have_taken_is_never_sent_twice(self):
        # The process stopped after the chat took the message and before it noted so: at most once, never again.
        with Server() as inst:
            inst.hook(events=["maint_on"])
            now = time.time()
            webhooks.detect(now)
            admin.songs.set_maintenance(True, "", HOST)
            webhooks.detect(now)
            with mock.patch.object(webhooks, "settle", side_effect=RuntimeError("stopped")):
                with self.assertRaises(RuntimeError):
                    webhooks.deliver(now)
            for later in (61, webhooks.CLAIM + 1, 1200):
                webhooks.deliver(now + later)
            self.assertEqual(len(inst.chat.got), 1)
            self.assertEqual([s for _, _, _, s in inst.queued()], ["failed"])

    def test_news_is_as_old_as_what_it_tells(self):
        # The admin service away for two hours: a first place taken then is no news now, and is not sent.
        with Server() as inst:
            inst.hook(events=["chart_top"])
            webhooks.detect()
            inst.play(8, 11, 950000, at=int(time.time()) - 7200)
            webhooks.detect()
            self.assertEqual(webhooks.deliver(), 0)
            self.assertEqual((inst.queued(), inst.chat.got), ([], []))
        # One taken 25 minutes ago, whose chat does not take it: given up 5 minutes on, half an hour after the play.
        with Server() as inst:
            inst.chat.answers = [(503, b"", {})]
            inst.hook(events=["chart_top"])
            now = time.time()
            webhooks.detect(now)
            inst.play(8, 11, 950000, at=int(now) - 1500)
            webhooks.detect(now)
            webhooks.deliver(now)
            webhooks.deliver(now + 301)
            self.assertEqual([s for _, _, _, s in inst.queued()], ["dropped"])

    def test_no_answer_in_time_and_no_chat_there(self):
        with Server() as inst:
            inst.chat.delay = 1.0
            self.assertEqual(webhooks.post(inst.chat.url + "/x", {}, timeout=0.3)["code"], "timeout")
            # A port nothing listens on: unreachable.
            closed = Chat()
            url = closed.url
            closed.close()
            self.assertEqual(webhooks.post(url + "/x", {}, timeout=2)["code"], "unreachable")

    def test_a_redirect_is_not_followed(self):
        with Server() as inst:
            inst.chat.answers = [(302, b"", {"Location": "http://127.0.0.1:9/elsewhere"})]
            result = webhooks.post(inst.chat.url + "/x", {"a": 1})
            self.assertEqual((result["ok"], result["code"], result["status"]), (False, "redirect", 302))
            self.assertEqual(len(inst.chat.got), 1)

    def test_the_request_names_the_server_and_sends_json(self):
        with Server() as inst:
            self.assertTrue(webhooks.post(inst.chat.url + "/x", {"content": "é"})["ok"])
            self.assertEqual(inst.chat.got[0]["body"], {"content": "é"})
            self.assertTrue(inst.chat.got[0]["agent"].startswith("OpenDMTQ/"))


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class RestoreTest(unittest.TestCase):
    """A restore keeps today's webhooks, and nothing the restored database had queued is sent again (SRV-53)."""

    def test_todays_webhooks_stay_and_the_old_queue_goes(self):
        with Server() as inst:
            inst.hook(path="/old")
            webhooks.detect()
            admin.songs.set_maintenance(True, "", HOST)
            webhooks.detect()
            # The backup holds the old webhook and its waiting message.
            name = admin.backups.make_backup("manual")
            admin.songs.set_maintenance(False, "", HOST)
            with admin.app.test_request_context():
                webhooks.delete(1)
            inst.hook(path="/today")
            with admin.app.test_request_context():
                said, done = admin.backups.restore_backup(name, os.path.join(admin.core.BACKUPS, name))
            self.assertTrue(done, said)
            listed = webhooks.listing()
            self.assertEqual([h["address"] for h in listed], [webhooks.masked(inst.chat.url + "/today")])
            self.assertEqual(inst.queued(), [])
            # The next look starts from the restored data: nothing of it is sent.
            webhooks.run_once()
            self.assertEqual(inst.chat.got, [])


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class CardTest(unittest.TestCase):
    """The card on the Notices page and the log of changes (ADM-122, ADM-123)."""

    def form(self, inst, path, **data):
        csrf = page_token(inst)
        return inst.client.post(path, data={"csrf": csrf, **data})

    def test_added_tested_changed_and_deleted_on_the_card(self):
        with Server() as inst:
            r = self.form(inst, "/opendmtq/admin/webhooks", url=inst.chat.url + "/api/webhooks/1234/secret-part-9876", language="ko",
                          event=["live_on", "maint_on"])
            self.assertEqual(r.status_code, 302)
            self.assertTrue(r.headers["Location"].endswith("/opendmtq/admin/maintenance#hooks"))
            page = inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True)
            self.assertIn('id="hooks"', page)
            self.assertIn("127.0.0.1:", page)
            # The address masked on the page, never whole.
            self.assertIn("••••9876", page)
            self.assertNotIn("secret-part-9876", page)
            self.assertIn("Nothing sent yet", page)
            # Send a test: the chat gets it, and the card says when.
            r = self.form(inst, "/opendmtq/admin/webhooks/1", action="test")
            self.assertEqual(r.status_code, 302)
            self.assertEqual(title_of(inst.chat.got[0]["body"]), "시험 메시지")
            page = inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True)
            self.assertIn("Sent just now", page)
            # A chat gone: the test says so, and the card in red with why.
            inst.chat.answers = [(404, b"", {})]
            self.form(inst, "/opendmtq/admin/webhooks/1", action="test")
            page = inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True)
            self.assertIn('class="lamp bad"', page)
            self.assertIn("the chat says this webhook is not there", page)
            # The status page names it among what to look at.
            self.assertIn("Messages to a chat are not going through", inst.client.get("/opendmtq/admin/").get_data(as_text=True))
            self.form(inst, "/opendmtq/admin/webhooks/1", action="save", language="en", event=["maint_off"])
            self.assertEqual(webhooks.listing()[0]["events"], ["maint_off"])
            self.form(inst, "/opendmtq/admin/webhooks/1", action="delete")
            self.assertEqual(webhooks.listing(), [])
            # Every change in the log of changes, the address masked.
            log = admin.insights.audit_read(inst.path("state"))
            notes = [(c["what"], c["target"]) for c in log if c["what"].startswith("webhook")]
            masked = webhooks.masked(inst.chat.url + "/api/webhooks/1234/secret-part-9876")
            self.assertEqual(notes[::-1], [("webhook_new:", masked), ("webhook_action:test", masked), ("webhook_action:test", masked),
                                           ("webhook_action:save", masked), ("webhook_action:delete", masked)])
            with open(inst.path("state/changes.log"), encoding="utf-8") as f:
                self.assertNotIn("secret-part-9876", f.read())

    def test_a_refused_address_comes_back_with_what_was_typed_and_why(self):
        with Server() as inst:
            # Back to the page's own address (a form sent in place needs it), with why and what was typed, once.
            r = self.form(inst, "/opendmtq/admin/webhooks", url="ftp://chat.example/x", language="ko", event=["maint_on"])
            self.assertEqual((r.status_code, r.headers["Location"].rsplit("/", 1)[-1]), (302, "maintenance#hooks"))
            page = inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True)
            self.assertIn("That is no webhook address", page)
            self.assertIn('value="ftp://chat.example/x"', page)
            self.assertRegex(page, r'<option value="ko" selected>한국어</option></select></label>\s*</div>\s*<div class="hook-events"')
            self.assertRegex(page, r'<div class="hook-events"[^>]*>\s*<span[^>]*>[^<]*</span>\s*<label class="check"><input type="checkbox" name="event" value="live_on"><span>'
                             r'[^<]*</span></label>(?:<label[^>]*>.*?</label>){3}<label class="check"><input type="checkbox" name="event" value="maint_on" checked>')
            # The address typed is kept on the server, never in the browser's cookie.
            with inst.client.session_transaction(path="/opendmtq/admin/") as sess:
                self.assertNotIn("ftp://chat.example/x", json.dumps(dict(sess)))
            # Once: the page drawn again comes as it always does.
            self.assertNotIn('value="ftp://chat.example/x"', inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True))
            self.form(inst, "/opendmtq/admin/webhooks", url=inst.chat.url + "/x", language="en")
            self.assertIn("Pick at least one thing", inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True))

    def test_the_card_in_korean_and_its_delete_asks_first(self):
        with Server() as inst:
            inst.hook()
            inst.sign_in()
            inst.client.set_cookie("opendmtq_lang", "ko")
            page = inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True)
            self.assertIn("디스코드·슬랙 알림", page)
            self.assertIn("아직 보낸 메시지가 없습니다", page)
            self.assertRegex(page, r'value="delete" data-ask="[^"]+" data-yes="삭제"')
            # A new webhook speaks the page's language as the form comes.
            self.assertRegex(page, r'<option value="ko" selected>한국어</option></select></label>\s*</div>\s*<div class="hook-events"')
            # When it went, in words a Korean reader says: "방금 보냄", "3분 전 보냄", never "방금에".
            csrf = page_token(inst)
            inst.client.post("/opendmtq/admin/webhooks/1", data={"csrf": csrf, "action": "test"})
            page = inst.client.get("/opendmtq/admin/maintenance").get_data(as_text=True)
            self.assertIn("방금 보냄", page)
            self.assertIn("방금 추가", page)
            self.assertNotIn("방금에", page)


@unittest.skipUnless(HAVE_FLASK, "needs Flask (in the tools image)")
class LoopTest(unittest.TestCase):
    """The loop's own thread: kept out of the tests, and a turn that fails does not end it."""

    def test_not_started_in_the_tests(self):
        self.assertEqual(os.environ.get("OPENDMTQ_WEBHOOK_LOOP"), "off")
        self.assertNotIn("webhooks", [th.name for th in threading.enumerate()])

    def test_a_failing_turn_is_tried_again(self):
        turns = []

        def turn():
            turns.append(1)
            if len(turns) == 1:
                raise sqlite3.OperationalError("database is locked")
            if len(turns) == 3:
                raise SystemExit

        with mock.patch.object(webhooks, "run_once", turn), mock.patch.object(webhooks, "EVERY", 0), \
                mock.patch.object(webhooks.app.logger, "warning") as warned:
            with self.assertRaises(SystemExit):
                webhooks._loop()
        self.assertEqual(len(turns), 3)
        self.assertIn("database is locked", str(warned.call_args_list[0]))

    def test_a_lasting_failure_is_said_once(self):
        turns = []

        def turn():
            turns.append(1)
            if len(turns) == 5:
                raise SystemExit
            raise sqlite3.OperationalError("no such table: Play")

        with mock.patch.object(webhooks, "run_once", turn), mock.patch.object(webhooks, "EVERY", 0), \
                mock.patch.object(webhooks.app.logger, "warning") as warned:
            with self.assertRaises(SystemExit):
                webhooks._loop()
        self.assertEqual(warned.call_count, 1)


if __name__ == "__main__":
    unittest.main()
