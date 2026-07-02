"""test_provenance.py — the Provenance Lens: the genealogy of a belief."""
from __future__ import annotations

from dreamlayer.memory.ring_buffer import SemanticRingBuffer
from dreamlayer.pipelines.ingest import MemoryEvent
from dreamlayer.orchestrator.provenance import ProvenanceLens, humanize_age

NOW = 1_700_000_000.0
DAY = 86_400.0


def ring(*mems) -> SemanticRingBuffer:
    """mems: (summary, ago_days, meta, confidence) with sensible defaults."""
    r = SemanticRingBuffer(capacity=128)
    for m in mems:
        summary = m[0]
        ago = m[1] if len(m) > 1 else 0
        meta = m[2] if len(m) > 2 else {}
        conf = m[3] if len(m) > 3 else 0.8
        r.append(MemoryEvent(kind="memory", summary=summary, confidence=conf,
                             meta=meta), ts=NOW - ago * DAY)
    return r


class TestAge:
    def test_humanize(self):
        assert humanize_age(10) == "just now"
        assert humanize_age(3 * 3600) == "3 hours ago"
        assert humanize_age(2 * DAY) == "2 days ago"
        assert humanize_age(3 * 604800) == "3 weeks ago"


class TestTrace:
    def test_traces_to_the_origin_and_who(self):
        lens = ProvenanceLens(ring(
            ("the deadline is Friday", 21, {"person": "Maya", "via": "heard"})))
        r = lens.trace("the deadline is Friday", now=NOW)
        assert r.found
        assert r.origin.who == "Maya"
        assert "Maya" in r.card["detail"] and "weeks ago" in r.card["detail"]

    def test_single_hearsay_is_unverified(self):
        lens = ProvenanceLens(ring(
            ("the deadline is Friday", 3, {"person": "Maya", "via": "heard"})))
        r = lens.trace("the deadline is Friday", now=NOW)
        assert r.status == "unverified"
        assert r.corroboration == 1

    def test_two_independent_sources_corroborate(self):
        lens = ProvenanceLens(ring(
            ("deadline is Friday", 5, {"person": "Maya", "via": "heard"}),
            ("Friday is the deadline", 2, {"person": "Sam", "via": "heard"})))
        r = lens.trace("the deadline is Friday", now=NOW)
        assert r.status == "corroborated"
        assert r.corroboration == 2

    def test_firsthand_beats_hearsay(self):
        lens = ProvenanceLens(ring(
            ("deadline is Friday", 5, {"person": "Maya", "via": "heard"}),
            ("saw the deadline is Friday on the board", 1, {"via": "saw"})))
        r = lens.trace("the deadline is Friday", now=NOW)
        assert r.status == "firsthand"

    def test_earliest_support_is_the_origin(self):
        lens = ProvenanceLens(ring(
            ("deadline is Friday", 2, {"person": "Sam", "via": "heard"}),
            ("deadline is Friday", 20, {"person": "Maya", "via": "heard"})))
        r = lens.trace("the deadline is Friday", now=NOW)
        assert r.origin.who == "Maya"          # the older one seeded the belief


class TestContested:
    def test_contradiction_makes_it_contested(self):
        lens = ProvenanceLens(ring(
            ("the team standup is at 3", 3, {"person": "Maya", "via": "heard"}),
            ("the team standup is at 4", 1, {"person": "Sam", "via": "heard"})))
        r = lens.trace("the team standup is at 3", now=NOW)
        assert r.status == "contested"
        assert r.contradiction is not None
        # the clashing memory must not also be counted as support
        assert all("at 4" not in s.summary for s in r.supports)


class TestGuards:
    def test_no_support_is_unknown(self):
        lens = ProvenanceLens(ring(("bought milk", 1)))
        r = lens.trace("the sky is blue", now=NOW)
        assert r.found is False and r.status == "unknown"

    def test_private_memories_are_never_traced(self):
        lens = ProvenanceLens(ring(
            ("the code is 4417", 2, {"private": True, "person": "Maya"})))
        assert lens.trace("the code is 4417", now=NOW).found is False


class TestOrchestratorWiring:
    def test_trace_provenance_is_veil_gated_and_cards(self):
        from dreamlayer.tests.test_integration_dream_suite import FakeBridge
        from dreamlayer.orchestrator.orchestrator import Orchestrator
        orc = Orchestrator(FakeBridge())
        orc.ring.append(MemoryEvent(kind="memory", summary="deadline is Friday",
                                    confidence=0.8,
                                    meta={"person": "Maya", "via": "heard"}),
                        ts=NOW - 20 * DAY)
        r = orc.trace_provenance("the deadline is Friday", now=NOW)
        assert r is not None and r.found and r.origin.who == "Maya"
        assert any(f.get("t") == "card" for f in orc.bridge.raw)
        orc.privacy.pause()
        assert orc.trace_provenance("the deadline is Friday", now=NOW) is None
