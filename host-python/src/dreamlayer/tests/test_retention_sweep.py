"""Forget-completeness: the nightly RetentionSweep must evict an expired
memory's vector from the ALTERNATE vector store too, not just the ann index.

RetentionSweep.sweep() purges the DB row and (if wired) removes the ann vector,
but an alternate store (Chroma/Lance/VectorStore) indexes the same MemoryDB in
its OWN table/collection — not the ann index, and not among the tables
db.purge_memory deletes. Before this fix the sweep never called
vector_store.evict, so a warm memory that aged out of its window left a fully
recallable embedding behind the moment such a store was enabled. These pin the
RetentionSweep -> vector_store.evict wiring (mirrors Retriever.purge_memory).
"""
from __future__ import annotations

import time

from dreamlayer.memory.db import MemoryDB
from dreamlayer.memory.retention import RetentionPolicy, RetentionSweep

VEC = [0.1] * 8


class SpyVectorStore:
    """Duck-typed alternate store (VectorStore/Chroma/Lance shape) — records the
    evict calls the sweep must make, no optional deps needed."""
    def __init__(self):
        self.evicted: list = []

    def evict(self, memory_id):
        self.evicted.append(memory_id)


class BoomVectorStore:
    """An alternate store whose evict raises — the sweep must stay best-effort
    and finish the night, not abort on one bad row."""
    def __init__(self):
        self.attempted: list = []

    def evict(self, memory_id):
        self.attempted.append(memory_id)
        raise RuntimeError("transient store failure")


class TestRetentionSweepEvictsAlternateStore:
    def test_expired_memory_evicted_from_alternate_store(self):
        db, vs = MemoryDB(":memory:"), SpyVectorStore()
        mid = db.add_memory("scene", "an old sighting", embedding=VEC)
        # jump the clock far past the warm window so the memory expires
        future = time.time() + 10_000 * 86400
        sweep = RetentionSweep(db, RetentionPolicy(warm_days=90),
                               vector_store=vs, now_fn=lambda: future)
        report = sweep.sweep()
        assert mid in report.expired
        # REVERT-FAILING: the expired memory's vector left the alternate store
        assert vs.evicted == [mid]
        assert db.memory(mid) is None

    def test_kept_memory_not_evicted(self):
        # a memory INSIDE the warm window is kept — the sweep must not evict it
        db, vs = MemoryDB(":memory:"), SpyVectorStore()
        mid = db.add_memory("scene", "a recent sighting", embedding=VEC)
        sweep = RetentionSweep(db, RetentionPolicy(warm_days=90),
                               vector_store=vs)   # real clock: created_at is now
        report = sweep.sweep()
        assert mid not in report.expired
        assert vs.evicted == []                   # kept memory keeps its vector
        assert db.memory(mid) is not None

    def test_store_evict_error_does_not_abort_sweep(self):
        # best-effort: a store that raises on evict must not kill the night —
        # the DB row is still purged and the sweep completes.
        db, vs = MemoryDB(":memory:"), BoomVectorStore()
        mid = db.add_memory("scene", "an old sighting", embedding=VEC)
        future = time.time() + 10_000 * 86400
        sweep = RetentionSweep(db, RetentionPolicy(warm_days=90),
                               vector_store=vs, now_fn=lambda: future)
        report = sweep.sweep()                    # must not raise
        assert mid in report.expired
        assert vs.attempted == [mid]              # evict was attempted
        assert db.memory(mid) is None             # row still purged despite error

    def test_no_alternate_store_is_a_noop(self):
        # a sweep with no alternate store wired must still expire and not raise
        db = MemoryDB(":memory:")
        mid = db.add_memory("scene", "an old sighting", embedding=VEC)
        future = time.time() + 10_000 * 86400
        sweep = RetentionSweep(db, RetentionPolicy(warm_days=90),
                               now_fn=lambda: future)
        report = sweep.sweep()
        assert mid in report.expired
        assert db.memory(mid) is None


