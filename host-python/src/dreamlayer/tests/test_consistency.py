"""test_consistency.py — on-device fact consistency over your own memories."""
from __future__ import annotations

from dreamlayer.memory.ring_buffer import SemanticRingBuffer
from dreamlayer.pipelines.ingest import MemoryEvent
from dreamlayer.orchestrator.consistency import ConsistencyEngine

NOW = 1000.0


def ring_with(*mems) -> SemanticRingBuffer:
    """mems: (summary, confidence[, meta]) tuples."""
    ring = SemanticRingBuffer(capacity=64)
    for i, m in enumerate(mems):
        summary, conf = m[0], m[1]
        meta = m[2] if len(m) > 2 else {}
        ring.append(MemoryEvent(kind="memory", summary=summary,
                                confidence=conf, meta=meta), ts=NOW + i)
    return ring


class TestContradictions:
    def test_negation_flip(self):
        eng = ConsistencyEngine(ring_with(("the store is open on Sundays", 0.8)))
        r = eng.check("the store is not open on Sundays")
        assert r.fired and r.reason == "negation"
        assert "open on Sundays" in r.prior_summary

    def test_antonym_states(self):
        eng = ConsistencyEngine(ring_with(("the front door is open", 0.8)))
        r = eng.check("the front door is closed")
        assert r.fired and r.reason == "antonym"
        assert r.detail == "open vs closed"

    def test_value_conflict(self):
        eng = ConsistencyEngine(ring_with(("meeting with Sarah at 3", 0.8)))
        r = eng.check("meeting with Sarah at 4")
        assert r.fired and r.reason == "value"
        assert r.card["type"] == "ConsistencyCard"


class TestNoFalsePositives:
    def test_agreement_does_not_fire(self):
        eng = ConsistencyEngine(ring_with(("meeting with Sarah at 3", 0.8)))
        assert eng.check("meeting with Sarah at 3 is confirmed").fired is False

    def test_unrelated_subject_does_not_fire(self):
        eng = ConsistencyEngine(ring_with(("bought milk this morning", 0.8)))
        assert eng.check("the sky is blue today").fired is False

    def test_same_number_different_subject_does_not_fire(self):
        eng = ConsistencyEngine(ring_with(("bought 3 apples", 0.8)))
        assert eng.check("there are 3 cars outside").fired is False

    def test_value_needs_numbers_on_both_sides(self):
        eng = ConsistencyEngine(ring_with(("call Sarah tomorrow", 0.8)))
        # a number appears only in the new claim: no value contradiction
        assert eng.check("call Sarah at 5").fired is False

    def test_empty_baseline(self):
        assert ConsistencyEngine(ring_with()).check("anything at all").fired is False


class TestPrivacy:
    def test_private_memories_are_never_compared(self):
        eng = ConsistencyEngine(ring_with(
            ("dinner reservation at 7", 0.8, {"private": True})))
        assert eng.check("dinner reservation at 8").fired is False

    def test_low_confidence_priors_ignored(self):
        eng = ConsistencyEngine(ring_with(("the gate is open", 0.1)))
        assert eng.check("the gate is closed").fired is False


class TestCard:
    def test_card_shows_both_sides(self):
        eng = ConsistencyEngine(ring_with(("the store is open Sundays", 0.8)))
        card = eng.check("the store is not open Sundays").card
        assert card["primary"] == "the store is not open Sundays"
        assert card["footer"] == "the store is open Sundays"
        assert "different" in card["eyebrow"].lower()
