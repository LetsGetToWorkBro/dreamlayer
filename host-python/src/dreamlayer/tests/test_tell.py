"""test_tell.py — tests for TellEngine deviation detection."""
from __future__ import annotations
import pytest
from dreamlayer.orchestrator.tell import TellEngine, _overlap, _keywords
from dreamlayer.memory.ring_buffer import SemanticRingBuffer
from dreamlayer.pipelines.ingest import MemoryEvent


def _ring_with_promise(
    summary: str = "I will send the invoice tomorrow",
    confidence: float = 0.82,
) -> SemanticRingBuffer:
    ring = SemanticRingBuffer(capacity=50)
    ring.append(MemoryEvent(
        kind="task",
        summary=summary,
        confidence=confidence,
        meta={"person": "Jordan", "task": summary, "due": "tomorrow"},
        source="passive",
        db_id=1,
    ))
    return ring


class TestHelpers:
    def test_keywords_removes_stopwords(self):
        kw = _keywords("I will send the invoice tomorrow")
        assert "i" not in kw
        assert "invoice" in kw
        assert "send" in kw

    def test_overlap_identical(self):
        assert _overlap("send invoice tomorrow", "send invoice tomorrow") == pytest.approx(1.0)

    def test_overlap_disjoint(self):
        assert _overlap("cat sat mat", "dog ran far") == pytest.approx(0.0)


class TestTellEngine:
    def test_no_baseline_no_fire(self):
        ring = SemanticRingBuffer(capacity=10)  # empty
        engine = TellEngine(ring)
        result = engine.check("I never said I'd send anything", confidence=0.85)
        assert not result.fired
        assert result.score == 0.0

    def test_fires_on_contradicting_transcript(self):
        ring = _ring_with_promise(
            summary="send invoice tomorrow",
            confidence=0.20,  # low prior confidence
        )
        engine = TellEngine(ring, deviation_threshold=0.30)
        # High-confidence denial of same topic → overlap moderate, conf delta large
        result = engine.check("send invoice tomorrow", confidence=0.90)
        assert result.fired
        assert result.card is not None
        assert result.card["type"] == "DeviationAlertCard"

    def test_no_fire_on_unrelated_transcript(self):
        ring = _ring_with_promise(summary="send invoice tomorrow")
        engine = TellEngine(ring)
        result = engine.check("walked the dog in the park", confidence=0.80)
        assert not result.fired
