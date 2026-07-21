"""Meeting mode — keep track of who's there and what was decided/committed.

Pure MeetingLog + the Brain's NL commands, all offline. The point is the action
items: a note like "I'll send the deck Friday" becomes a tracked commitment.
"""
from __future__ import annotations

import json
import threading
import urllib.request

from dreamlayer.ai_brain.server import Brain, make_brain_server
from dreamlayer.ai_brain.server.store import BrainConfig
from dreamlayer.social_lens.meeting import MeetingLog, extract_actions

TOKEN = "fern-vale"


class TestExtractActions:
    def test_commitments_are_pulled_with_a_due_date(self):
        acts = extract_actions("I'll send the deck Friday")
        assert acts and acts[0]["when"].lower() == "friday"

    def test_third_person_commitment(self):
        acts = extract_actions("Marcus will follow up next week")
        assert any("follow up" in a["text"].lower() for a in acts)

    def test_ordinary_talk_has_no_actions(self):
        assert extract_actions("the coffee here is good") == []


class TestMeetingLog:
    def test_lifecycle_and_actions(self, tmp_path):
        clock = [1000.0]
        log = MeetingLog(tmp_path / "m.json", now_fn=lambda: clock[0])
        m = log.start(title="Standup", attendees=["Sarah"])
        assert log.current()["id"] == m["id"]
        log.note("I'll book the room by Monday")
        live = log.current()
        assert live["actions"] and "book the room" in live["actions"][0]["text"].lower()
        assert live["actions"][0]["when"].lower().startswith("by mon")
        log.note("we decided to ship Tuesday")
        assert log.current()["decisions"]
        ended = log.end()
        assert ended["ended"] and log.current() is None

    def test_note_without_a_meeting_is_a_noop(self, tmp_path):
        log = MeetingLog(tmp_path / "m.json")
        assert log.note("I'll do the thing") is None

    def test_starting_closes_a_dangling_meeting(self, tmp_path):
        clock = [1.0]
        log = MeetingLog(tmp_path / "m.json", now_fn=lambda: clock[0])
        log.start(title="one")
        clock[0] = 2.0
        log.start(title="two")
        opens = [m for m in log.all() if not m.get("ended")]
        assert len(opens) == 1 and opens[0]["title"] == "two"


def _brain(tmp_path) -> Brain:
    d = tmp_path / "cfg"
    d.mkdir()
    BrainConfig(token=TOKEN).save(d)
    return Brain(d)


class TestBrainMeetings:
    def test_start_with_attendees_enrolls_them(self, tmp_path):
        b = _brain(tmp_path)
        r = b.meeting_command("start a meeting with Sarah and Marcus")
        assert r["intent"] == "meeting_start"
        assert set(r["meeting"]["attendees"]) == {"Sarah", "Marcus"}
        assert "Sarah" in b.known_names() and "Marcus" in b.known_names()

    def test_note_and_end_capture_actions(self, tmp_path):
        b = _brain(tmp_path)
        b.meeting_command("start a meeting")
        b.meeting_command("note that I'll email the report Friday")
        end = b.meeting_command("end the meeting")
        assert end["intent"] == "meeting_end"
        assert end["meeting"]["actions"]
        assert "1 action item" in end["say"]

    def test_introduction_during_a_meeting_adds_an_attendee(self, tmp_path):
        b = _brain(tmp_path)
        b.meeting_command("start a meeting")
        b.introduce("this is Priya")
        assert "Priya" in b.meetings()[0]["attendees"]

    def test_non_meeting_text_returns_none(self, tmp_path):
        b = _brain(tmp_path)
        assert b.meeting_command("what time is it") is None


class TestEndpoints:
    def test_ask_starts_a_meeting_and_meetings_endpoint_reads_it(self, tmp_path):
        b = _brain(tmp_path)
        server = make_brain_server(b, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        hdr = {"X-DreamLayer-Token": TOKEN, "Content-Type": "application/json"}
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            req = urllib.request.Request(
                base + "/dreamlayer/brain/ask",
                data=json.dumps({"query": "start a meeting with Dana"}).encode(),
                headers=hdr)
            with opener.open(req, timeout=10) as r:
                out = json.loads(r.read())
            assert out["intent"] == "meeting_start"
            req2 = urllib.request.Request(base + "/dreamlayer/meetings",
                                          headers={"X-DreamLayer-Token": TOKEN})
            with opener.open(req2, timeout=10) as r:
                got = json.loads(r.read())
            assert got["meetings"] and "Dana" in got["meetings"][0]["attendees"]
        finally:
            server.shutdown(); server.server_close()
