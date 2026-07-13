"""Memory substance: BLOB embeddings, the embedder ladder, the retention
lifecycle (hot → warm → cold), the cold-start maturity arc, the Social Lens
top-2 margin, and the REM no-dream / keep-fade controls."""
import json
import time

import pytest

from dreamlayer.bridge.emulator_bridge import EmulatorBridge
from dreamlayer.memory.db import MemoryDB
from dreamlayer.memory.embeddings import (
    MockEmbeddingProvider, default_embedder, embedder_signature,
    pack_embedding, unpack_embedding,
)
from dreamlayer.memory.retention import (
    RetentionSweep,
)
from dreamlayer.memory.retrieval import Retriever
from dreamlayer.memory.ring_buffer import SemanticRingBuffer
from dreamlayer.orchestrator.maturity import (
    APPRENTICE, APPRENTICE_DAILY_CAP, MaturityGate, OBSERVER,
    OBSERVER_MIN_EVENTS, RESIDENT, ResidentGate,
)
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.pipelines.ingest import MemoryEvent


class TestEmbeddingStorage:
    def test_pack_unpack_roundtrip(self):
        vec = [0.25, -1.5, 3.0]
        out = unpack_embedding(pack_embedding(vec))
        assert out == pytest.approx(vec)

    def test_unpack_reads_legacy_json_rows(self):
        assert unpack_embedding(json.dumps([1.0, 2.0])) == [1.0, 2.0]
        assert unpack_embedding(None) is None

    def test_db_stores_blob_and_retriever_reads_it(self):
        db = MemoryDB()
        emb = MockEmbeddingProvider()
        mid = db.add_memory("object", "keys at the door",
                            embedding=emb.embed("keys at the door"))
        row = db.memory(mid)
        assert isinstance(row["embedding"], bytes)
        results = Retriever(db, emb).search("keys")
        assert results and results[0][1]["id"] == mid

    def test_retriever_reads_mixed_generations(self):
        db = MemoryDB()
        emb = MockEmbeddingProvider()
        # simulate a pre-BLOB row (JSON text) alongside a new BLOB row
        db.conn.execute(
            "INSERT INTO memories(kind,summary,embedding,confidence,created_at,meta)"
            " VALUES (?,?,?,?,?,?)",
            ("object", "wine on the shelf",
             json.dumps(emb.embed("wine on the shelf")), 0.9,
             "2026-01-01T00:00:00+00:00", "{}"))
        db.add_memory("object", "bike at the rack",
                      embedding=emb.embed("bike at the rack"))
        r = Retriever(db, emb)
        assert r.search("wine")[0][1]["summary"] == "wine on the shelf"
        assert r.search("bike")[0][1]["summary"] == "bike at the rack"


