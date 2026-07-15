"""LanceDB zero-server columnar vector store — on-disk alternative to Chroma.

ADD-alongside: new sibling, Retriever-compatible. Lazy-imports lancedb (extras
group `memory`); when absent it delegates to VectorStore (linear fallback).
"""
from __future__ import annotations
import logging

from .embeddings import MockEmbeddingProvider, unpack_embedding
from .vector_store import VectorStore

log = logging.getLogger("dreamlayer.lance_store")

try:  # optional dep — extras group `memory`
    import lancedb  # type: ignore
    _HAS_LANCE = True
except ImportError:
    _HAS_LANCE = False


class LanceStore:
    available = _HAS_LANCE

    def __init__(self, db, embedder=None, uri: str | None = None, table: str = "memories"):
        self.db = db
        self.embedder = embedder or MockEmbeddingProvider()
        self._fallback = VectorStore(db, embedder=self.embedder)
        self._uri = uri or "/tmp/dreamlayer-lance"
        self._table = table

    def search(self, query: str, kind=None, top_k: int = 3):
        if not _HAS_LANCE:
            return self._fallback.search(query, kind=kind, top_k=top_k)
        try:
            rows = list(self.db.memories(kind=kind))
            if not rows:
                return []
            data = []
            for i, m in enumerate(rows):
                emb = unpack_embedding(m["embedding"]) if m.get("embedding") else self.embedder.embed(m["summary"])
                data.append({"idx": i, "vector": emb, "conf": m.get("confidence") or 0.5})
            conn = lancedb.connect(self._uri)
            tbl = conn.create_table(self._table, data=data, mode="overwrite")
            hits = tbl.search(self.embedder.embed(query)).limit(top_k).to_list()
            out = []
            for h in hits:
                m = rows[int(h["idx"])]
                sim = 1.0 - float(h.get("_distance", 0.0))
                out.append((0.5 * sim + 0.5 * (m.get("confidence") or 0.5), m))
            return out
        except Exception as exc:
            log.error("[lance_store] query failed: %s; linear fallback", exc)
            return self._fallback.search(query, kind=kind, top_k=top_k)

    # -- forget hooks: wired into Retriever.purge_* so this store is not
    # purge-blind (audit 2026-07-14). Lance keyed rows by transient row index
    # (mode="overwrite" rebuilds the table from live DB rows on every search),
    # so a forget just needs to drop the persisted table; the next search
    # rebuilds it without the purged row. Best-effort + fallback delegation.
    def evict(self, memory_id: int) -> None:
        self._drop_table()
        self._fallback.evict(memory_id)

    def purge_all(self) -> None:
        self._drop_table()
        self._fallback.purge_all()

    def _drop_table(self) -> None:
        if not _HAS_LANCE:
            return
        try:
            conn = lancedb.connect(self._uri)
            if self._table in conn.table_names():
                conn.drop_table(self._table)
        except Exception as exc:
            log.warning("[lance_store] table drop failed: %s", exc)
