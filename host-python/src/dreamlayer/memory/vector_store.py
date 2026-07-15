"""Vector search inside SQLite via sqlite-vec — a Retriever-compatible store.

ADD-alongside: sibling to retrieval.py with the same ``search(query, kind,
top_k)`` shape as Retriever, so it's a drop-in where a caller wants ANN over the
same MemoryDB. Lazy-imports sqlite-vec (extras group ``memory``); when absent —
or on any error — it degrades to the exact linear-cosine scan Retriever does, so
results are always correct, just without the index.

What changed for AAA: the index is now **persistent and cosine-correct**. It
lives in the MemoryDB's own connection as a ``vec0`` virtual table created with
``distance_metric=cosine`` (so ``similarity = 1 - distance`` is exactly cosine,
not the L2-vs-cosine mismatch the ephemeral version had), and it is synced
incrementally instead of rebuilt on every query. The linear scan stays the
reference the tests pin the index against.

Privacy: reads never need the guard; the store only indexes what MemoryDB
already holds, and writes are gated upstream by allow_capture().
"""
from __future__ import annotations
import logging

from .embeddings import MockEmbeddingProvider, cosine, unpack_embedding

log = logging.getLogger("dreamlayer.vector_store")

try:  # optional dep — extras group `memory`
    import sqlite_vec  # type: ignore
    _HAS_SQLITE_VEC = True
except ImportError:
    sqlite_vec = None                   # type: ignore
    _HAS_SQLITE_VEC = False