class TestPersistentAnn:
    """Real usearch path (skipped when the extra isn't installed)."""

    def setup_method(self):
        from dreamlayer.memory.ann_index import PersistentAnnIndex
        if not PersistentAnnIndex.available:
            pytest.skip("usearch not installed")

    def test_index_survives_reopen(self, tmp_path):
        from dreamlayer.memory.ann_index import PersistentAnnIndex
        emb = MockEmbeddingProvider()
        path = tmp_path / "mem.usearch"
        idx = PersistentAnnIndex(path, emb.DIM)
        idx.add(1, emb.embed("keys at the door"))
        idx.add(2, emb.embed("wine on the shelf"))
        idx.flush()   # adds batch (P2-15); flush is the persistence boundary
        idx2 = PersistentAnnIndex(path, emb.DIM)      # reopen from disk
        hits = idx2.search(emb.embed("keys"), k=1)
        assert hits and hits[0][0] == 1

    def test_dimension_mix_refused(self, tmp_path):
        from dreamlayer.memory.ann_index import PersistentAnnIndex
        idx = PersistentAnnIndex(tmp_path / "m.usearch", 32)
        assert idx.add(1, [0.5] * 384) is False       # wrong space

    def test_retriever_uses_ann_and_agrees_with_linear(self, tmp_path):
        from dreamlayer.memory.ann_index import PersistentAnnIndex
        db = MemoryDB()
        emb = MockEmbeddingProvider()
        ann = PersistentAnnIndex(tmp_path / "m.usearch", emb.DIM)
        r = Retriever(db, emb, ann=ann)
        for text in ("keys at the door", "wine on the shelf",
                     "bike at the rack", "lease on the desk"):
            mid = db.add_memory("object", text, embedding=emb.embed(text))
            r.index_memory(mid, emb.embed(text))
        assert len(ann) == 4
        ann_top = r.search("bike rack")[0][1]["summary"]
        linear_top = Retriever(db, emb).search("bike rack")[0][1]["summary"]
        assert ann_top == linear_top == "bike at the rack"

    def test_orchestrator_rebuilds_on_embedder_change(self, tmp_path):
        db_path = str(tmp_path / "m.db")
        orch = Orchestrator(EmulatorBridge(), db_path=db_path)
        orch.ingest_scene({"object": "keys", "place": "door",
                           "detail": "on the hook", "confidence": 0.9})
        if orch.retriever.ann is None:
            pytest.skip("usearch not installed")
        assert len(orch.retriever.ann) >= 1
        # simulate an embedder swap: poison the stored signature
        orch.db.set_setting("embedder_signature", "someone:else")
        orch2 = Orchestrator(EmulatorBridge(), db_path=db_path)
        assert orch2.db.get_setting("embedder_signature") != "someone:else"
        assert len(orch2.retriever.ann) >= 1          # rebuilt from rows


class TestEmbedderLadder:
    def test_hashing_is_the_offline_default(self):
        # with no neural model and no key, the offline default is a *real*
        # semantic/lexical embedder — the Model2Vec static tier when it's
        # installed, else the lexical hashing embedder — NEVER the 32-d mock.
        e = default_embedder(config=None)
        from dreamlayer.memory.embedder_local import LocalEmbeddingProvider
        from dreamlayer.memory.embedder_static import StaticEmbeddingProvider
        from dreamlayer.memory.embeddings import HashingEmbeddingProvider
        if not LocalEmbeddingProvider.available:
            import os
            if not os.environ.get("OPENAI_API_KEY"):
                if StaticEmbeddingProvider.available:
                    assert isinstance(e, StaticEmbeddingProvider)
                else:
                    assert isinstance(e, HashingEmbeddingProvider)

    def test_signature_distinguishes_spaces(self):
        from dreamlayer.memory.embeddings import HashingEmbeddingProvider
        assert embedder_signature(MockEmbeddingProvider()) == "mock:32"
        assert embedder_signature(HashingEmbeddingProvider()) == "hashing:512"


class TestRetentionLifecycle:
    def _db_with(self, kind, summary, created_at, meta=None):
        db = MemoryDB()
        db.conn.execute(
            "INSERT INTO memories(kind,summary,confidence,created_at,meta)"
            " VALUES (?,?,?,?,?)",
            (kind, summary, 0.6, created_at, json.dumps(meta or {})))
        db.conn.commit()
        return db

    def test_old_warm_memory_expires(self):
        db = self._db_with("object", "old sighting", "2020-01-01T00:00:00+00:00")
        report = RetentionSweep(db).sweep()
        assert report.expired and not db.memories()

    def test_cold_kinds_never_expire(self):
        db = self._db_with("promise", "send the lease", "2020-01-01T00:00:00+00:00")
        report = RetentionSweep(db).sweep()
        assert not report.expired and report.kept_cold == 1

    def test_pinned_never_expires(self):
        db = self._db_with("object", "grandma's ring box",
                           "2020-01-01T00:00:00+00:00", meta={"pinned": True})
        report = RetentionSweep(db).sweep()
        assert not report.expired and report.kept_pinned == 1

    def test_rem_promotion_saves_past_window(self):
        from dreamlayer.rem.bias import RetrievalBias, event_key
        db = self._db_with("object", "the mural on 4th",
                           "2020-01-01T00:00:00+00:00")
        bias = RetrievalBias({event_key("object", "the mural on 4th"): 0.3})
        report = RetentionSweep(db, bias=bias).sweep()
        assert not report.expired and report.kept_promoted == 1

    def test_inside_window_untouched(self):
        from datetime import datetime, UTC
        db = self._db_with("object", "fresh sighting",
                           datetime.now(UTC).isoformat())
        assert not RetentionSweep(db).sweep().expired

    def test_hot_ring_purges_by_age(self):
        ring = SemanticRingBuffer(capacity=16)
        now = time.time()
        ring.append(MemoryEvent(kind="memory", summary="yesterday"),
                    ts=now - 30 * 3600)
        ring.append(MemoryEvent(kind="memory", summary="just now"), ts=now)
        purged = RetentionSweep(MemoryDB()).purge_hot(ring)
        assert purged == 1 and len(ring) == 1


