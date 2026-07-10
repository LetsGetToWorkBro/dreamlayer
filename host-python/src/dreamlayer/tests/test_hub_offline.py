"""test_hub_offline.py — the hub works with just the glasses, no Mac Brain.

"Phone as brain": the Orchestrator (the hub) drives the glasses over its bridge
with no brain_url set. Timers/clock, notes, debts, meet, and recall all run
on-device here — the Mac only adds file/mail search and heavier models.
"""
from __future__ import annotations

import numpy as np

from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.bridge.emulator_bridge import EmulatorBridge
from dreamlayer.social_lens.schema import ContactRecord
from dreamlayer.truth_lens.face_embed import FaceEmbedder


def _frame(v=0.8):
    return np.full((32, 32), v, dtype=np.float32)


def _embed(v=0.8):
    return FaceEmbedder(threshold=0.40).process_frame(_frame(v)).embedding


def _hub():
    orc = Orchestrator(EmulatorBridge())
    assert not orc.brain_url          # no Mac paired — hub + glasses only
    return orc


def _ftypes(br):
    return [f.get("t") for f in br.raw_frames]


# -- native timers deploy straight to the glasses, no Brain -------------------

def test_hub_sets_a_timer_on_the_glasses():
    orc = _hub()
    r = orc.handle_voice("Hey Juno, set a timer for 5 minutes")
    assert r["ok"] and "5 minutes" in r["say"]
    assert _ftypes(orc.bridge) == ["figment_put", "figment_swap"]


def test_hub_interval_and_stop():
    orc = _hub()
    r = orc.handle_voice("interval timer, 30 seconds on, 15 seconds off, 8 rounds")
    assert r["ok"] and "8 rounds" in r["say"]
    orc.bridge.raw_frames.clear()
    r = orc.handle_voice("stop the timer")
    assert r["ok"] and _ftypes(orc.bridge) == ["figment_revoke"]


def test_hub_clock_query_just_answers():
    orc = _hub()
    r = orc.handle_voice("what time is it")
    assert r["ok"] and "It's" in r["say"]
    assert orc.bridge.raw_frames == []          # no figment for a time query


def test_hub_clock_shows_a_figment():
    orc = _hub()
    r = orc.handle_voice("show me a clock")
    assert r["ok"]
    # put + swap + a text push seeding the time slot
    assert _ftypes(orc.bridge) == ["figment_put", "figment_swap", "figment_text"]


def test_hub_timer_veil_gated():
    orc = _hub()
    orc.privacy.pause()
    r = orc.handle_voice("set a timer for 2 minutes")
    assert r["ok"] is False and orc.bridge.raw_frames == []


# -- the rest of the social surface is hub-native too (no Brain) --------------

def test_hub_social_works_with_no_brain():
    orc = _hub()
    orc.handle_voice("this is my colleague Sarah, she runs marketing", frame=_frame(0.8))
    orc.handle_voice("Sarah owes me $20")
    res = orc.look_at_person(_frame(0.8))
    assert res["person"] == "Sarah"
    assert res["rescue"]["relation"] == "colleague"
    assert res["rescue"]["debts"] == ["owes you $20"]
    # publish_people is a no-op with no Brain, and must not raise
    assert orc.publish_people() is None
    # ...but the hub itself still has the whole snapshot for the glasses
    assert orc.social_people()[0]["name"] == "Sarah"
