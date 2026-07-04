"""test_people_screen.py — the phone People screen's data path.

The hub builds a social-memory snapshot (everyone met + notes/relation/debts),
mirrors it to the Brain (like the profile), and the phone reads + edits it.
"""
from __future__ import annotations

import numpy as np

from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.ai_brain.server import Brain
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def _frame(v=0.8):
    return np.full((32, 32), v, dtype=np.float32)


def _seed_hub():
    orc = Orchestrator(FakeBridge())
    orc.handle_voice("this is my colleague Sarah, she runs marketing", frame=_frame(0.8))
    orc.handle_voice("Sarah owes me $20")
    orc.ingest_caption("the Q3 deck is ready", speaker="Sarah")
    return orc


# -- hub builds the snapshot --------------------------------------------------

def test_social_people_snapshot():
    orc = _seed_hub()
    people = orc.social_people()
    assert len(people) == 1
    p = people[0]
    assert p["name"] == "Sarah" and p["relation"] == "colleague"
    assert "she runs marketing" in p["notes"]
    assert p["debts"] == ["owes you $20"]
    assert p["last_seen"]                       # from the ledger
    assert "q3" in p["topics"]


def test_publish_people_posts_snapshot():
    orc = _seed_hub()
    orc.brain_url = "http://mac"                 # pretend a Brain is paired
    sent = {}
    def fake_post(url, body, token=None):
        sent["url"] = url; sent["body"] = body; return {"ok": True}
    orc.publish_people(http_post=fake_post)
    assert sent["url"].endswith("/dreamlayer/social/people")
    assert sent["body"]["people"][0]["name"] == "Sarah"


# -- Brain mirror + edits -----------------------------------------------------

def test_brain_receives_and_serves_people(tmp_path):
    orc = _seed_hub()
    b = Brain(tmp_path)
    b.receive_people({"people": orc.social_people()})
    state = b.social_people_state()
    assert [p["name"] for p in state["people"]] == ["Sarah"]


def test_brain_edit_person(tmp_path):
    orc = _seed_hub()
    b = Brain(tmp_path)
    b.receive_people({"people": orc.social_people()})
    cid = b.social_people[0]["contact_id"]

    # add a note
    r = b.edit_person({"contact_id": cid, "action": "note", "value": "likes tea"})
    assert r["ok"] and "likes tea" in r["person"]["notes"]
    # fix the relationship
    r = b.edit_person({"contact_id": cid, "action": "relation", "value": "friend"})
    assert r["person"]["relation"] == "friend"
    # settle the debt
    r = b.edit_person({"contact_id": cid, "action": "settle"})
    assert r["person"]["debts"] == []
    # remove a note
    r = b.edit_person({"contact_id": cid, "action": "remove_note", "value": "likes tea"})
    assert "likes tea" not in r["person"]["notes"]
    # persisted across a reload
    b2 = Brain(tmp_path)
    assert b2.social_people[0]["relation"] == "friend"


def test_brain_edit_unknown_person(tmp_path):
    b = Brain(tmp_path)
    assert b.edit_person({"contact_id": "nope", "action": "note", "value": "x"})["ok"] is False


def test_people_endpoints_over_http(tmp_path):
    import json, threading, urllib.request
    from dreamlayer.ai_brain.server.server import make_brain_server
    orc = _seed_hub()
    b = Brain(tmp_path)
    srv = make_brain_server(b, host="127.0.0.1", port=7802)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tok = b.config.token

    def call(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request("http://127.0.0.1:7802" + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if tok:
            req.add_header("X-DreamLayer-Token", tok)
        return json.loads(urllib.request.urlopen(req).read())

    try:
        assert call("POST", "/dreamlayer/social/people", {"people": orc.social_people()})["ok"]
        got = call("GET", "/dreamlayer/social/people")
        assert got["people"][0]["name"] == "Sarah"
        cid = got["people"][0]["contact_id"]
        edited = call("POST", "/dreamlayer/social/people/edit",
                      {"contact_id": cid, "action": "settle"})
        assert edited["ok"] and edited["person"]["debts"] == []
    finally:
        srv.shutdown()


# -- typed-voice parity: note / meet / debt / settle on the Brain mirror ------

def _brain_with_sarah(tmp_path):
    orc = _seed_hub()
    b = Brain(tmp_path)
    b.receive_people({"people": orc.social_people()})
    return b


def test_voice_social_note_and_debt_and_settle(tmp_path):
    b = _brain_with_sarah(tmp_path)
    r = b.voice_social("note_person", {"who": "Sarah", "note": "loves oat milk"})
    assert r["ok"] and "Sarah" in r["say"]
    r = b.voice_social("debt", {"who": "Sarah", "dir": "they_owe", "what": "$40"})
    assert r["ok"] and "owes you $40" in r["say"]
    person = b._find_person("Sarah")
    assert "loves oat milk" in person["notes"] and "owes you $40" in person["debts"]
    r = b.voice_social("debt_settle", {"who": "Sarah"})
    assert r["ok"] and b._find_person("Sarah")["debts"] == []


def test_voice_social_meet_creates_a_person(tmp_path):
    b = Brain(tmp_path)
    r = b.voice_social("meet_person", {"who": "Priya", "relation": "neighbor", "note": "two kids"})
    assert r["ok"]
    p = b._find_person("Priya")
    assert p and p["relation"] == "neighbor" and "two kids" in p["notes"]


def test_voice_social_unknown_person_is_gentle(tmp_path):
    b = _brain_with_sarah(tmp_path)
    r = b.voice_social("debt", {"who": "Zoltan", "dir": "they_owe", "what": "$5"})
    assert r["ok"] is False and "don't know" in r["say"].lower()


def test_voice_endpoint_parity_over_http(tmp_path):
    import json, threading, urllib.request
    from dreamlayer.ai_brain.server.server import make_brain_server
    b = _brain_with_sarah(tmp_path)
    srv = make_brain_server(b, host="127.0.0.1", port=7803)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tok = b.config.token

    def voice(text):
        data = json.dumps({"text": text}).encode()
        req = urllib.request.Request("http://127.0.0.1:7803/dreamlayer/voice",
                                     data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if tok:
            req.add_header("X-DreamLayer-Token", tok)
        return json.loads(urllib.request.urlopen(req).read())

    try:
        assert "remember" in voice("remember Sarah's a climber")["say"].lower()
        assert "owes you $15" in voice("Sarah owes me $15")["say"]
        assert "owes you $15" in b._find_person("Sarah")["debts"]   # appended
        assert "climber" in " ".join(b._find_person("Sarah")["notes"])
    finally:
        srv.shutdown()
