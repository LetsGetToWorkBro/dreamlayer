"""P2-15: memory-spine coherence — the DB/ANN/feedback machinery keeps its own
promises about writes, windows, and knobs.

Three fixes pinned here:

1. **ANN write batching.** PersistentAnnIndex.add() used to serialize the whole
   index file on EVERY ingest — tens of MB rewritten per captured moment at a
   year of wear. Adds now batch (save every `save_every` mutations, flush() at
   quiet points); deletions still persist immediately, because a purged memory
   must never resurrect from a stale index file. The boot path rebuilds when
   the on-disk index disagrees with the DB, so a crash inside the batch window
   costs one rebuild, never silent recall misses.

2. **Per-card-type dismissal windows.** One shared 20-event window meant a
   chatty card type evicted every other type's history, so a rarely-shown type
   could never reach MIN_SAMPLES and adapt. Each type now has its own window.

3. **passive_tick_interval_ms is real.** The config knob existed with zero
   consumers — "~4 Hz" was a comment about the caller, not a guarantee. The
   injector now self-throttles to it.
"""
from __future__ import annotations

import pytest

from dreamlayer.memory.embeddings import MockEmbeddingProvider


# ---------------------------------------------------------------------------
# 1. ANN write batching
# ---------------------------------------------------------------------------

class TestAnnWriteBatching:
    def setup_method(self):
        from dreamlayer.memory.ann_index import PersistentAnnIndex
        if not PersistentAnnIndex.available:
            pytest.skip("usearch not installed")

    def _index(self, tmp_path, save_every):
        from dreamlayer.memory.ann_index import PersistentAnnIndex
        emb = MockEmbeddingProvider()
        idx = PersistentAnnIndex(tmp_path / "m.usearch", emb.DIM,
                                 save_every=save_every)
        saves = []
        original = idx._save
        idx._save = lambda: (saves.append(1), original())[1]  # count real saves
        return idx, emb, saves

    def test_adds_do_not_save_every_time(self, tmp_path):
        idx, emb, saves = self._index(tmp_path, save_every=4)
        for i in range(3):
            idx.add(i, emb.embed(f"memory {i}"))
        assert saves == []                      # inside the batch: no disk I/O

    def test_batch_boundary_saves(self, tmp_path):
        idx, emb, saves = self._index(tmp_path, save_every=4)
        for i in range(4):
            idx.add(i, emb.embed(f"memory {i}"))
        assert len(saves) == 1                  # exactly at save_every

    def test_flush_persists_a_partial_batch(self, tmp_path):
        from dreamlayer.memory.ann_index import PersistentAnnIndex
        idx, emb, saves = self._index(tmp_path, save_every=64)
        idx.add(1, emb.embed("keys at the door"))
        idx.flush()
        assert len(saves) == 1
        # ...and the vector really is on disk
        idx2 = PersistentAnnIndex(tmp_path / "m.usearch", emb.DIM)
        assert idx2.search(emb.embed("keys"), k=1)

    def test_flush_is_a_noop_when_clean(self, tmp_path):
        idx, _emb, saves = self._index(tmp_path, save_every=4)
        idx.flush()
        assert saves == []                      # nothing dirty, nothing written

    def test_remove_saves_immediately(self, tmp_path):
        from dreamlayer.memory.ann_index import PersistentAnnIndex
        idx, emb, saves = self._index(tmp_path, save_every=64)
        idx.add(1, emb.embed("secret"))
        idx.flush()
        n = len(saves)
        idx.remove(1)                           # purge honesty: no batching
        assert len(saves) == n + 1
        idx2 = PersistentAnnIndex(tmp_path / "m.usearch", emb.DIM)
        assert len(idx2) == 0                   # gone from disk, on the spot

    def test_boot_rebuilds_when_index_lags_the_db(self, tmp_path):
        # simulate a crash inside the batch window: DB has rows the on-disk
        # index never saw — the orchestrator's boot check must rebuild
        from dreamlayer.orchestrator.orchestrator import Orchestrator
        from dreamlayer.tests.test_integration_dream_suite import FakeBridge
        db_path = tmp_path / "mem.db"
        orch = Orchestrator(FakeBridge(), db_path=str(db_path))
        if orch.retriever.ann is None:
            pytest.skip("usearch not installed")
        orch.ingest_conversation("I left the keys on the piano")
        n = len(orch.retriever.ann)
        assert n > 0                            # the ingest really indexed rows
        # crash before any flush: throw away the in-memory index, leave disk stale
        (tmp_path / "mem.db.usearch").unlink(missing_ok=True)
        orch2 = Orchestrator(FakeBridge(), db_path=str(db_path))
        assert orch2.retriever.ann is not None
        assert len(orch2.retriever.ann) == n    # rebuilt from the DB at boot


# ---------------------------------------------------------------------------
# 2. Per-card-type dismissal windows
# ---------------------------------------------------------------------------

def _shown(t):
    return {"t": "TEL", "event": "CARD_SHOWN", "card_type": t}


def _dismissed(t):
    return {"t": "TEL", "event": "CARD_DISMISSED", "card_type": t}


