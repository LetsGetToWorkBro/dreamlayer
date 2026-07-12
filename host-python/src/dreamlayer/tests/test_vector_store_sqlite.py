"""sqlite-vec persistent Vault index: parity with the linear reference,
cosine correctness, kind filtering, incremental persistence, and graceful
degradation. Real-index tests need the sqlite-vec extension (importorskip);
the degradation test always runs."""
import pytest

from dreamlayer.memory.db import MemoryDB
from dreamlayer.memory.embeddings import HashingEmbeddingProvider
from dreamlayer.memory.vector_store import VectorStore
from dreamlayer.memory.retrieval import Retriever

ROWS = [
    ("object", "snake plant on the windowsill, water every two weeks"),
    ("object", "bike locked at the north rack on 4th and Alder"),
    ("commitment", "Marcus is owed the signed lease by Friday"),
    ("object", "passport is in the top drawer of the desk"),
    ("commitment", "call the dentist about Tuesday at 3pm"),
]


def _seeded(emb, with_embeddings=True):
    db = MemoryDB(":memory:")
    for kind, summary in ROWS:
        db.add_memory(kind, summary,
                      embedding=emb.embed(summary) if with_embeddings else None,
                      confidence=0.6)
    return db


class TestDegradation:
    def test_absent_matches_linear(self, monkeypatch):
        monkeypatch.setattr(VectorStore, "available", False)
        monkeypatch.setattr(
            "dreamlayer.memory.vector_store._HAS_SQLITE_VEC", False)
        emb = HashingEmbeddingProvider()
        db = _seeded(emb)
        got = VectorStore(db, embedder=emb).search("snake plant", top_k=3)
        ref = Retriever(db, embedder=emb).search("snake plant", top_k=3)
        assert [m["summary"] for _, m in got] == [m["summary"] for _, m in ref]


class TestRealIndex:
    def setup_method(self):
        pytest.importorskip("sqlite_vec")

    def test_indexed_matches_linear_reference(self):
        emb = HashingEmbeddingProvider()
        db = _seeded(emb)
        vs = VectorStore(db, embedder=emb)
        assert vs.available is True
        for q in ("where is my snake plant", "the lease", "passport drawer"):
            got = [m["summary"] for _, m in vs.search(q, top_k=3)]
            ref = [m["summary"] for _, m in
                   Retriever(db, embedder=emb).search(q, top_k=3)]
            assert got == ref, q

    def test_kind_filter(self):
        emb = HashingEmbeddingProvider()
        db = _seeded(emb)
        vs = VectorStore(db, embedder=emb)
        out = vs.search("owed by friday", kind="commitment", top_k=3)
        assert out and all(m["kind"] == "commitment" for _, m in out)

    def test_index_is_persistent_and_incremental(self):
        emb = HashingEmbeddingProvider()
        db = _seeded(emb)
        vs = VectorStore(db, embedder=emb)
        vs.search("plant", top_k=2)
        assert len(vs._indexed_ids) == len(ROWS)      # built once
        # a new memory is picked up on the next search without a full rebuild
        db.add_memory("object", "umbrella by the front door",
                      embedding=emb.embed("umbrella by the front door"),
                      confidence=0.6)
        hits = [m["summary"] for _, m in vs.search("umbrella", top_k=1)]
        assert hits == ["umbrella by the front door"]
        assert len(vs._indexed_ids) == len(ROWS) + 1

    def test_dim_change_rebuilds_table(self):
        # seed without stored vectors so both the query and the indexed rows are
        # re-embedded by the *current* embedder — a genuine dim-change rebuild
        emb = HashingEmbeddingProvider()
        db = _seeded(emb, with_embeddings=False)
        vs = VectorStore(db, embedder=emb)
        vs.search("plant", top_k=1)
        assert vs._dim == HashingEmbeddingProvider().DIM
        vs.embedder = HashingEmbeddingProvider(dim=128)   # new embedding space
        got = [m["summary"] for _, m in vs.search("passport", top_k=2)]
        ref = [m["summary"] for _, m in
               Retriever(db, embedder=vs.embedder).search("passport", top_k=2)]
        assert vs._dim == 128 and len(vs._indexed_ids) == len(ROWS) and got == ref
