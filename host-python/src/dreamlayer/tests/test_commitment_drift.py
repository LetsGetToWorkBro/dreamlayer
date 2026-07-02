"""test_commitment_drift.py — tests for CommitmentDriftEngine."""
from __future__ import annotations
import time
import pytest
from dreamlayer.orchestrator.commitment_drift import CommitmentDriftEngine, _classify, _parse_due
from dreamlayer.memory.ring_buffer import SemanticRingBuffer
from dreamlayer.pipelines.ingest import MemoryEvent


def _ring_with_task(
    summary: str = "call dentist",
    confidence: float = 0.85,
    due: str = "2h",
    ts: float | None = None,
) -> SemanticRingBuffer:
    ring = SemanticRingBuffer(capacity=50)
    ts = ts if ts is not None else time.time()
    ring.append(
        MemoryEvent(
            kind="task",
            summary=summary,
            confidence=confidence,
            meta={"person": "Jordan", "task": summary, "due": due},
            source="passive",
            db_id=1,
        ),
        ts=ts,
    )
    return ring


class TestClassify:
    def test_blooming(self):  assert _classify(0.10) == "blooming"
    def test_healthy(self):   assert _classify(0.35) == "healthy"
    def test_drifting(self):  assert _classify(0.60) == "drifting"
    def test_cracking(self):  assert _classify(0.85) == "cracking"
    def test_shattered(self): assert _classify(1.00) == "shattered"


class TestParseDue:
    def test_hours(self):
        base = 0.0
        assert _parse_due("in 3h", base) == 3 * 3600

    def test_days(self):
        base = 0.0
        assert _parse_due("2d from now", base) == 2 * 86400

    def test_tomorrow(self):
        base = 0.0
        assert _parse_due("tomorrow morning", base) == 86400

    def test_none_returns_none(self):
        assert _parse_due(None, 0.0) is None
        assert _parse_due("", 0.0) is None


class TestDriftEngine:
    def test_no_alerts_before_threshold(self):
        base_ts = 1000.0
        ring = _ring_with_task(due="2h", ts=base_ts)
        engine = CommitmentDriftEngine(ring)
        # tick 30 s after creation — decay ~0.004, state=blooming
        alerts = engine.tick(now=base_ts + 30)
        assert alerts == []

    def test_cracking_fires_alert(self):
        base_ts = 1000.0
        ring = _ring_with_task(due="2h", ts=base_ts)
        engine = CommitmentDriftEngine(ring)
        # tick at 80% of the 2-h window → decay=0.80, state=cracking
        alerts = engine.tick(now=base_ts + 0.80 * 2 * 3600)
        assert len(alerts) == 1
        assert alerts[0].state == "cracking"

    def test_alert_fires_only_once(self):
        base_ts = 1000.0
        ring = _ring_with_task(due="2h", ts=base_ts)
        engine = CommitmentDriftEngine(ring)
        engine.tick(now=base_ts + 0.80 * 2 * 3600)  # first tick — fires
        alerts2 = engine.tick(now=base_ts + 0.90 * 2 * 3600)  # second tick — already surfaced
        assert alerts2 == []

    def test_shattered_uses_fallback_lifetime(self):
        """Without a due date, decay uses the 48-h fallback lifetime."""
        base_ts = 1000.0
        ring = _ring_with_task(due="", ts=base_ts)
        engine = CommitmentDriftEngine(ring)
        alerts = engine.tick(now=base_ts + 49 * 3600)  # past 48 h → shattered
        assert any(a.state == "shattered" for a in alerts)
