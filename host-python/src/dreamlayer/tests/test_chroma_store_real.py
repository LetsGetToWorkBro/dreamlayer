"""ChromaDB real-path semantic recall (issue #282): ranking, the
0.5*sim + 0.5*confidence blend, kind filtering, the empty-DB early return,
and the linear fallback. Issue #409 adds the stable-memory_id keying pins:
broad->narrow kind= searches must stay on the chroma path (no IndexError->
silent-degradation), kind isolation must hold against cross-kind vectors
accumulated in the persistent collection, and evict() must delete exactly one
vector instead of dropping the collection. Needs chromadb (importorskip);
path=None builds an EphemeralClient (no disk state) and the default
MockEmbeddingProvider is deterministic, so ranking and score assertions are
stable across runs."""
import pytest

from dreamlayer.memory.chroma_store import ChromaStore
from dreamlayer.memory.db import MemoryDB
from dreamlayer.memory.embeddings import MockEmbeddingProvider, cosine
from dreamlayer.memory.vector_store import VectorStore

chromadb = pytest.importorskip("chromadb")

ROWS = [
    ("object", "snake plant on the windowsill water every two weeks", 0.5),
    ("object", "bike locked at the north rack on 4th and Alder", 0.5),
    ("commitment", "Marcus is owed the signed lease by Friday", 0.5),
    ("object", "passport is in the top drawer of the desk", 0.5),
    ("commitment", "call the dentist about Tuesday at 3pm", 0.5),
]


def _seeded(emb, rows=ROWS):
    db = MemoryDB(":memory:")
    for kind, summary, conf in rows:
        db.add_memory(kind, summary, embedding=emb.embed(summary), confidence=conf)
    return db


def _fallback_spy(store, monkeypatch):
    """Record any silent degrade to the linear fallback — the real-path tests
    must prove the chroma branch itself produced the answer."""
    calls = []
    real = store._fallback.search
    def spy(*a, **k):
        calls.append((a, k))
        return real(*a, **k)
    monkeypatch.setattr(store._fallback, "search", spy)
    return calls


# chromadb's EphemeralClient shares one in-memory system per settings tuple
# (SharedSystemClient) — same-named collections leak across store instances.
def _store(db, name):
    return ChromaStore(db, collection=name)     # path=None -> EphemeralClient


