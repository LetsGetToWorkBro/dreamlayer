"""P1-8: "forget" must evict the vector, not just the row.

purge_memory / purge_all and the nightly RetentionSweep deleted rows from
SQLite but never called ann.remove, so a forgotten memory's embedding lived on
in the .usearch index forever — a privacy residue (recall could still surface
it) and unbounded growth. These tests pin that both stores stay in step, at the
Retriever, the RetentionSweep, and (when usearch is installed) the real index.
"""
from __future__ import annotations

import time

import pytest

from dreamlayer.memory.db import MemoryDB
from dreamlayer.memory.retrieval import Retriever
from dreamlayer.memory.retention import RetentionSweep, RetentionPolicy

VEC = [0.1] * 8


class StubAnn:
    """Records the calls the purge paths must make (no usearch needed)."""
    def __init__(self):
        self.added, self.removed, self.rebuilt = [], [], False

    def add(self, mid, vec):
        self.added.append(mid)

    def remove(self, mid, save=True):
        self.removed.append(mid)

    def rebuild(self, db):
        self.rebuilt = True
        return 0


class TestRetrieverPurge:
    def test_purge_memory_evicts_vector_and_row(self):
        db, ann = MemoryDB(":memory:"), StubAnn()
        r = Retriever(db, ann=ann)
        mid = db.add_memory("scene", "keys on the counter", embedding=VEC)
        r.index_memory(mid, VEC)
        assert mid in ann.added

        r.purge_memory(mid)
        assert mid in ann.removed          # vector evicted
        assert db.memory(mid) is None       # row gone

    def test_purge_all_clears_the_index(self):
        db, ann = MemoryDB(":memory:"), StubAnn()
        r = Retriever(db, ann=ann)
        db.add_memory("scene", "a", embedding=VEC)
        r.purge_all()
        assert ann.rebuilt and db.memories() == []


class TestPurgeLeavesNoLocationResidue:
    """Re-audit: purge_all deleted memories/commitments/conversations/events but
    left `places` and `entities`. A place row is a location SIGNATURE (the
    wifi/BLE fingerprint ProactiveEngine.on_place matches on), so leaving it
    behind is a privacy residue after a full wipe. `settings` stays — it is
    device config, not a trace of the wearer's world."""

    def test_purge_all_erases_places_and_entities(self):
        db = MemoryDB(":memory:")
        pid = db.add_place("home kitchen", signature="wifi:aa:bb:cc")
        db.add_memory("scene", "keys on the counter", place_id=pid)
        db.set_setting("model", "keyword")          # config, must survive
        db.purge_all()
        assert db.memories() == []
        assert db.places() == []                    # location signature gone
        with db._lock:
            assert db.conn.execute("SELECT COUNT(*) c FROM entities").fetchone()["c"] == 0
        assert db.get_setting("model") == "keyword"  # config preserved


class TestRetentionSweepEviction:
    def test_expired_memory_leaves_the_index(self):
        db, ann = MemoryDB(":memory:"), StubAnn()
        mid = db.add_memory("scene", "an old sighting", embedding=VEC)
        # jump the clock far past the warm window so the memory expires
        future = time.time() + 10_000 * 86400
        sweep = RetentionSweep(db, RetentionPolicy(warm_days=90),
                               ann=ann, now_fn=lambda: future)
        report = sweep.sweep()
        assert mid in report.expired
        assert mid in ann.removed
        assert db.memory(mid) is None


class TestRealIndexEviction:
    def test_purged_vector_is_gone_from_recall(self):
        pytest.importorskip("usearch")
        from dreamlayer.memory.ann_index import PersistentAnnIndex
        ann = PersistentAnnIndex(None, 8)          # in-memory (no path)
        ann.add(1, [1.0] + [0.0] * 7)
        ann.add(2, [0.0, 1.0] + [0.0] * 6)
        assert len(ann) == 2

        ann.remove(1)
        hits = dict(ann.search([1.0] + [0.0] * 7, k=5))
        assert 1 not in hits                       # the forgotten vector is gone
        assert len(ann) == 1