class TestMaturityArc:
    def test_fresh_install_is_observer_and_silent(self):
        g = MaturityGate(now_fn=lambda: 1000.0)
        assert g.state() == OBSERVER
        assert not g.allows_proactive(kind="event")
        assert not g.allows_hark()

    def test_observer_exit_needs_time_AND_events(self):
        clock = {"t": 0.0}
        g = MaturityGate(now_fn=lambda: clock["t"])
        clock["t"] = 49 * 3600.0                 # time served, no events
        assert g.state() == OBSERVER
        g.observe_event(OBSERVER_MIN_EVENTS)
        assert g.state() == APPRENTICE

    def test_apprentice_gates_kind_confidence_and_daily_cap(self):
        clock = {"t": 49 * 3600.0}
        g = MaturityGate(now_fn=lambda: clock["t"])
        g.paired_at = 0.0
        g.observe_event(OBSERVER_MIN_EVENTS)
        assert g.state() == APPRENTICE
        assert not g.allows_proactive(kind="place")           # kind gate
        assert not g.allows_proactive(kind="event", confidence=0.5)
        for _ in range(APPRENTICE_DAILY_CAP):
            assert g.allows_proactive(kind="event", confidence=0.9)
        assert not g.allows_proactive(kind="event", confidence=0.9)  # cap
        clock["t"] += 86400.0                                  # new day
        assert g.allows_proactive(kind="event", confidence=0.9)

    def test_resident_after_a_week_of_low_dismissals(self):
        clock = {"t": 8 * 86400.0}
        g = MaturityGate(now_fn=lambda: clock["t"])
        g.paired_at = 0.0
        g.observe_event(OBSERVER_MIN_EVENTS)
        for _ in range(10):
            g.observe_card(dismissed=False)
        assert g.state() == RESIDENT
        assert g.allows_hark()

    def test_high_dismissal_regresses_for_a_day(self):
        clock = {"t": 8 * 86400.0}
        g = MaturityGate(now_fn=lambda: clock["t"])
        g.paired_at = 0.0
        g.observe_event(OBSERVER_MIN_EVENTS)
        assert g.state() == RESIDENT            # earned it (sticky)
        for _ in range(20):
            g.observe_card(dismissed=True)      # the wearer swats everything
        assert g.state() == APPRENTICE          # dropped one state
        assert g.recalibrating()
        clock["t"] += 25 * 3600.0
        for _ in range(20):
            g.observe_card(dismissed=False)
        # the hold re-arms while the trailing window is still dirty; once
        # it's clean, one more quiet day restores full standing
        clock["t"] += 25 * 3600.0
        assert g.state() == RESIDENT

    def test_state_persists_across_restart(self, tmp_path):
        db = MemoryDB(str(tmp_path / "m.db"))
        clock = {"t": 0.0}
        g = MaturityGate(db, now_fn=lambda: clock["t"])
        g.observe_event(OBSERVER_MIN_EVENTS)
        clock["t"] = 49 * 3600.0
        g2 = MaturityGate(db, now_fn=lambda: clock["t"])   # "reboot"
        assert g2.events_seen >= OBSERVER_MIN_EVENTS
        assert g2.paired_at == 0.0
        assert g2.state() == APPRENTICE

    def test_ephemeral_sessions_skip_the_arc(self):
        orch = Orchestrator(EmulatorBridge())         # :memory: db
        assert isinstance(orch.maturity, ResidentGate)
        assert orch.maturity.allows_hark()

    def test_persistent_install_earns_it(self, tmp_path):
        orch = Orchestrator(EmulatorBridge(), db_path=str(tmp_path / "m.db"))
        assert isinstance(orch.maturity, MaturityGate)
        assert orch.maturity.state() == OBSERVER

    def test_dismissal_telemetry_feeds_the_gate(self, tmp_path):
        orch = Orchestrator(EmulatorBridge(), db_path=str(tmp_path / "m.db"))
        orch._on_event("TEL", {"event": "CARD_DISMISSED", "method": "tap",
                               "card_type": "UpcomingCard"})
        assert len(orch.maturity._cards) == 1
        assert orch.maturity._cards[-1] is True