class TestRealPath:
    def test_obvious_nearest_ranks_first(self, monkeypatch):
        emb = MockEmbeddingProvider()
        store = _store(_seeded(emb), "t282_rank")
        degraded = _fallback_spy(store, monkeypatch)
        q = "where is my snake plant"
        out = store.search(q, top_k=3)
        assert store._col is not None and degraded == []   # real chroma path
        assert len(out) == 3
        assert out[0][1]["summary"] == ROWS[0][1]
        scores = [s for s, _ in out]
        assert scores[0] > scores[1] > scores[2]
        # score = 0.5*sim + 0.5*conf; the collection uses cosine space, so
        # sim = 1 - cosine_distance = cos, and with uniform conf=0.5 every
        # score is exactly 0.5*cos + 0.25 (cos recomputed here).
        qv = emb.embed(q)
        for score, m in out:
            assert score == pytest.approx(
                0.5 * cosine(qv, emb.embed(m["summary"])) + 0.25, abs=1e-3)

    def test_blend_rewards_confidence(self, monkeypatch):
        # identical text -> identical embeddings and distances: confidence is
        # the ONLY thing that can separate the scores, by 0.5 * (0.95 - 0.05)
        emb = MockEmbeddingProvider()
        text = "the red kite festival is on saturday"
        db = _seeded(emb, [("object", text, 0.95), ("object", text, 0.05)])
        store = _store(db, "t282_blend")
        degraded = _fallback_spy(store, monkeypatch)
        out = store.search("kite festival", top_k=2)
        assert degraded == [] and len(out) == 2
        by_conf = {m["confidence"]: s for s, m in out}
        assert by_conf[0.95] > by_conf[0.05]         # the confident one wins
        assert by_conf[0.95] - by_conf[0.05] == pytest.approx(0.45, abs=1e-3)

    def test_kind_filter(self, monkeypatch):
        emb = MockEmbeddingProvider()
        store = _store(_seeded(emb), "t282_kind")
        degraded = _fallback_spy(store, monkeypatch)
        out = store.search("owed lease friday", kind="commitment", top_k=3)
        assert degraded == []
        assert len(out) == 2                     # only 2 commitments exist
        assert all(m["kind"] == "commitment" for _, m in out)
        assert out[0][1]["summary"] == ROWS[2][1]   # the lease, not the dentist

    def test_empty_db_returns_empty(self):
        store = _store(MemoryDB(":memory:"), "t282_empty")
        assert store.search("anything", top_k=3) == []
        assert store._col is not None    # real client built; early return fired

    def test_blend_reorders_and_matches_linear(self, monkeypatch):
        # The #395 core symptom AND the ordering guarantee in one scenario.
        # `plants` is the LEAST similar of the four to the query but has the
        # HIGHEST confidence, so the 0.5*sim + 0.5*conf blend makes it the
        # winner while raw cosine distance ranks it dead last. This forces a
        # genuine reorder that:
        #   - the re-score/re-sort MUST perform (without it, chroma's raw-
        #     distance order wins and top-1 is the most-similar/low-conf row),
        #   - the full-candidate over-fetch MUST feed (with n_results=top_k the
        #     blended winner sits beyond the distance-truncated window and is
        #     dropped before the blend ever sees it).
        # So the real chroma path must agree with the linear fallback on the
        # ENTIRE ranking — order and scores — not merely the top-1.
        emb = MockEmbeddingProvider()
        rows = [
            ("object", "remember to water the office plants on friday", 0.95),
            ("object", "the ferry to the island leaves at noon", 0.05),
            ("object", "the ferry to the island departs each morning", 0.05),
            ("object", "the island ferry schedule is posted at the dock", 0.05),
        ]
        db = _seeded(emb, rows)
        store = _store(db, "t282_reorder")
        degraded = _fallback_spy(store, monkeypatch)
        q = "when does the island ferry leave"
        got = store.search(q, top_k=3)
        assert store._col is not None and degraded == []   # real chroma path
        ref = VectorStore(db, embedder=MockEmbeddingProvider()).search(q, top_k=3)
        assert [m["summary"] for _, m in got] == [m["summary"] for _, m in ref]
        assert [s for s, _ in got] == pytest.approx([s for s, _ in ref])
        # the blend genuinely reordered: the confident-but-least-similar memory
        # is top-1, NOT the row chroma's raw distance would rank first.
        assert got[0][1]["summary"] == rows[0][1]
        qv = emb.embed(q)
        raw_top = max(rows, key=lambda r: cosine(qv, emb.embed(r[1])))[1]
        assert raw_top != rows[0][1]                       # raw top-1 is a DIFFERENT row
        assert cosine(qv, emb.embed(rows[0][1])) < cosine(qv, emb.embed(raw_top))


