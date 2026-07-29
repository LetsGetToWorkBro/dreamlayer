"""Truth, checked live — `FactCheckCard` on the shipped Brain.

Two things had to be true before this could be wired at all, and only one of
them was about plumbing.

1. THE SCORER. `contradicts()` — shared by Candor, Provenance and Veritas —
   missed most real contradictions, including the example in its own module
   docstring ("the meeting was at 3, now you're saying 4") whenever a clock time
   was written the way people say it. Wiring a producer on top of that would
   have satisfied `hud_reachability.py` and blinded it. `test_consistency.py`
   carries the corpus that fix is held to.

2. THE OVERLAP. `Veritas.check` has two halves and the offline one — the
   self-contradiction pass — is ALREADY wired as Candor, over the same ring and
   the same scorer. So this runs the world half only. Two lenses, one job each.
"""
from __future__ import annotations

import tempfile

import pytest

from dreamlayer.ai_brain.server.server import Brain


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


def _pushes(brain):
    seen = []
    brain.push_event = lambda kind, card=None, veil_ok=False: (
        seen.append((kind, card)) or 1)
    return seen


def _answers(brain, reply):
    brain.ask = lambda *a, **k: reply


def test_a_disputed_claim_is_drawn(brain):
    ls = brain.lenses()
    _answers(brain, "VERDICT: DISPUTED — the wall fell in 1989, not 1975")
    seen = _pushes(brain)
    out = ls.fact_check("the Berlin Wall fell in 1975")
    assert out["fired"] is True
    assert out["verdict"] == "disputed"
    kind, card = seen[-1]
    assert kind == "fact_check" and card["type"] == "FactCheckCard"
    # the BASIS is the whole difference between a fact-check and an accusation
    assert "1989" in card["detail"]


def test_a_supported_claim_stays_quiet_unless_it_is_strong(brain):
    """Veritas only interrupts for a dispute, or a corroboration confident
    enough to be worth the glass. A hedged "probably right" is neither."""
    ls = brain.lenses()
    _answers(brain, "VERDICT: SUPPORTED — that seems probably about right")
    seen = _pushes(brain)
    out = ls.fact_check("the Berlin Wall fell in 1989")
    assert out["fired"] is False
    assert seen == []


def test_an_unreachable_tier_is_silence_not_an_error(brain):
    """`ask` returning nothing means no tier could answer — offline, cloud off,
    or incognito. That is "nothing worth interrupting for", not a failure."""
    ls = brain.lenses()
    _answers(brain, "")
    seen = _pushes(brain)
    out = ls.fact_check("something unknowable")
    assert out["fired"] is False and seen == []


def test_a_raising_tier_never_escapes(brain):
    ls = brain.lenses()

    def _boom(*a, **k):
        raise RuntimeError("no model")
    brain.ask = _boom
    out = ls.fact_check("the sky is green")
    assert out["fired"] is False


def test_the_veil_answers_nothing(brain):
    ls = brain.lenses()
    _answers(brain, "VERDICT: DISPUTED — no")
    brain.config.network_mode = "lan_only"
    seen = _pushes(brain)
    out = ls.fact_check("the Berlin Wall fell in 1975")
    assert out["fired"] is False and out["reason"] == "veiled"
    assert seen == []


def test_an_empty_claim_is_not_a_question(brain):
    ls = brain.lenses()
    assert ls.fact_check("")["fired"] is False
    assert ls.fact_check("   ")["fired"] is False


def test_it_does_not_re_fire_candors_half(brain):
    """The overlap decision, pinned. The ring holds a contradicting statement,
    so if `fact_check` passed `prior` it would fire a SECOND card about the
    thing Candor already reported — two accusations, one disagreement."""
    ls = brain.lenses()
    # The claim has to be one Veritas would actually TAKE, or this proves
    # nothing: `detect_claim` rejects "the meeting is at 4pm" outright (not a
    # checkable factual assertion), so an earlier version of this test passed
    # against a mutant that DID pass `prior`. A numeric claim is checkable, and
    # the ring holds a line it contradicts.
    ls.ingest_utterance("rent is 1200 a month", via="said")
    from dreamlayer.orchestrator.veritas import detect_claim
    assert detect_claim("rent is 1400 a month").checkable, (
        "the fixture claim is not one Veritas would take — test is vacuous")
    from dreamlayer.orchestrator.consistency import contradicts
    assert contradicts("rent is 1400 a month", "rent is 1200 a month"), (
        "the fixture pair no longer contradicts — test is vacuous")
    _answers(brain, "")                      # world tier declines to answer
    seen = _pushes(brain)
    out = ls.fact_check("rent is 1400 a month")
    assert out["fired"] is False, (
        "fact_check ran the self-contradiction pass Candor already owns")
    assert not [c for k, c in seen if k == "fact_check"]


def test_candor_still_catches_that_same_pair(brain):
    """…and the other half of the same decision: giving the world check to
    Veritas must not have taken the self-contradiction away from Candor."""
    ls = brain.lenses()
    ls.ingest_utterance("rent is 1200 a month", via="said")
    res = ls.candor_check("rent is 1400 a month", push=False)
    assert res["fired"] is True, "Candor lost the contradiction it owns"
    assert res["card"]["type"] == "ConsistencyCard"


def test_the_verifier_adds_no_second_posture_gate(brain):
    """`brain.ask` already owns the egress decision. A parallel check here is
    how the two drift apart and one of them starts being wrong."""
    import inspect
    from dreamlayer.ai_brain.server.lens_hosts import BrainLenses
    src = inspect.getsource(BrainLenses._verify_claim)
    # CODE only — the docstring explains at length why there is no gate here,
    # so a naive substring search finds every word it is asserting the absence
    # of. Strip comments and the docstring first.
    body = src.split('"""')[-1]
    code = "\n".join(ln.split("#")[0] for ln in body.splitlines())
    for banned in ("cloud_enabled", "incognito", "lan_only", "allow_capture"):
        assert banned not in code, f"a second posture gate crept in: {banned}"


def test_the_route_reaches_it(brain):
    from dreamlayer.ai_brain.server import server as srv
    text = open(srv.__file__, encoding="utf-8").read()
    assert '"/dreamlayer/factcheck": _get_factcheck,' in text
    assert "def _get_factcheck(self, path, qs):" in text