class TestSocialMargin:
    @staticmethod
    def _vec(x, y):
        v = [0.0] * 512
        v[0], v[1] = x, y
        return v

    def _index(self):
        from dreamlayer.social_lens.index import ContactIndex
        from dreamlayer.social_lens.schema import ContactRecord
        idx = ContactIndex()
        idx.load([
            ContactRecord(contact_id="a", name="Maya",
                          embedding=self._vec(1.0, 0.0)),
            ContactRecord(contact_id="b", name="Mara",
                          embedding=self._vec(0.9, 0.4359)),   # unit vector
        ])
        return idx

    def test_too_close_to_call_returns_none(self):
        # a probe nearly equidistant between two contacts must NOT name one
        assert self._index().search(self._vec(0.974, 0.226)) is None

    def test_clear_winner_still_matches(self):
        r = self._index().search(self._vec(1.0, 0.0))
        assert r is not None and r.contact.contact_id == "a"


class TestRemControls:
    def test_no_dream_events_never_dreamed(self):
        from dreamlayer.rem.cycle import REMCycle
        ring = SemanticRingBuffer(capacity=16)
        now = time.time()
        ring.append(MemoryEvent(kind="memory", summary="the argument at work",
                                meta={"no_dream": True}), ts=now - 3600)
        ring.append(MemoryEvent(kind="memory", summary="coffee with Sam"),
                    ts=now - 7200)
        ring.append(MemoryEvent(kind="memory", summary="bike at the rack"),
                    ts=now - 10000)
        reel = REMCycle(ring, seed=7, now_fn=lambda: now).run()
        assert all("argument" not in s.phrase for s in reel.scenes)
        assert not any("argument" in (reel.summaries.get(k) or "")
                       for k in reel.dream_counts)

    def test_never_dream_about_tags_memories(self):
        orch = Orchestrator(EmulatorBridge())
        emb = orch.embedder.embed("the argument at work")
        mid = orch.db.add_memory("conversation", "the argument at work",
                                 embedding=emb)
        tagged = orch.never_dream_about("argument work")
        assert tagged >= 1
        meta = json.loads(orch.db.memory(mid)["meta"])
        assert meta["no_dream"] is True

    def test_rem_feedback_moves_the_bias(self):
        orch = Orchestrator(EmulatorBridge())
        before = orch.rem_bias.boost_for("memory", "coffee with Sam")
        after = orch.rem_feedback("memory", "coffee with Sam", keep=True)
        assert after > before
        faded = orch.rem_feedback("memory", "coffee with Sam", keep=False)
        assert faded < after
