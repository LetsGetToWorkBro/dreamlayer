"""test_passive.py — tests for silent capture, ring buffer, and passive injection.

All tests use EmulatorBridge + in-memory DB. No hardware, no API key needed.
"""
from __future__ import annotations

from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.bridge.emulator_bridge import EmulatorBridge
from dreamlayer.config import Config
from dreamlayer.memory.ring_buffer import SemanticRingBuffer
from dreamlayer.pipelines.ingest import MemoryEvent


# vision.extract_object_memory expects nested dicts for object and place
_SCENE = {
    "object":     {"name": "keys", "near": "mug"},
    "place":      {"name": "kitchen table"},
    "confidence": 0.9,
}


def _orch(cfg: Config | None = None) -> Orchestrator:
    return Orchestrator(EmulatorBridge(), db_path=":memory:", config=cfg or Config())


class TestSemanticRingBuffer:
    def test_capacity_eviction(self):
        ring = SemanticRingBuffer(capacity=2)
        for s in ("a", "b", "c"):
            ring.append(MemoryEvent(kind="object", summary=s, confidence=0.9))
        assert len(ring) == 2
        latest = ring.latest(limit=5)
        assert latest[0].event.summary == "c"
        assert latest[1].event.summary == "b"

    def test_latest_kind_filter(self):
        ring = SemanticRingBuffer(capacity=10)
        ring.append(MemoryEvent(kind="object", summary="keys",   confidence=0.9))
        ring.append(MemoryEvent(kind="person", summary="Jordan", confidence=0.8))
        ring.append(MemoryEvent(kind="object", summary="wallet", confidence=0.9))
        objects = ring.latest(kind="object")
        assert all(b.event.kind == "object" for b in objects)
        assert len(objects) == 2

    def test_since_filters_by_timestamp(self):
        ring = SemanticRingBuffer(capacity=10)
        ring.append(MemoryEvent(kind="object", summary="old", confidence=0.9), ts=1000.0)
        ring.append(MemoryEvent(kind="object", summary="new", confidence=0.9), ts=2000.0)
        results = ring.since(1500.0)
        assert len(results) == 1
        assert results[0].event.summary == "new"


class TestSilentCapture:
    def test_scene_capture_rate_limited(self):
        """First call succeeds; second call within the interval is blocked."""
        o = _orch()
        first  = o.on_scene_frame(_SCENE, now_ms=1000)
        second = o.on_scene_frame(_SCENE, now_ms=1500)  # within default 4000 ms window
        assert first is not None
        assert second is None

    def test_scene_capture_allowed_after_interval(self):
        cfg = Config()
        cfg.capture_min_interval_ms = 1000
        o = _orch(cfg)
        first  = o.on_scene_frame(_SCENE, now_ms=0)
        second = o.on_scene_frame(_SCENE, now_ms=1001)  # past the 1 s interval
        assert first is not None
        assert second is not None

    def test_privacy_pause_blocks_audio_capture(self):
        o = _orch()
        o.pause()
        result = o.on_audio_frame("I left my wallet on the dresser.", now_ms=1000)
        assert result == []
        assert len(o.ring) == 0

    def test_audio_capture_populates_ring(self):
        cfg = Config()
        cfg.capture_min_interval_ms = 0
        o = _orch(cfg)
        o.on_audio_frame("I left my keys on the kitchen counter.", now_ms=1000)
        assert len(o.ring) >= 1
        assert any(b.event.kind == "object" for b in o.ring.latest(limit=20))


class TestPassiveEventInjector:
    def test_tick_emits_card_once_dedupes_on_second(self):
        cfg = Config()
        cfg.passive_min_confidence = 0.5
        o = _orch(cfg)
        o.ring.append(MemoryEvent(
            kind="object",
            summary="keys at kitchen counter",
            confidence=0.95,
            meta={"object": "Keys", "place": "Kitchen counter", "detail": ""},
            source="passive",
            db_id=42,
        ))
        card1 = o.tick()
        card2 = o.tick()
        assert card1 is not None
        assert card1["type"] == "ObjectRecallCard"
        assert card2 is None  # deduped

    def test_tick_ignores_low_confidence(self):
        cfg = Config()
        cfg.passive_min_confidence = 0.8
        o = _orch(cfg)
        o.ring.append(MemoryEvent(
            kind="object", summary="x", confidence=0.4, meta={}, source="passive", db_id=1
        ))
        assert o.tick() is None

    def test_tick_emits_task_card(self):
        cfg = Config()
        cfg.passive_min_confidence = 0.5
        o = _orch(cfg)
        o.ring.append(MemoryEvent(
            kind="task",
            summary="call dentist",
            confidence=0.85,
            meta={"person": "Jordan", "task": "call dentist", "due": "Monday"},
            source="passive",
            db_id=7,
        ))
        card = o.tick()
        assert card is not None
        assert card["type"] == "CommitmentRecallCard"