class VectorStore:
    """Semantic search over MemoryDB rows.

    Parameters mirror Retriever: ``db`` (a MemoryDB) and an optional
    ``embedder``. With sqlite-vec present it maintains a persistent vec0 index
    (cosine) in ``db.conn`` for fast top-k; without it, the linear scan."""

    available = _HAS_SQLITE_VEC

    def __init__(self, db, embedder=None):
        self.db = db
        self.embedder = embedder or MockEmbeddingProvider()
        self._loaded = False             # extension loaded into db.conn?
        self._dim = None                 # dim the vec table was built for
        self._indexed_ids: set[int] = set()

    # -- linear fallback (the reference; identical to Retriever scoring) -------
    def _emb_of(self, m):
        # stored embeddings are packed float32 BLOBs (same read path as
        # Retriever); fall back to re-embedding the summary when absent
        if m.get("embedding"):
            return unpack_embedding(m["embedding"])
        return self.embedder.embed(m["summary"])

    def _linear(self, query, kind, top_k):
        qv = self.embedder.embed(query)
        scored = []
        for m in self.db.memories(kind=kind):
            sim = cosine(qv, self._emb_of(m))
            score = 0.5 * sim + 0.5 * (m.get("confidence") or 0.5)
            scored.append((score, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]

    def search(self, query: str, kind=None, top_k: int = 3):
        if not _HAS_SQLITE_VEC:
            return self._linear(query, kind, top_k)
        try:
            out = self._search_indexed(query, kind, top_k)
            if out is not None:
                return out
        except Exception as exc:
            log.error("[vector_store] indexed search failed: %s; linear", exc)
        return self._linear(query, kind, top_k)

    # -- persistent, cosine-correct vec0 index --------------------------------
    def _ensure_loaded(self) -> bool:
        if self._loaded:
            return True
        try:
            self.db.conn.enable_load_extension(True)
            sqlite_vec.load(self.db.conn)
            self.db.conn.enable_load_extension(False)
            self._loaded = True
            return True
        except Exception as exc:         # sqlite built without extension load
            log.warning("[vector_store] cannot load sqlite-vec: %s", exc)
            return False

    def _ensure_table(self, dim: int) -> None:
        # a dim change (embedder space changed) means a fresh table. Every write
        # to the shared db.conn rides the MemoryDB RLock — this table lives in
        # the same connection as the memories table, so an unlocked write here
        # would race the off-thread capture writer the lock exists to serialize
        # (audit 2026-07-14).
        if self._dim == dim:
            return
        with self.db._lock:
            self.db.conn.execute("DROP TABLE IF EXISTS memory_vec")
            self.db.conn.execute(
                "CREATE VIRTUAL TABLE memory_vec USING "
                f"vec0(memory_id integer primary key, kind text, "
                f"embedding float[{dim}] distance_metric=cosine)")
        self._dim = dim
        self._indexed_ids = set()

    def _sync(self, dim: int) -> None:
        """Index any memories not yet in the vec table (incremental)."""
        for m in self.db.memories():
            mid = m["id"]
            if mid in self._indexed_ids:
                continue
            emb = self._emb_of(m)
            if len(emb) != dim:
                raise ValueError("embedding dim mismatch")
            with self.db._lock:
                self.db.conn.execute(
                    "INSERT OR REPLACE INTO memory_vec(memory_id, kind, embedding) "
                    "VALUES (?, ?, ?)",
                    (mid, m.get("kind") or "", sqlite_vec.serialize_float32(emb)))
            self._indexed_ids.add(mid)

    def evict(self, memory_id: int) -> None:
        """Drop a purged memory's vector so it can never be recalled again and
        never occupies a top-k slot. Without this the vec table only ever grew:
        a forgotten memory's row survived, and a search that fetched it (its DB
        row gone) silently returned fewer than top_k live matches.

        Wired into Retriever.purge_memory (audit 2026-07-14): "forget that" must
        reach this table too — it lives inside db.conn, which the DB-level purge
        never touched, so a forgotten memory left a fully recallable embedding
        the moment this store was enabled."""
        if not self._ensure_loaded():
            return
        with self.db._lock:
            self.db.conn.execute(
                "DELETE FROM memory_vec WHERE memory_id=?", (memory_id,))
        self._indexed_ids.discard(memory_id)

    def purge_all(self) -> None:
        """Empty the whole vec table — the erase-everything hook, wired into
        Retriever.purge_all. memory_vec lives in db.conn but is NOT one of the
        tables db.purge_all() deletes, so without this an erase left every
        embedding behind (a privacy residue) the moment this store was enabled.
        No-op when the extension never loaded (table was never created)."""
        if not self._ensure_loaded():
            return
        with self.db._lock:
            self.db.conn.execute("DELETE FROM memory_vec")
        self._indexed_ids.clear()

    def _search_indexed(self, query, kind, top_k):
        if not self._ensure_loaded():
            return None
        qv = self.embedder.embed(query)
        dim = len(qv)
        self._ensure_table(dim)
        self._sync(dim)
        if not self._indexed_ids:
            return []
        params = [sqlite_vec.serialize_float32(qv)]
        where = "embedding MATCH ?"
        if kind is not None:
            where += " AND kind = ?"
            params.append(kind)
        # Over-fetch so stale rows (a memory purged from the DB but not yet
        # evicted here) can't starve the result below top_k — we refill from
        # the wider candidate set, keeping "results are always correct" true
        # even if a caller forgot to evict().
        params.append(max(top_k * 4, 16))
        with self.db._lock:
            cur = self.db.conn.execute(
                f"SELECT memory_id, distance FROM memory_vec WHERE {where} "
                "ORDER BY distance LIMIT ?", params)
            rows = cur.fetchall()
        out = []
        for mid, dist in rows:
            m = self.db.get_memory(mid) if hasattr(self.db, "get_memory") else None
            if m is None:
                m = next((x for x in self.db.memories() if x["id"] == mid), None)
            if m is None:
                continue           # dead row (purged) — skip, don't count it
            sim = 1.0 - float(dist)      # cosine distance → cosine similarity
            conf = m.get("confidence")
            conf = 0.5 if conf is None else float(conf)   # 0.0 stays 0.0
            score = 0.5 * sim + 0.5 * conf
            out.append((score, dict(m)))
        out.sort(key=lambda x: x[0], reverse=True)
        return out[:top_k]
