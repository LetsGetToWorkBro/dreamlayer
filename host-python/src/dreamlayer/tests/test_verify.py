"""test_verify.py — turning a claim into a verdict through the brain.

verify_claim shapes a verification question, sends it to a knowledge tier (local
first, cloud only if opted in — that gating lives in the router), and parses the
reply into supported / disputed / unverified for Veritas to act on.
"""
from __future__ import annotations

from dreamlayer.ai_brain.verify import parse_verdict, verify_claim
from dreamlayer.ai_brain.schema import Answer
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.orchestrator.veritas import Veritas
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


# -- parsing a tier's reply ---------------------------------------------------

def test_parses_a_disputed_verdict():
    v = parse_verdict("VERDICT: DISPUTED — Canberra is the capital, not Sydney.")
    assert v["verdict"] == "disputed"
    assert "Canberra" in v["basis"] and v["confidence"] >= 0.8


def test_parses_supported_and_unverified():
    assert parse_verdict("VERDICT: SUPPORTED — Paris is indeed the capital.")["verdict"] == "supported"
    u = parse_verdict("VERDICT: UNVERIFIED — not enough information.")
    assert u["verdict"] == "unverified" and u["confidence"] < 0.5


def test_a_hedged_verdict_is_softer():
    v = parse_verdict("VERDICT: DISPUTED — this might be wrong, hard to say.")
    assert v["verdict"] == "disputed" and v["confidence"] < 0.8


def test_no_verdict_word_returns_none():
    assert parse_verdict("I'm not really sure what you mean.") is None
    assert parse_verdict("") is None


# -- verify_claim over an injected ask ----------------------------------------

def test_verify_claim_routes_through_ask():
    def ask(_q):
        return Answer(text="VERDICT: DISPUTED — the tower is 330m, not 200m.",
                      tier="laptop", confidence=0.6)
    v = verify_claim("The Eiffel Tower is 200 meters tall.", ask)
    assert v["verdict"] == "disputed"


def test_verify_claim_silent_when_no_tier_answers():
    assert verify_claim("Anything.", lambda _q: None) is None


# -- Veritas end to end with the real verifier --------------------------------

def test_veritas_disputes_via_the_verifier():
    def ask(_q):
        return Answer(text="VERDICT: DISPUTED — Canberra is the capital.",
                      tier="cloud", confidence=0.6)
    v = Veritas(verify_fn=lambda c: verify_claim(c, ask))
    res = v.check("Sydney is the capital of Australia.", speaker="Dana", now=1.0)
    assert res.fired and res.verdict == "disputed"


# -- orchestrator wiring: _verify_claim uses the brain router -----------------

def test_orchestrator_verify_claim_uses_the_brain():
    orc = Orchestrator(FakeBridge())
    orc.brain.ask = lambda _q: Answer(
        text="VERDICT: DISPUTED — actually it was 1989.", tier="laptop")
    out = orc._verify_claim("The Berlin Wall fell in 1975.")
    assert out and out["verdict"] == "disputed"
