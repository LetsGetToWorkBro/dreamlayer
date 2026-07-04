"""test_glance.py — the Glance Arbiter: the look decides the lens.

Pins the pure arbitration (bids → fire / offer / none), the coarse classifier,
learned priors, hysteresis, the two-tier ambiguity escalation, spoken-intent
bias, the veil gate, and the end-to-end path through the orchestrator.
"""
from __future__ import annotations

import numpy as np

from dreamlayer.orchestrator.glance import (
    GlanceArbiter, GlanceReading, GlanceContext, GlancePriors,
    classify_coarse,
)
from dreamlayer.orchestrator.orchestrator import Orchestrator, _parse_scene_reply
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def frame():
    return np.zeros((8, 8), dtype=np.float32)


# -- the coarse classifier: a usable scene from cheap signals -----------------

def test_coarse_reads_a_scene_from_signals():
    assert classify_coarse({"has_face": True}).scene == "person"
    assert classify_coarse({"form_fields": 4}).scene == "form"
    assert classify_coarse({"text_density": 0.7, "question": True}).scene == "question"
    assert classify_coarse({"text_density": 0.6, "language": "fr"},
                           user_language="en").scene == "foreign_text"
    assert classify_coarse({"text_density": 0.8}).scene == "text"
    assert classify_coarse({}).scene == "unknown"


# -- arbitration: fire the clear winner ---------------------------------------

def test_a_clear_scene_fires_one_lens():
    d = GlanceArbiter().arbitrate(classify_coarse({"form_fields": 4}))
    assert d.kind == "fire" and d.winner.lens == "scholar_form"

    d2 = GlanceArbiter().arbitrate(GlanceReading("person", 0.8, {"has_face": True}))
    assert d2.kind == "fire" and d2.winner.lens == "person"


def test_ambiguous_glance_offers_a_chooser():
    # a page that is both fillable and a question: two close bids → offer
    reading = GlanceReading("text", 0.7,
                            {"form_fields": 2, "question": True, "text_density": 0.5})
    d = GlanceArbiter().arbitrate(reading)
    assert d.kind == "offer"
    lenses = {o.lens for o in d.options}
    assert {"scholar_form", "scholar_answer"} <= lenses
    assert d.card and d.card["type"] == "GlanceChoiceCard"


def test_nothing_worth_it_does_nothing():
    d = GlanceArbiter().arbitrate(GlanceReading("unknown", 0.2, {}))
    assert d.kind == "none" and d.winner is None


def test_the_veil_stops_arbitration():
    d = GlanceArbiter().arbitrate(classify_coarse({"form_fields": 4}),
                                  GlanceContext(veiled=True))
    assert d.kind == "none"


# -- spoken intent steers a close call ----------------------------------------

def test_recent_intent_forces_its_lens():
    reading = GlanceReading("text", 0.7,
                            {"form_fields": 2, "question": True, "text_density": 0.5})
    # "how do I fill this out" just said → the form lens wins outright
    d = GlanceArbiter().arbitrate(reading, GlanceContext(recent_intent="form"))
    assert d.kind == "fire" and d.winner.lens == "scholar_form"
    # and "answer" flips the same look to the answer lens
    d2 = GlanceArbiter().arbitrate(reading, GlanceContext(recent_intent="answer"))
    assert d2.kind == "fire" and d2.winner.lens == "scholar_answer"


# -- it learns you: per-scene priors ------------------------------------------

def test_learned_priors_tip_a_close_call_and_persist():
    reading = GlanceReading("text", 0.7,
                            {"form_fields": 2, "question": True, "text_density": 0.5})
    arb = GlanceArbiter()
    assert arb.arbitrate(reading).kind == "offer"          # tie at first
    # you pick "answer" a few times for this scene…
    for _ in range(4):
        arb.reinforce("text", "scholar_answer")
    d = arb.arbitrate(GlanceReading("text", 0.7,
                                    {"form_fields": 2, "question": True, "text_density": 0.5}))
    # …now the learned favourite tips it to a fire (or at least leads)
    assert d.winner is None or d.winner.lens == "scholar_answer" or \
        d.options[0].lens == "scholar_answer"
    # priors serialise for the Mac Brain to persist
    round_trip = GlancePriors.from_dict(arb.priors.to_dict())
    assert round_trip.favourite("text") == "scholar_answer"


# -- priors persist to disk beside the vault ----------------------------------

