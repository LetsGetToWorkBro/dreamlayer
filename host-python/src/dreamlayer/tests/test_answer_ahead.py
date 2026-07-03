"""test_answer_ahead.py — the answer-ahead copilot.

The glasses overhear a question aimed at you and surface the answer from your own
knowledge, in time to say it yourself. It stays quiet on rhetorical asides and on
anything it can't answer confidently.
"""
from __future__ import annotations

from dreamlayer.orchestrator.answer_ahead import AnswerAhead, detect_question
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def _cards(br):
    return [f for f in br.raw if f.get("t") == "card" and f.get("type") == "AnswerAheadCard"]


# -- question detection -------------------------------------------------------

def test_detects_a_question_aimed_at_you():
    q = detect_question("When did you last see Marcus?", speaker="Dana")
    assert q.is_question and q.directed_at_me and q.kind == "personal"


def test_detects_a_plain_factual_question():
    q = detect_question("What year did the Berlin Wall fall?", speaker="Dana")
    assert q.is_question and q.kind == "factual"


def test_ignores_rhetorical_and_tag_questions():
    assert not detect_question("That was wild, right?", speaker="Dana").is_question
    assert not detect_question("You know?", speaker="Dana").is_question
    assert not detect_question("Let's get lunch.", speaker="Dana").is_question


# -- fetch + surface ----------------------------------------------------------

def test_surfaces_a_confident_answer():
    def answer(_q):
        return {"text": "March 14th.", "confidence": 0.8, "source": "your files"}
    aa = AnswerAhead(answer_fn=answer)
    p = aa.consider("When did we last ship to Denver?", speaker="Priya", now=1.0)
    assert p.fired and p.answer == "March 14th."
    assert p.card is not None and p.card["type"] == "AnswerAheadCard"


def test_stays_quiet_on_a_low_confidence_answer():
    def answer(_q):
        return {"text": "maybe?", "confidence": 0.2, "source": ""}
    aa = AnswerAhead(answer_fn=answer)
    assert not aa.consider("What's the capital of Bhutan?", now=1.0).fired


def test_cooldown_paces_prompts():
    def answer(_q):
        return {"text": "yes.", "confidence": 0.9, "source": "you"}
    aa = AnswerAhead(answer_fn=answer, cooldown_s=20.0)
    assert aa.consider("Did you email Sam?", now=100.0).fired
    assert not aa.consider("What did you decide?", now=110.0).fired      # cooling
    assert aa.consider("When is the review?", now=130.0).fired           # elapsed


# -- end to end through the orchestrator --------------------------------------

def test_orchestrator_pre_answers_an_overheard_question():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.answer_ahead.answer_fn = lambda _q: {
        "text": "March 14th, two pallets.", "confidence": 0.8, "source": "files"}
    orc.set_copilot(True)
    orc.ingest_caption("When did we last ship to Denver?", speaker="Priya", ts=1.0)
    cards = _cards(br)
    assert cards and cards[-1]["primary"].startswith("March 14th")


def test_copilot_ignores_your_own_lines_and_is_off_by_default():
    br = FakeBridge()
    orc = Orchestrator(br)
    assert orc.copilot_on is False
    orc.answer_ahead.answer_fn = lambda _q: {"text": "x", "confidence": 0.9, "source": ""}
    orc.set_copilot(True)
    orc.ingest_caption("What did I decide again?", speaker="", ts=1.0)   # your own voice
    assert not _cards(br)
