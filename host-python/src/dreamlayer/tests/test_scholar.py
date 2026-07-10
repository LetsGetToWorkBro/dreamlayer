"""test_scholar.py — Scholar: answer a question, fill a form, or plain-word it.

Scholar reads what you look at through the Brain's vision tier and hands it
back understood. These pin the three modes, the tight reply grammar, the
honest 'no brain' fallback, the veil gate, the voice intents, and the
end-to-end path through the orchestrator with an injected reader.
"""
from __future__ import annotations

import numpy as np

from dreamlayer.orchestrator.scholar import Scholar
from dreamlayer.orchestrator.voice import parse_intent
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def frame():
    return np.zeros((8, 8), dtype=np.float32)


# -- the three reads, from a tight reply grammar ------------------------------

def test_answer_reads_the_verdict_and_working():
    reply = "ANSWER: 1789\nWHY: the French Revolution began that year."
    sch = Scholar(read_fn=lambda f, p: reply)
    r = sch.answer(frame(), question="what year?")
    assert r.ok and r.mode == "answer"
    assert r.primary == "1789"
    assert "French Revolution" in r.detail
    assert r.card["type"] == "ScholarCard" and r.card["eyebrow"] == "ANSWER"


def test_answer_passes_a_spoken_question_through():
    seen = {}
    def read(f, prompt):
        seen["prompt"] = prompt
        return "ANSWER: C"
    Scholar(read_fn=read).answer(frame(), question="which option is right?")
    assert "which option is right?" in seen["prompt"]


def test_hedged_answer_lowers_confidence():
    hi = Scholar(read_fn=lambda f, p: "ANSWER: Paris").answer(frame())
    lo = Scholar(read_fn=lambda f, p: "ANSWER: maybe Lyon, not sure").answer(frame())
    assert hi.confidence > lo.confidence


def test_form_spells_out_each_field():
    reply = (
        "SUMMARY: US passport renewal form DS-82.\n"
        "FIELD: Full name — your name exactly as on your last passport.\n"
        "FIELD: Date of birth — MM/DD/YYYY as on your birth certificate.\n"
        "FIELD: Mailing address — where the new passport should be sent."
    )
    sch = Scholar(read_fn=lambda f, p: reply)
    r = sch.form(frame(), purpose="renew my passport")
    assert r.ok and r.mode == "form"
    assert "passport renewal" in r.primary.lower()
    labels = [x["label"] for x in r.items]
    assert "Full name" in labels and "Date of birth" in labels
    guide = {x["label"]: x["guidance"] for x in r.items}
    assert "last passport" in guide["Full name"]


def test_form_purpose_reaches_the_reader():
    seen = {}
    Scholar(read_fn=lambda f, p: (seen.__setitem__("p", p), "FIELD: x — y")[1]) \
        .form(frame(), purpose="claim the home-office deduction")
    assert "home-office deduction" in seen["p"]


def test_explain_puts_dense_text_in_plain_words():
    reply = ("GIST: This clause lets them auto-renew you every year unless you "
             "cancel 30 days ahead.\n- You are billed until you cancel.\n"
             "- Cancelling is only by mail.")
    sch = Scholar(read_fn=lambda f, p: reply)
    r = sch.explain(frame())
    assert r.ok and r.mode == "explain"
    assert "auto-renew" in r.primary
    assert any("cancel" in pt for pt in r.items)
    assert len(r.items) == 2


# -- the honest fallback ------------------------------------------------------

def test_no_brain_returns_an_unavailable_card_not_a_guess():
    sch = Scholar(read_fn=None)
    for r in (sch.answer(frame()), sch.form(frame()), sch.explain(frame())):
        assert not r.ok
        assert r.card["unavailable"] is True
        assert r.primary == ""            # never invents an answer


def test_a_blank_or_garbled_read_is_unavailable():
    assert not Scholar(read_fn=lambda f, p: "   ").answer(frame()).ok
    assert not Scholar(read_fn=lambda f, p: "no tags here at all").form(frame()).ok


# -- voice intents ------------------------------------------------------------

def test_voice_routes_the_scholar_intents():
    assert parse_intent("Hey Juno, what's the answer?").kind == "scholar"
    assert parse_intent("answer this question").args["mode"] == "answer"
    assert parse_intent("how do I fill this out?").args["mode"] == "form"
    fill = parse_intent("how do I fill this out to renew my license")
    assert fill.args["mode"] == "form" and "renew my license" in fill.args["purpose"]
    assert parse_intent("explain this").args["mode"] == "explain"
    assert parse_intent("what does this mean?").args["mode"] == "explain"
    assert parse_intent("put this in plain english").args["mode"] == "explain"
    # ordinary asks are untouched
    assert parse_intent("what did Marcus need?").kind == "recall"
    assert parse_intent("what's the capital of France").kind == "ask"


# -- end to end through the orchestrator --------------------------------------

def test_orchestrator_reads_an_answer_onto_the_glasses():
    br = FakeBridge()
    orc = Orchestrator(br)

    class A:
        text = "ANSWER: 42\nWHY: the ultimate answer."
        tier = "cloud"
        def is_empty(self): return False

    orc.brain.explain = lambda f, p, want="quick": A()
    res = orc.read_answer(frame())
    assert res.ok and res.primary == "42"
    scards = [c for c in br.raw if c.get("t") == "card" and c.get("type") == "ScholarCard"]
    assert scards and scards[-1]["primary"] == "42"


def test_orchestrator_scholar_is_veil_gated():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.brain.explain = lambda f, p, want="quick": None
    orc.privacy.pause()                    # veil down
    res = orc.read_answer(frame())
    assert not res.ok                       # the ear/eye is closed


def test_handle_voice_scholar_uses_the_frame():
    br = FakeBridge()
    orc = Orchestrator(br)

    class A:
        text = "SUMMARY: a W-9 tax form.\nFIELD: Name — your legal name."
        tier = "cloud"
        def is_empty(self): return False

    orc.brain.explain = lambda f, p, want="quick": A()
    out = orc.handle_voice("how do I fill this out", frame=frame())
    assert out["intent"] == "scholar" and out["mode"] == "form" and out["ok"] is True
    # with no frame, it stays a structured intent (device pairs the frame)
    out2 = orc.handle_voice("what's the answer")
    assert out2["intent"] == "scholar" and out2["ok"] is False
