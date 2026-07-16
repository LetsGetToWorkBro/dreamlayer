"""ChromaDB real-path semantic recall (issue #282): ranking, the
0.5*sim + 0.5*confidence blend, kind filtering, the empty-DB early return,
and the linear fallback. Needs chromadb (importorskip); path=None builds an
EphemeralClient (no disk state) and the default MockEmbeddingProvider is
deterministic, so ranking and score assertions are stable across runs."""
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
        # score = 0.5*sim + 0.5*conf; chroma's default squared-L2 distance on
        # the mock's unit vectors gives sim = 2cos - 1, so with uniform
        # conf=0.5 every score is exactly cos - 0.25 (cos recomputed here).
        qv = emb.embed(q)
        for score, m in out:
            assert score == pytest.approx(
                cosine(qv, emb.embed(m["summary"])) - 0.25, abs=1e-3)

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