class BoomAnn:
    """A live ann index whose remove() raises on ONE row — the LIVE index is the
    store most likely to raise, and (before the fix) the least protected: an
    unguarded ann.remove aborted the whole night's sweep on the first bad row."""
    def __init__(self, boom_id):
        self.boom_id = boom_id
        self.removed: list = []
        self.flushed = False

    def remove(self, memory_id, save=False):
        self.removed.append(memory_id)
        if memory_id == self.boom_id:
            raise RuntimeError("ann index remove failed")

    def flush(self):
        self.flushed = True


class TestRetentionSweepIsResilient:
    def test_a_raising_ann_remove_does_not_abort_the_night(self):
        # Two expired memories; the ann index raises removing the FIRST. The
        # sweep must still purge BOTH rows and flush the index — one bad row
        # strands one vector, never the whole retention pass.
        db = MemoryDB(":memory:")
        m1 = db.add_memory("scene", "first old sighting", embedding=VEC)
        m2 = db.add_memory("scene", "second old sighting", embedding=VEC)
        future = time.time() + 10_000 * 86400
        ann = BoomAnn(boom_id=m1)
        sweep = RetentionSweep(db, RetentionPolicy(warm_days=90),
                               ann=ann, now_fn=lambda: future)
        report = sweep.sweep()                    # must not raise
        # REVERT-FAILING: an unguarded ann.remove would abort on m1, leaving m2
        assert db.memory(m1) is None
        assert db.memory(m2) is None
        assert m1 in report.expired and m2 in report.expired
        assert ann.flushed is True                # the trailing flush still ran


class TestRetentionSweepDiscardsBiasFingerprint:
    def test_expired_memory_bias_fingerprint_is_discarded_and_persisted(self, tmp_path):
        # An expired memory's REM consolidation fingerprint must not survive the
        # sweep — else a forgotten memory leaves a durable content-hash rank-ghost
        # in the bias vault (the same sidecar residue Retriever.purge_memory clears).
        from dreamlayer.rem import RetrievalBias
        from dreamlayer.rem.bias import event_key
        db = MemoryDB(":memory:")
        mid = db.add_memory("scene", "an old sighting", embedding=VEC)
        bias = RetrievalBias()
        key = event_key("scene", "an old sighting")
        bias.apply({key: -0.5})                   # a down-vote: present, non-positive
        assert bias.get(key) == -0.5              # fingerprint recorded
        future = time.time() + 10_000 * 86400
        sweep = RetentionSweep(db, RetentionPolicy(warm_days=90),
                               bias=bias, bias_dir=tmp_path, now_fn=lambda: future)
        report = sweep.sweep()
        assert mid in report.expired
        # REVERT-FAILING: the fingerprint is gone in memory AND on disk
        assert bias.get(key) == 0.0
        assert RetrievalBias.load(tmp_path).get(key) == 0.0

    def test_promoted_memory_keeps_its_fingerprint(self, tmp_path):
        # a memory the nights voted UP (positive bias) is KEPT — its fingerprint
        # must survive, not be discarded.
        from dreamlayer.rem import RetrievalBias
        from dreamlayer.rem.bias import event_key
        db = MemoryDB(":memory:")
        mid = db.add_memory("scene", "a cherished sighting", embedding=VEC)
        bias = RetrievalBias()
        key = event_key("scene", "a cherished sighting")
        bias.apply({key: 0.5})                    # an up-vote keeps it past the window
        future = time.time() + 10_000 * 86400
        sweep = RetentionSweep(db, RetentionPolicy(warm_days=90),
                               bias=bias, bias_dir=tmp_path, now_fn=lambda: future)
        report = sweep.sweep()
        assert mid not in report.expired
        assert bias.get(key) == 0.5               # kept memory keeps its opinion
        assert db.memory(mid) is not None
