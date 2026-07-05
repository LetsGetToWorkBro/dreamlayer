"""test_waypath_voice.py — the "where did I leave my …" loop end to end.

Three gaps this closes (they were parsed but never executed):
  • `stash` — "I left my bike at the north rack" drops a Waypath anchor.
  • `locate` — "where's my bike?" reads it back (was answering "I don't know").
  • `missed` / `reply` — the Brain now actually answers these.
"""
from __future__ import annotations

from dreamlayer.orchestrator.voice import parse_intent
from dreamlayer.orchestrator.waypath import WaypathLens
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.ai_brain.server import Brain
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


# -- grammar ------------------------------------------------------------------

def test_stash_grammar():
    it = parse_intent("I left my bike at the north rack")
    assert it.kind == "stash" and it.args["subject"] == "bike"
    assert it.args["place"] == "the north rack"


def test_stash_grammar_parked():
    it = parse_intent("Hey Oracle, I parked on level 3")
    assert it.kind == "stash" and it.args["subject"] == "the car"
    assert it.args["place"] == "level 3"


def test_stash_grammar_my_thing_is():
    it = parse_intent("my keys are on the desk")
    assert it.kind == "stash" and it.args["subject"] == "keys"
    assert it.args["place"] == "the desk"


def test_stash_grammar_remember_prefix():
    it = parse_intent("remember I put my passport in the drawer")
    assert it.kind == "stash" and it.args["subject"] == "passport"
    assert it.args["place"] == "the drawer"


def test_locate_grammar_still_parses():
    it = parse_intent("where's my bike?")
    assert it.kind == "locate" and it.args["subject"] == "bike"


def test_stash_does_not_eat_person_notes():
    # a note about a person must still win over stash
    assert parse_intent("remember Maya's into climbing").kind == "note_person"
    # and a wearer fact is neither
    assert parse_intent("remember I prefer aisle seats").kind == "ask"


# -- lens: place-only anchors -------------------------------------------------

def test_place_only_anchor():
    wp = WaypathLens()
    wp.remember_place("bike", "the north rack")
    cue = wp.locate("bike")
    assert cue.found and cue.text == "at the north rack"
    assert wp.to_hud_card(cue)["detail"] == "at the north rack"


def test_place_only_and_bearing_coexist():
    wp = WaypathLens()
    wp.remember_place("bike", "the rack")
    wp.remember("keys", bearing_deg=90, distance_m=12)
    assert wp.locate("bike").text == "at the rack"
    assert wp.locate("keys").text == "12m to your right"


# -- hub: stash then locate ---------------------------------------------------

def test_hub_stash_then_locate():
    orc = Orchestrator(FakeBridge())
    r = orc.handle_voice("I left my bike at the north rack")
    assert r["ok"] and "north rack" in r["say"]
    r2 = orc.handle_voice("where's my bike?")
    assert r2["ok"] and r2["found"] and "north rack" in r2["say"]


def test_hub_locate_unknown_is_honest():
    orc = Orchestrator(FakeBridge())
    r = orc.handle_voice("where's my umbrella?")
    assert r["ok"] is False and "umbrella" in r["say"]


def test_hub_stash_veil_gated():
    orc = Orchestrator(FakeBridge())
    orc.privacy.pause()                        # Veil down
    r = orc.handle_voice("I left my bike at the rack")
    assert r["ok"] is False and "incognito" in r["say"].lower()


def test_oracle_wrapper_speaks_locate():
    orc = Orchestrator(FakeBridge())
    orc.ask_oracle("I left my bike at the north rack")
    out = orc.ask_oracle("where's my bike?")
    assert "north rack" in out["text"]         # not persona.dunno()


# -- Brain: self-contained stash/locate + missed + reply ----------------------

def test_brain_stash_then_locate(tmp_path):
    b = Brain(tmp_path)
    assert b.waypath_stash("bike", "the north rack")["ok"]
    r = b.waypath_locate("bike")
    assert r["ok"] and r["found"] and "north rack" in r["say"]
    # persisted across a reload
    b2 = Brain(tmp_path)
    assert b2.waypath_locate("bike")["found"]


def test_brain_reply_stages_not_sends(tmp_path):
    b = Brain(tmp_path)
    r = b.voice_reply("Priya", "on my way")
    assert r["ok"] and r["to"] == "Priya" and r["text"] == "on my way"
    assert "Messages" in r["say"]


def test_brain_missed_empty(tmp_path):
    b = Brain(tmp_path)
    r = b.missed()
    assert r["ok"] and r["texts"] == 0 and "Nothing" in r["say"]


def test_voice_endpoint_stash_locate_missed_reply_over_http(tmp_path):
    import json, threading, urllib.request
    from dreamlayer.ai_brain.server.server import make_brain_server
    b = Brain(tmp_path)
    srv = make_brain_server(b, host="127.0.0.1", port=7804)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tok = b.config.token

    def voice(text):
        data = json.dumps({"text": text}).encode()
        req = urllib.request.Request("http://127.0.0.1:7804/dreamlayer/voice",
                                     data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if tok:
            req.add_header("X-DreamLayer-Token", tok)
        return json.loads(urllib.request.urlopen(req).read())

    try:
        assert voice("I left my bike at the north rack")["ok"]
        loc = voice("where's my bike?")
        assert loc["found"] and "north rack" in loc["say"]
        assert voice("what did I miss?")["intent"] == "missed"
        rep = voice("reply to Priya saying on my way")
        assert rep["intent"] == "reply" and rep["to"] == "Priya"
    finally:
        srv.shutdown()
