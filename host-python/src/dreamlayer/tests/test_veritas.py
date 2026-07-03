"""test_veritas.py — the live fact-checker.

Veritas watches a conversation and flags two things: when a speaker contradicts
their *own* earlier words (offline, from the ledger) and when a checkable claim
fails a world check (Brain/cloud seam). It fires sparingly and never on opinions.
"""
from __future__ import annotations

from dreamlayer.orchestrator.veritas import Veritas, detect_claim
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def _factcards(br):
    return [f for f in br.raw if f.get("t") == "card" and f.get("type") == "FactCheckCard"]


# -- claim detection: only assertive, checkable statements --------------------

def test_only_checkable_claims_are_flagged():
    assert detect_claim("The tower is 330 meters tall.").checkable        # numeric
    assert detect_claim("Canberra is the capital of Australia.").checkable  # factual
    assert not detect_claim("What time is the meeting?").checkable        # a question
    assert not detect_claim("I think it's probably fine.").checkable      # hedged
    assert not detect_claim("Let's grab lunch.").checkable                # small talk


# -- self-contradiction: no network needed ------------------------------------

def test_speaker_contradicts_their_own_earlier_words():
    v = Veritas()
    prior = ["The deal closed at 2 million."]
    res = v.check("Actually the deal closed at 3 million.", speaker="Marcus",
                  prior=prior, now=100.0)
    assert res.fired and res.verdict == "self_contradiction"
    assert res.card is not None and res.card["type"] == "FactCheckCard"


def test_no_prior_no_contradiction():
    v = Veritas()
    res = v.check("The deal closed at 3 million.", speaker="Marcus",
                  prior=[], now=100.0)
    assert not res.fired


# -- world check: the verifier seam -------------------------------------------

def test_disputed_claim_from_the_verifier_fires():
    def verify(_claim):
        return {"verdict": "disputed", "basis": "Canberra is the capital.",
                "confidence": 0.95}
    v = Veritas(verify_fn=verify)
    res = v.check("Sydney is the capital of Australia.", speaker="Dana", now=1.0)
    assert res.fired and res.verdict == "disputed"
    assert "Canberra" in res.basis


def test_a_quiet_supported_claim_does_not_interrupt():
    def verify(_claim):
        return {"verdict": "supported", "basis": "correct", "confidence": 0.6}
    v = Veritas(verify_fn=verify)
    res = v.check("Paris is the capital of France.", speaker="Dana", now=1.0)
    assert not res.fired          # weak corroboration stays out of the way


# -- pacing: one verdict per speaker per cooldown -----------------------------

def test_cooldown_holds_a_second_verdict():
    v = Veritas(per_speaker_cooldown_s=45.0)
    prior = ["The deal closed at 2 million."]
    a = v.check("The deal closed at 3 million.", speaker="Marcus", prior=prior, now=100.0)
    b = v.check("The deal closed at 4 million.", speaker="Marcus",
                prior=prior + ["The deal closed at 3 million."], now=120.0)
    assert a.fired and not b.fired
    c = v.check("The deal closed at 5 million.", speaker="Marcus",
                prior=prior, now=200.0)          # cooldown elapsed
    assert c.fired


# -- end to end through the orchestrator --------------------------------------

def test_orchestrator_flags_a_live_contradiction():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.set_factcheck(True)
    orc.ingest_caption("The deal closed at 2 million.", speaker="Marcus", ts=100.0)
    orc.ingest_caption("Actually it closed at 3 million.", speaker="Marcus", ts=140.0)
    cards = _factcards(br)
    assert cards and cards[-1]["verdict"] == "self_contradiction"


def test_factcheck_is_off_by_default():
    br = FakeBridge()
    orc = Orchestrator(br)
    assert orc.factcheck_on is False
    orc.ingest_caption("It was 2 million.", speaker="Marcus", ts=100.0)
    orc.ingest_caption("It was 3 million.", speaker="Marcus", ts=140.0)
    assert not _factcards(br)