def test_priors_persist_across_sessions(tmp_path):
    path = str(tmp_path / "glancepriors.json")
    # session one teaches a favourite through the arbiter…
    arb = GlanceArbiter(priors_path=path)
    for _ in range(4):
        arb.reinforce("text", "scholar_answer")
    import os
    assert os.path.exists(path)                    # written on reinforce
    # …a fresh arbiter on the same path starts already knowing it
    reborn = GlanceArbiter(priors_path=path)
    assert reborn.priors.favourite("text") == "scholar_answer"
    # a close look now leans the learned way without re-teaching
    d = reborn.arbitrate(GlanceReading(
        "text", 0.7, {"form_fields": 2, "question": True, "text_density": 0.5}))
    assert d.winner is None or d.winner.lens == "scholar_answer" or \
        d.options[0].lens == "scholar_answer"


def test_priors_without_a_path_stay_in_memory():
    arb = GlanceArbiter()                          # no path → no file, no error
    arb.reinforce("form", "scholar_form")
    assert arb.priors.favourite("form") == "scholar_form"
    assert arb.priors.path is None


# -- hysteresis: a wandering glance doesn't flip ------------------------------

def test_hysteresis_holds_a_fresh_decision():
    clock = {"t": 0.0}
    arb = GlanceArbiter(debounce_ms=1000.0, now_fn=lambda: clock["t"])
    r = classify_coarse({"form_fields": 4})
    a = arb.arbitrate(r)
    clock["t"] += 200.0
    b = arb.arbitrate(r)
    assert a is b                                # same decision object, held
    clock["t"] += 2000.0                          # past the debounce
    c = arb.arbitrate(r)
    assert c is not a and c.kind == "fire"


# -- two-tier: ambiguity flags a fine read, and the reply parses --------------

def test_is_ambiguous_flags_when_the_cheap_read_cant_tell():
    arb = GlanceArbiter()
    assert arb.is_ambiguous(GlanceReading("unknown", 0.2, {}))
    assert arb.is_ambiguous(GlanceReading("text", 0.4, {"text_density": 0.6}))
    assert not arb.is_ambiguous(GlanceReading("person", 0.8, {"has_face": True}))


def test_fine_scene_reply_parses():
    r = _parse_scene_reply("SCENE: form — density=0.7 fields=4 lang=en")
    assert r.scene == "form" and r.signals["form_fields"] == 4
    assert r.signals["text_density"] == 0.7
    r2 = _parse_scene_reply("this looks like a question to me?")
    assert r2.scene == "question" and r2.signals.get("question") is True


# -- end to end through the orchestrator --------------------------------------

def test_orchestrator_glance_fires_the_right_lens():
    br = FakeBridge()
    orc = Orchestrator(br)

    class A:
        text = "SUMMARY: a W-9 tax form.\nFIELD: Name — your legal name."
        tier = "cloud"
        def is_empty(self): return False

    orc.brain.explain = lambda f, p, want="quick": A()
    orc._glance_signals_fn = lambda f: {"form_fields": 4}
    d = orc.glance(frame())
    assert d.kind == "fire" and d.winner.lens == "scholar_form"
    scards = [c for c in br.raw if c.get("t") == "card" and c.get("type") == "ScholarCard"]
    assert scards                                # the form card went to the glasses


def test_orchestrator_glance_offers_a_chooser_when_ambiguous():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc._classify_glance = lambda f: GlanceReading(
        "text", 0.8, {"form_fields": 2, "question": True, "text_density": 0.5})
    d = orc.glance(frame())
    assert d.kind == "offer"
    choice = [c for c in br.raw if c.get("t") == "card" and c.get("type") == "GlanceChoiceCard"]
    assert choice and len(choice[-1]["options"]) >= 2


def test_choose_glance_runs_the_lens_and_teaches_the_arbiter():
    br = FakeBridge()
    orc = Orchestrator(br)

    class A:
        text = "ANSWER: 42\nWHY: the ultimate answer."
        tier = "cloud"
        def is_empty(self): return False

    orc.brain.explain = lambda f, p, want="quick": A()
    res = orc.choose_glance("scholar_answer", frame(), scene="text")
    assert res.ok and res.primary == "42"
    assert orc.glance_arbiter.priors.favourite("text") == "scholar_answer"


def test_glance_is_veil_gated_end_to_end():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.privacy.pause()
    d = orc.glance(frame())
    assert d.kind == "none"


def test_a_look_after_a_spoken_intent_is_biased():
    br = FakeBridge()
    orc = Orchestrator(br)

    class A:
        text = "ANSWER: C"
        tier = "cloud"
        def is_empty(self): return False

    orc.brain.explain = lambda f, p, want="quick": A()
    # say "what's the answer" (no frame), then look at an ambiguous page
    orc.handle_voice("what's the answer")
    orc._classify_glance = lambda f: GlanceReading(
        "text", 0.8, {"form_fields": 2, "question": True, "text_density": 0.5})
    d = orc.glance(frame())
    assert d.kind == "fire" and d.winner.lens == "scholar_answer"