class TestStableMemoryIdKeys:
    """Issue #409: vectors are keyed by the STABLE memory_id, not the transient
    row index — and kind isolation lives in the query (a where={"kind": ...}
    metadata filter), not the upsert set. The pinned symptom is the
    IndexError->silent-degradation route: keyed positionally, a broad upsert of
    N rows followed by a narrower kind= re-upsert of M<N rows left stale ids
    M..N-1 in the collection; a stale hit made `rows[int(idx)]` raise
    IndexError, the blanket except swallowed it, and the chroma path quietly
    fell back to the linear scan until the collection was dropped."""

    def test_broad_then_narrow_kind_search_stays_on_chroma(self, monkeypatch):
        # The #409 core: a broad search() upserts all N rows; a narrower kind=
        # search() must still be served by the chroma path — no silent degrade.
        # The query text IS an object memory's summary, so on row-index keys the
        # stale positional id of that object ranks top-2 in the narrow query and
        # `rows[stale]` raises IndexError -> fallback (the spy catches it).
        emb = MockEmbeddingProvider()
        store = _store(_seeded(emb), "t409_degrade")
        degraded = _fallback_spy(store, monkeypatch)
        q = ROWS[3][1]                                  # the passport OBJECT text
        store.search(q, top_k=3)                        # broad: upserts all N
        out = store.search(q, kind="commitment", top_k=3)   # narrow: M < N
        assert store._col is not None and degraded == []    # chroma handled BOTH
        assert len(out) == 2                          # only 2 commitments exist
        assert all(m["kind"] == "commitment" for _, m in out)

    def test_kind_filter_never_surfaces_another_kinds_vector(self, monkeypatch):
        # Keyed by memory_id, the persistent collection accumulates rows across
        # ALL kind= filters, so the broad upsert below leaves object vectors in
        # the collection. The kind= query must still return ONLY commitments —
        # enforced by the query's where filter, not by what's in the upsert set.
        emb = MockEmbeddingProvider()
        store = _store(_seeded(emb), "t409_isolation")
        degraded = _fallback_spy(store, monkeypatch)
        store.search("anything", top_k=5)               # broad upsert, all kinds
        q = ROWS[3][1]                                  # matches an OBJECT exactly
        out = store.search(q, kind="commitment", top_k=5)
        assert degraded == []                           # real chroma path, not fallback
        assert len(out) == 2                            # only 2 commitments exist
        assert all(m["kind"] == "commitment" for _, m in out)
        assert all(m["summary"] != q for _, m in out)   # the object did not leak

    def test_evict_deletes_one_vector_and_keeps_the_collection(self, monkeypatch):
        # The #409 bonus: keyed by memory_id, evict() deletes exactly that one
        # vector instead of dropping the whole collection (the wart the old
        # forget-hooks comment called out). The rest of the index survives and
        # the next search still runs on the real chroma path.
        emb = MockEmbeddingProvider()
        db = _seeded(emb)
        store = _store(db, "t409_evict")
        degraded = _fallback_spy(store, monkeypatch)
        store.search("snake plant", top_k=3)            # build + populate
        col = store._col
        assert col is not None and col.count() == len(ROWS)
        victim = next(m["id"] for m in db.memories() if m["summary"] == ROWS[0][1])
        db.purge_memory(victim)                         # the row is forgotten...
        store.evict(victim)                             # ...so its vector must go too
        assert store._col is col                        # collection NOT dropped
        assert col.count() == len(ROWS) - 1             # exactly one vector deleted
        out = store.search("where is my snake plant", top_k=len(ROWS))
        assert degraded == []                           # still the real chroma path
        assert all(m["id"] != victim for _, m in out)   # dead id never surfaces


class TestLinearFallback:
    def test_query_failure_degrades_to_linear(self, monkeypatch):
        # resilience: a broken collection query must not lose recall — the
        # answer comes back via VectorStore's linear scan, sorted by blended
        # score, so the confident memory takes the top rank despite being the
        # LESS similar of the two (the blend flips the rank here).
        emb = MockEmbeddingProvider()
        conf_txt, sim_txt = "kite festival", "kite festival saturday picnic"
        db = _seeded(emb, [("event", conf_txt, 0.95), ("event", sim_txt, 0.05)])
        store = _store(db, "t282_fallback")
        q = "kite festival saturday"
        store.search(q, top_k=2)                        # build the collection
        def boom(**kwargs):
            raise RuntimeError("chroma down")
        monkeypatch.setattr(store._col, "query", boom)
        got = store.search(q, top_k=2)
        ref = VectorStore(db, embedder=MockEmbeddingProvider()).search(q, top_k=2)
        assert [m["summary"] for _, m in got] == [m["summary"] for _, m in ref]
        assert [s for s, _ in got] == pytest.approx([s for s, _ in ref])
        assert got[0][1]["summary"] == conf_txt
        qv = emb.embed(q)
        assert cosine(qv, emb.embed(conf_txt)) < cosine(qv, emb.embed(sim_txt))
