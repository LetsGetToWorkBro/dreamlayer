"""Vector search inside SQLite via sqlite-vec — a Retriever-compatible store.

ADD-alongside: new sibling to retrieval.py. Same `search(query, kind, top_k)`
shape as Retriever, so it's a drop-in where a caller wants ANN over the same
MemoryDB. Lazy-imports sqlite-vec (extras group `memory`); when absent it
degrades to the exact linear-cosine scan Retriever already does — identical
results, just without the index.

Privacy: reads never need the guard; any write path must still be gated by an
allow_capture() check by the caller (this store only indexes what MemoryDB
already holds).
"""
from __future__ import annotations
import json
import logging

from .embeddings import MockEmbeddingProvider, cosine

log = logging.getLogger("dreamlayer.vector_store")

try:  # optional dep — extras group `memory`
    import sqlite_vec  # type: ignore
    _HAS_SQLITE_VEC = True
except ImportError:
    _HAS_SQLITE_VEC = False


class VectorStore:
    """Semantic search over MemoryDB rows.

    Parameters mirror Retriever: `db` (a MemoryDB) and an optional `embedder`
    (any EmbeddingProvider). With sqlite-vec present it builds a vec0 virtual
    table for fast top-k; without it, it falls back to the linear scan.
    """
    available = _HAS_SQLITE_VEC

    def __init__(self, db, embedder=None):
        self.db = db
        self.embedder = embedder or MockEmbeddingProvider()
        self._indexed = False

    # -- linear fallback (identical to Retriever.search scoring) --------------
    def _linear(self, query, kind, top_k):
        qv = self.embedder.embed(query)
        scored = []
        for m in self.db.memories(kind=kind):
            emb = json.loads(m["embedding"]) if m.get("embedding") else self.embedder.embed(m["summary"])
            sim = cosine(qv, emb)
            score = 0.5 * sim + 0.5 * (m.get("confidence") or 0.5)
            scored.append((score, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]

    def search(self, query: str, kind=None, top_k: int = 3):
        # sqlite-vec path is only worth it for large tables; for correctness and
        # to keep MemoryDB untouched we compute candidates the same way and let
        # the extension accelerate distance when available. The linear fallback
        # is always correct, so we use it unless a real index is wired.
        if not _HAS_SQLITE_VEC:
            return self._linear(query, kind, top_k)
        try:
            return self._search_indexed(query, kind, top_k)
        except Exception as exc:
            log.error("[vector_store] indexed search failed: %s; linear fallback", exc)
            return self._linear(query, kind, top_k)

    def _search_indexed(self, query, kind, top_k):
        # Build an ephemeral vec0 table over current rows, query KNN, join back.
        rows = list(self.db.memories(kind=kind))
        if not rows:
            return []
        import sqlite3

        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        qv = self.embedder.embed(query)
        dim = len(qv)
        conn.execute(f"CREATE VIRTUAL TABLE vec USING vec0(embedding float[{dim}])")
        by_rowid = {}
        for i, m in enumerate(rows, start=1):
            emb = json.loads(m["embedding"]) if m.get("embedding") else self.embedder.embed(m["summary"])
            if len(emb) != dim:  # embedder mismatch → give up to linear
                raise ValueError("embedding dim mismatch")
            conn.execute(
                "INSERT INTO vec(rowid, embedding) VALUES (?, ?)",
                (i, sqlite_vec.serialize_float32(emb)),
            )
            by_rowid[i] = m
        cur = conn.execute(
            "SELECT rowid, distance FROM vec WHERE embedding MATCH ? "
            "ORDER BY distance LIMIT ?",
            (sqlite_vec.serialize_float32(qv), top_k),
        )
        out = []
        for rowid, dist in cur.fetchall():
            m = by_rowid[rowid]
            sim = 1.0 - float(dist)  # cosine distance → similarity
            score = 0.5 * sim + 0.5 * (m.get("confidence") or 0.5)
            out.append((score, m))
        conn.close()
        return out
