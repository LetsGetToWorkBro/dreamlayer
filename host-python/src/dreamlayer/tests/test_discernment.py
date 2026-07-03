"""test_discernment.py — one read from three lenses.

Discernment fuses Veritas (content) with an optional Truth Lens CredibilityVector
(delivery) and a history count. The point of the composition: content + delivery
that *agree* is a strong flag, while a false claim delivered *sincerely* reads as
an honest mistake, not a lie.
"""
from __future__ import annotations

from dreamlayer.orchestrator.discernment import discern
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.truth_lens.schema import CredibilityVector
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


class _FC:
    """A minimal stand-in for a Veritas FactCheck (only the fields discern reads)."""
    def __init__(self, verdict, confidence=0.9):
        self.verdict = verdict
        self.confidence = confidence
        self.claim = "the deal closed at 3 million"
        self.basis = "earlier: 2 million"
        self.detail = ""


def _cred(deception, confidence=0.8):
    return CredibilityVector(deception_prob=deception, confidence=confidence,
                             micro_expression_z=0, voice_stress_z=0,
                             linguistic_z=0, dominant_channel="voice")


# -- content alone ------------------------------------------------------------

def test_content_alone_reflects_the_verdict():
    d = discern(_FC("self_contradiction"))
    assert d.content == "self_contradiction" and d.stance in ("caution", "flag")
    assert d.delivery == ""


def test_supported_content_is_trust():
    assert discern(_FC("supported", 0.9)).stance == "trust"


# -- the composition: content + delivery --------------------------------------

def test_disputed_plus_deceptive_delivery_is_the_strongest_flag():
    d = discern(_FC("disputed"), credibility=_cred(0.9))
    assert d.stance == "flag"
    assert "elevated" in d.corroboration or "alert" in d.corroboration
    assert "didn't sound like it" in d.headline


def test_false_but_sincere_is_an_honest_mistake_not_a_lie():
    d = discern(_FC("disputed"), credibility=_cred(0.1))     # credible delivery
    assert "they seem to mean it" in d.headline
    assert d.stance != "flag"                                # softened, not damning


def test_supported_but_uneasy_delivery_is_only_a_note():
    d = discern(_FC("supported", 0.9), credibility=_cred(0.9))
    assert d.stance in ("note", "caution") and "uneasy" in d.headline


# -- history escalates --------------------------------------------------------

def test_a_repeated_pattern_adds_weight():
    once = discern(_FC("disputed"))
    again = discern(_FC("disputed"), history=3)
    assert again.weight > once.weight
    assert "seen before" in again.corroboration


# -- end to end: the fused tag reaches the card -------------------------------

def test_orchestrator_folds_delivery_into_the_fact_card():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.set_factcheck(True)
    orc.note_credibility("Marcus", _cred(0.9))       # Truth Lens says: uneasy
    orc.ingest_caption("The deal closed at 2 million.", speaker="Marcus", ts=100.0)
    orc.ingest_caption("Actually it closed at 3 million.", speaker="Marcus", ts=140.0)
    cards = [f for f in br.raw if f.get("type") == "FactCheckCard"]
    assert cards
    card = cards[-1]
    assert card["stance"] == "flag"
    assert "elevated" in card["footer"] or "alert" in card["footer"].lower()


def test_history_builds_across_repeated_flags():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.set_factcheck(True)
    orc.ingest_caption("The rent is 2000 a month.", speaker="Dana", ts=1.0)
    orc.ingest_caption("The rent is 3000 a month.", speaker="Dana", ts=2.0)
    orc.ingest_caption("The rent is 4000 a month.", speaker="Dana", ts=3.0)
    # the second flag should know about the first
    assert orc._speaker_flags.get("dana", 0) >= 1
