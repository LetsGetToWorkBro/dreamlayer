"""test_time_scrub.py — tests for TimeScrubSession."""
from __future__ import annotations
from dreamlayer.orchestrator.time_scrub import TimeScrubSession
from dreamlayer.memory.ring_buffer import SemanticRingBuffer
from dreamlayer.pipelines.ingest import MemoryEvent


def _populated_ring(n: int = 5, base_ts: float = 1000.0) -> SemanticRingBuffer:
    ring = SemanticRingBuffer(capacity=50)
    for i in range(n):
        ring.append(
            MemoryEvent(
                kind="object",
                summary=f"event_{i}",
                confidence=0.9,
                meta={},
                source="passive",
                db_id=i,
            ),
            ts=base_ts + i * 60,  # one event per minute
        )
    return ring


class TestTimeScrubSession:
    def test_empty_ring_returns_none(self):
        ring = SemanticRingBuffer(capacity=10)
        session = TimeScrubSession(ring, lookback_s=3600, now=5000.0)
        assert session.current() is None
        assert session.forward() is None
        assert session.back() is None

    def test_length_matches_ring_events(self):
        base = 1000.0
        ring = _populated_ring(5, base)
        session = TimeScrubSession(ring, lookback_s=3600, now=base + 500)
        assert session.length == 5

    def test_current_is_most_recent(self):
        base = 1000.0
        ring = _populated_ring(5, base)
        session = TimeScrubSession(ring, lookback_s=3600, now=base + 500)
        card = session.current()
        assert card is not None
        assert card["type"] == "TimeScrubNodeCard"
        # cursor starts at last (most-recent) node
        assert card["index"] == session.length - 1

    def test_back_decrements_cursor(self):
        base = 1000.0
        ring = _populated_ring(5, base)
        session = TimeScrubSession(ring, lookback_s=3600, now=base + 500)
        first = session.current()["index"]
        session.back()
        assert session.cursor == first - 1

    def test_forward_clamps_at_end(self):
        base = 1000.0
        ring = _populated_ring(3, base)
        session = TimeScrubSession(ring, lookback_s=3600, now=base + 300)
        # Already at end; forward should clamp
        session.forward()
        assert session.cursor == session.length - 1

    def test_select_jumps_to_index(self):
        base = 1000.0
        ring = _populated_ring(5, base)
        session = TimeScrubSession(ring, lookback_s=3600, now=base + 500)
        card = session.select(2)
        assert card is not None
        assert card["index"] == 2
        assert session.cursor == 2
