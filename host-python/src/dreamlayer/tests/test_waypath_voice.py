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
    it = parse_intent("Hey Juno, I parked on level 3")
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


def test_stash_stands_down_for_people_events_idioms():
    """The review pass's headline finding: "my X is at Y" phrasings about
    people, events, and idioms must NOT become stashes — a wrong stash is
    spoken back as a confident confirmation and lands in Memories."""
    not_stash = [
        "my brother is in town", "my mom is in the hospital",
        "my sister is at Stanford", "my son is at soccer practice",
        "my wife is at work", "my meeting is at 3", "my flight is at noon",
        "my birthday is on Friday", "our anniversary is on Tuesday",
        "I left my job at Google", "I left my wife at the altar",
        "I dropped my kids at school", "I dropped the ball on that project",
        "I left a message on her voicemail", "I put my faith in you",
        "I set my phone on silent", "I set the meeting at 3pm",
        "I left early on Friday", "I left my heart in San Francisco",
        "note that my brother is in town",
    ]
    for line in not_stash:
        assert parse_intent(line).kind != "stash", line


def test_stash_duration_less_timer_words_are_not_stashes():
    # "put a timer on the oven" must not file a "timer" at "the oven"
    assert parse_intent("put a timer on the oven").kind != "stash"
    assert parse_intent("set a timer on the counter").kind != "stash"
    # and the clock phrasing still routes to clock
    assert parse_intent("put a clock on the hud").kind == "clock"


def test_stash_degenerate_parking_is_ignored():
    assert parse_intent("I parked the car").kind != "stash"       # no place
    assert parse_intent("I parked illegally").kind != "stash"     # not a place


def test_stash_natural_variants_parse():
    it = parse_intent("my car's in the garage")                   # contraction
    assert it.kind == "stash" and it.args["subject"] == "car"
    assert parse_intent("I'm parked on level 3").kind == "stash"
    assert parse_intent("we parked at the far end").kind == "stash"
    it = parse_intent("I left my bike downstairs")                # adverb place
    assert it.kind == "stash" and it.args["place"] == "downstairs"


def test_locate_natural_variants_parse():
    assert parse_intent("where are my keys").kind == "locate"
    it = parse_intent("where did I park")
    assert it.kind == "locate" and it.args["subject"] == "car"
    assert parse_intent("where did I park the car").kind == "locate"
    assert parse_intent("where am I parked").kind == "locate"


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


def test_hub_memory_writes_refuse_under_incognito_flag():
    """"Go incognito" promises a session that keeps nothing — the deliberate
    memory writes (stash, debts, notes, meet) must refuse under the flag, not
    only under the long-press veil."""
    orc = Orchestrator(FakeBridge())
    orc.set_incognito(True)
    assert orc.handle_voice("I left my bike at the rack")["ok"] is False
    assert orc.handle_voice("Marcus owes me $20")["ok"] is False
    # asking your brain still works in incognito — only writes are refused
    r = orc.handle_voice("where's my bike?")
    assert "incognito" not in (r.get("say") or "").lower()
    orc.set_incognito(False)
    assert orc.handle_voice("I left my bike at the rack")["ok"] is True


def test_juno_wrapper_speaks_locate():
    orc = Orchestrator(FakeBridge())
    orc.ask_juno("I left my bike at the north rack")
    out = orc.ask_juno("where's my bike?")
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
