"""test_brain_controls.py — the trust/cloud/knowledge/ops controls added to
the Mac Brain: token rotation, cloud egress, data clearing, reindex, filters,
semantic search, quiet hours, retention, and the draft→approve→send guard."""
from __future__ import annotations

import json
import threading
import time
import urllib.request

from dreamlayer.ai_brain.server import Brain, make_brain_server
from dreamlayer.ai_brain.server.store import (
    BrainConfig, ActivityLog, QueryHistory, in_quiet_hours, _prune_jsonl,
)
from dreamlayer.ai_brain.server.index import FileIndex


def _op():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Live:
    def __init__(self, tmp, token="tok"):
        cfg = tmp / "cfg"; cfg.mkdir()
        BrainConfig(token=token).save(cfg)
        self.brain = Brain(cfg)
        self.srv = make_brain_server(self.brain, "127.0.0.1", 0)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.h = {"X-DreamLayer-Token": token, "Content-Type": "application/json"}

    def _do(self, req):
        try:
            return json.loads(_op().open(req, timeout=5).read())
        except urllib.error.HTTPError as e:      # return the JSON body of 4xx
            return json.loads(e.read())

    def get(self, p):
        return self._do(urllib.request.Request(self.url + p, headers=self.h))

    def post(self, p, body):
        return self._do(urllib.request.Request(
            self.url + p, data=json.dumps(body).encode(), headers=self.h))

    def stop(self):
        self.srv.shutdown(); self.srv.server_close()


# --- config primitives -----------------------------------------------------

class TestConfig:
    def test_cloud_ready_and_masking(self):
        c = BrainConfig(cloud_api_key="secret", cloud_model="gpt-4o-mini")
        assert c.cloud_ready() is True
        assert c.public()["cloud_api_key"] == "set"       # never leaks
        assert "secret" not in json.dumps(c.public())
        assert BrainConfig().cloud_ready() is False        # no key → not ready
        c.network_mode = "lan_only"
        assert c.cloud_ready() is False                    # incognito shuts it

    def test_quiet_hours_window(self):
        two_am = time.mktime(time.struct_time((2026, 1, 1, 2, 0, 0, 0, 1, -1)))
        noon = time.mktime(time.struct_time((2026, 1, 1, 12, 0, 0, 0, 1, -1)))
        assert in_quiet_hours("22:00-07:00", two_am) is True
        assert in_quiet_hours("22:00-07:00", noon) is False
        assert in_quiet_hours("", two_am) is False

    def test_prune_drops_old(self, tmp_path):
        p = tmp_path / "log.jsonl"
        old = time.time() - 100 * 86400
        p.write_text(json.dumps({"ts": old, "x": 1}) + "\n" +
                     json.dumps({"ts": time.time(), "x": 2}) + "\n")
        assert _prune_jsonl(p, 30) == 1
        assert len(p.read_text().splitlines()) == 1


# --- semantic search (fake embedder, no Ollama needed) ---------------------

class TestSemantic:
    def test_ranks_by_vector_similarity(self, tmp_path):
        d = tmp_path / "notes"; d.mkdir()
        (d / "a.md").write_text("the cat sat on the mat")
        (d / "b.md").write_text("quantum chromodynamics and gluons")
        cfg = BrainConfig(folders=[str(d)], semantic_search=True)
        # a toy embedder: 2-D vector [has_cat, has_physics]
        def embed(t):
            t = t.lower()
            return [1.0 if "cat" in t else 0.0, 1.0 if "gluon" in t or "physics" in t else 0.0]
        idx = FileIndex(cfg, embedder=embed)
        idx.reindex()
        hits = idx.search("tell me about the physics")
        assert hits and "gluons" in hits[0][1]

    def test_filters_extensions_and_size(self, tmp_path):
        d = tmp_path / "n"; d.mkdir()
        (d / "keep.md").write_text("hello world")
        (d / "skip.log").write_text("noise noise")
        cfg = BrainConfig(folders=[str(d)], index_extensions=["md"])
        idx = FileIndex(cfg); idx.reindex()
        assert idx.stats()["files"] == 1                   # .log excluded


# --- live endpoints --------------------------------------------------------