class TestPerTypeDismissalWindows:
    def test_a_chatty_type_cannot_evict_a_sparse_types_history(self):
        from dreamlayer.orchestrator.adaptive_confidence import DismissalTracker
        t = DismissalTracker(window_size=20, persist=False)
        # the sparse type earns its adaptation signal first...
        for _ in range(4):
            t.on_telemetry_event(_shown("TasteCard"))
            t.on_telemetry_event(_dismissed("TasteCard"))
        # ...then a chatty type floods 100 events (5x the old shared window)
        for _ in range(100):
            t.on_telemetry_event(_shown("HorizonCard"))
        # the old shared deque would have evicted every TasteCard event by now
        assert t.shown_count("TasteCard") == 4
        assert t.dismissal_rate("TasteCard") == 1.0
        assert t.suggested_threshold("TasteCard", 0.45) > 0.45  # still adapts

    def test_each_window_caps_independently(self):
        from dreamlayer.orchestrator.adaptive_confidence import DismissalTracker
        t = DismissalTracker(window_size=5, persist=False)
        for _ in range(20):
            t.on_telemetry_event(_shown("A"))
            t.on_telemetry_event(_shown("B"))
        assert t.shown_count("A") == 5 and t.shown_count("B") == 5

    def test_type_count_is_bounded_lru(self):
        from dreamlayer.orchestrator.adaptive_confidence import DismissalTracker
        t = DismissalTracker(window_size=5, persist=False, max_types=3)
        for name in ("A", "B", "C", "D"):       # D evicts A (stalest)
            t.on_telemetry_event(_shown(name))
        assert t.shown_count("A") == 0
        assert t.shown_count("D") == 1

    def test_persistence_round_trips_per_type(self, tmp_path):
        from dreamlayer.orchestrator.adaptive_confidence import DismissalTracker
        log = tmp_path / "dismissal_log.json"
        t = DismissalTracker(persist=True, log_path=log)
        t.on_telemetry_event(_shown("A"))
        t.on_telemetry_event(_dismissed("A"))
        t.on_telemetry_event(_shown("B"))
        t2 = DismissalTracker(persist=True, log_path=log)
        assert t2.shown_count("A") == 1 and t2.dismissal_rate("A") == 1.0
        assert t2.shown_count("B") == 1

    def test_legacy_flat_log_is_folded_per_type(self, tmp_path):
        import json
        from dreamlayer.orchestrator.adaptive_confidence import DismissalTracker
        log = tmp_path / "dismissal_log.json"
        log.write_text(json.dumps([                 # the pre-P2-15 format
            {"c": "A", "e": "CARD_SHOWN"},
            {"c": "B", "e": "CARD_SHOWN"},
            {"c": "A", "e": "CARD_DISMISSED"},
        ]))
        t = DismissalTracker(persist=True, log_path=log)
        assert t.shown_count("A") == 1 and t.shown_count("B") == 1
        assert t.dismissal_rate("A") == 1.0


# ---------------------------------------------------------------------------
# 3. passive_tick_interval_ms is enforced
# ---------------------------------------------------------------------------

class _Bridge:
    def __init__(self):
        self.cards = []

    def send_card(self, card, event=""):
        self.cards.append(card)


class TestPassiveTickInterval:
    def _injector(self, interval_ms):
        from dreamlayer.orchestrator.passive_injector import PassiveEventInjector
        from dreamlayer.memory.ring_buffer import SemanticRingBuffer, MemoryEvent
        clock = {"now": 0.0}
        ring = SemanticRingBuffer(capacity=8)
        inj = PassiveEventInjector(_Bridge(), ring, min_confidence=0.5,
                                   tick_interval_ms=interval_ms,
                                   clock=lambda: clock["now"])
        def event(db_id):
            return MemoryEvent(kind="object", summary="keys",
                               confidence=0.9,
                               meta={"object": "Keys", "place": "desk",
                                     "detail": ""},
                               source="passive", db_id=db_id)
        return inj, ring, clock, event

    def test_scans_are_throttled_to_the_configured_cadence(self):
        inj, ring, clock, event = self._injector(interval_ms=250)
        ring.append(event(1))
        assert inj.tick() is not None           # first scan fires
        ring.append(event(2))
        clock["now"] += 0.1                     # inside the 250ms cadence
        assert inj.tick() is None               # throttled, not scanned
        clock["now"] += 0.2                     # past the cadence
        assert inj.tick() is not None           # scans again

    def test_zero_interval_scans_every_tick(self):
        inj, ring, clock, event = self._injector(interval_ms=0)
        ring.append(event(1))
        assert inj.tick() is not None
        ring.append(event(2))
        assert inj.tick() is not None           # no throttle at 0 (old behavior)

    def test_orchestrator_wires_the_config_knob(self):
        from dreamlayer.config import Config
        from dreamlayer.orchestrator.orchestrator import Orchestrator
        from dreamlayer.tests.test_integration_dream_suite import FakeBridge
        cfg = Config()
        cfg.passive_tick_interval_ms = 123
        orch = Orchestrator(FakeBridge(), config=cfg)
        assert orch.passive.tick_interval_s == pytest.approx(0.123)