class TestControls:
    def test_token_rotate_reindex_clear(self, tmp_path):
        lb = Live(tmp_path)
        try:
            old = lb.get("/dreamlayer/token")["token"]
            new = lb.post("/dreamlayer/token/rotate", {})["token"]
            assert new and new != old
            # old token is now rejected; new one works
            lb.h["X-DreamLayer-Token"] = new
            assert lb.post("/dreamlayer/reindex", {})["stats"]["files"] == 0
            # activity captured the rotation + reindex
            kinds = {i["kind"] for i in lb.get("/dreamlayer/history")["items"]}
            assert "privacy" in kinds and "index" in kinds
            lb.post("/dreamlayer/clear", {"what": "activity"})
            assert lb.get("/dreamlayer/history")["items"] == []
        finally:
            lb.stop()

    def test_status_reports_missing_and_egress(self, tmp_path):
        lb = Live(tmp_path)
        try:
            lb.post("/dreamlayer/folders", {"action": "add", "path": "/no/such/dir"})
            s = lb.get("/dreamlayer/status")
            assert "/no/such/dir" in s["missing"]
            assert s["cloud_calls"] == 0 and s["cloud_ready"] is False
            h = lb.get("/dreamlayer/health")
            assert h["version"] and "uptime_s" in h
        finally:
            lb.stop()

    def test_cloud_fallback_logs_egress(self, tmp_path):
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(token="t", cloud_api_key="k", cloud_model="m").save(cfg)
        brain = Brain(cfg)
        # inject a fake cloud call so nothing hits the network
        import dreamlayer.ai_brain.server.backends as be
        orig = be.cloud_chat
        be.cloud_chat = lambda config, prompt, **k: "the cloud answer"
        try:
            ans = brain.ask("something not in any file")
            assert ans is not None and ans.tier == "cloud"
            assert brain.config.cloud_calls == 1
            assert any(i["kind"] == "cloud-egress" for i in brain.activity.recent())
        finally:
            be.cloud_chat = orig

    def test_messages_feed_gated_and_relayed(self, tmp_path):
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(token="t").save(cfg)
        fake = [{"channel": "imessage", "who": "Marcus", "from_me": False,
                 "text": "you around?", "ts": 2.0}]
        brain = Brain(cfg, messages_fn=lambda config, n=20: fake)
        srv = make_brain_server(brain, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        h = {"X-DreamLayer-Token": "t"}
        op = _op()
        try:
            # email off → relay is closed
            r1 = json.loads(op.open(urllib.request.Request(
                url + "/dreamlayer/messages/recent", headers=h), timeout=5).read())
            assert r1["enabled"] is False and r1["items"] == []
            # turn it on → the glasses would see Marcus's message
            brain.config.email_enabled = True; brain.save()
            r2 = json.loads(op.open(urllib.request.Request(
                url + "/dreamlayer/messages/recent", headers=h), timeout=5).read())
            assert r2["enabled"] is True
            assert r2["items"][0]["who"] == "Marcus"
        finally:
            srv.shutdown(); srv.server_close()

    def test_summarize_emails_adds_a_glance(self, tmp_path):
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(token="t", email_enabled=True, summarize_emails=True).save(cfg)
        long_body = "This is a very long email. " * 20
        fake = [{"channel": "email", "who": "a@b.co", "from_me": False,
                 "subject": "Renewal", "text": long_body, "ts": 3.0},
                {"channel": "imessage", "who": "Priya", "from_me": False,
                 "text": "tea?", "ts": 4.0}]
        brain = Brain(cfg, messages_fn=lambda config, n=20: fake)
        srv = make_brain_server(brain, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            data = json.loads(_op().open(urllib.request.Request(
                url + "/dreamlayer/messages/recent",
                headers={"X-DreamLayer-Token": "t"}), timeout=5).read())
            items = {i["who"]: i for i in data["items"]}
            # the long email gets a short summary; the text is untouched
            assert "summary" in items["a@b.co"]
            assert len(items["a@b.co"]["summary"]) < len(long_body)
            assert "summary" not in items["Priya"]
            assert data["summarize_emails"] is True
        finally:
            srv.shutdown(); srv.server_close()

    def test_morning_brief_synthesizes_agenda_and_new(self, tmp_path):
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(token="t", email_enabled=True).save(cfg)
        feed = [{"channel": "imessage", "who": "Marcus", "from_me": False, "text": "hi", "ts": 5.0},
                {"channel": "imessage", "who": "Me", "from_me": True, "text": "yo", "ts": 6.0},
                {"channel": "email", "who": "x@y.co", "from_me": False, "subject": "Renewal", "text": "…", "ts": 7.0}]
        brain = Brain(cfg, messages_fn=lambda config, n=20: feed)
        b = brain.brief(agenda=["Send Marcus the lease by Friday"], since=0)
        joined = " ".join(b["bullets"])
        assert "Send Marcus the lease by Friday" in joined      # my agenda
        assert "1 new text" in joined and "Marcus" in joined     # incoming, not mine
        assert any("Renewal" in x for x in b["bullets"])         # email subject
        assert b["missed"] == {"texts": 1, "emails": 1}
        # 'since' powers what-did-I-miss: nothing after ts 7 → clear
        assert brain.brief(since=99)["missed"] == {"texts": 0, "emails": 0}

    def test_backup_restore_round_trips(self, tmp_path):
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(token="t", cloud_model="gpt-4o-mini", quiet_hours="22:00-07:00").save(cfg)
        brain = Brain(cfg)
        brain.activity.add("folder", "Added folder /x")
        brain.history.add("q", "a", "laptop", ["f"], ts=1)
        snap = brain.export_backup()
        assert snap["config"]["quiet_hours"] == "22:00-07:00"
        # mutate, then restore from the snapshot
        brain.config.quiet_hours = ""; brain.config.cloud_model = "other"; brain.save()
        brain.activity.clear(); brain.history.clear()
        brain.import_backup(snap)
        assert brain.config.quiet_hours == "22:00-07:00"      # settings back
        assert brain.config.cloud_model == "gpt-4o-mini"
        assert any(i["kind"] == "folder" for i in brain.activity.recent())  # logs back
        assert brain.history.recent()[0]["query"] == "q"

    def test_voice_and_calendar_endpoints(self, tmp_path):
        lb = Live(tmp_path)
        try:
            # voice: a command comes back as a structured intent
            r = lb.post("/dreamlayer/voice", {"text": "reply to Priya saying on my way"})
            assert r == {"intent": "reply", "to": "Priya", "text": "on my way"}
            assert lb.post("/dreamlayer/voice", {"text": "brief me"})["intent"] == "brief"
            # calendar: add an event, then it's returned
            import time as _t
            items = lb.post("/dreamlayer/calendar", {"title": "Standup", "ts": _t.time() + 600})["items"]
            assert items and items[0]["title"] == "Standup"
        finally:
            lb.stop()

    def test_calendar_feeds_brief(self, tmp_path):
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(token="t").save(cfg)
        (cfg / "agenda.json").write_text(json.dumps([
            {"title": "Standup", "ts": time.time() + 600, "place": "Zoom"},
            {"title": "Dentist", "ts": time.time() - 99999},          # past → dropped
        ]))
        brain = Brain(cfg)
        cal = brain.calendar()
        assert [e["title"] for e in cal] == ["Standup"]               # only upcoming
        assert any("Standup" in b for b in brain.brief()["bullets"])   # leads the brief

    def test_agenda_add_and_remove_events(self, tmp_path):
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(token="t").save(cfg)
        brain = Brain(cfg)
        soon = time.time() + 600
        brain.add_event("Standup", soon, "Zoom")
        brain.add_event("Lunch", soon + 3600, "Cafe")
        assert [e["title"] for e in brain.calendar()] == ["Standup", "Lunch"]
        items = brain.remove_event("Standup", soon)
        assert [e["title"] for e in items] == ["Lunch"]          # only Standup gone
        assert any(i["text"] == "Removed event Standup" for i in brain.activity.recent())

    def test_people_registry_add_update_remove(self, tmp_path):
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(token="t").save(cfg)
        brain = Brain(cfg)
        brain.add_person("Marcus", "landlord", ["work"])
        brain.add_person("Priya", "designer")
        names = [p["name"] for p in brain.people()]
        assert "Marcus" in names and "Priya" in names
        # re-adding updates rather than duplicating
        brain.add_person("Marcus", "landlord — signing Friday", ["work", "lease"])
        marcus = [p for p in brain.people() if p["name"] == "Marcus"]
        assert len(marcus) == 1 and "Friday" in marcus[0]["note"]
        # removal
        brain.remove_person("Priya")
        assert [p["name"] for p in brain.people()] == ["Marcus"]

    def test_rewind_groups_todays_activity_by_hour(self, tmp_path):
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(token="t").save(cfg)
        brain = Brain(cfg)
        now = time.time()
        day_start = now - (now % 86400)
        brain.activity.add("folder", "Added folder /docs", ts=day_start + 9 * 3600 + 5)
        brain.activity.add("ask", "asked about the lease", ts=day_start + 9 * 3600 + 200)
        brain.activity.add("cloud-egress", "cloud call", ts=day_start + 14 * 3600)
        brain.add_event("Standup", now + 600)          # upcoming event lands today too
        r = brain.rewind(now)
        hours = [b["hour"] for b in r["blocks"]]
        assert 9 in hours                               # two 9am items grouped
        nine = next(b for b in r["blocks"] if b["hour"] == 9)
        assert nine["count"] == 2 and nine["label"].endswith("AM")
        assert r["count"] >= 3

    def test_scheduler_delivers_brief_once_at_the_hour(self, tmp_path):
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(token="t").save(cfg)
        brain = Brain(cfg)
        now = time.time()
        this_hour = time.localtime(now).tm_hour
        # off by default: nothing delivered
        assert brain.maybe_run_brief(now) is False and brain.last_brief is None
        # arm it for the current hour → fires once and caches the result
        brain.config.brief_hour = this_hour
        assert brain.maybe_run_brief(now) is True
        assert brain.last_brief and "text" in brain.last_brief
        assert any(i["kind"] == "brief" for i in brain.activity.recent())
        # same day, same hour → does not nag again
        assert brain.maybe_run_brief(now) is False
        # a different hour never fires
        brain.config.brief_hour = (this_hour + 1) % 24
        brain._brief_ran_day = None
        assert brain.maybe_run_brief(now) is False

    def test_message_draft_previews_without_sending(self, tmp_path):
        lb = Live(tmp_path)
        try:
            r = lb.post("/dreamlayer/message/draft",
                        {"channel": "imessage", "to": "Marcus", "text": "hi"})
            assert "Marcus" in r["script"] and "hi" in r["script"]
            # sending without approval is refused
            bad = lb.post("/dreamlayer/message/send",
                          {"channel": "imessage", "to": "Marcus", "text": "hi",
                           "approved": False})
            assert "error" in bad
        finally:
            lb.stop()
