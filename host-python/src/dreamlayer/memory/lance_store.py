"""LanceDB zero-server columnar vector store — on-disk alternative to Chroma.

ADD-alongside: new sibling, Retriever-compatible. Lazy-imports lancedb (extras
group `memory`); when absent it delegates to VectorStore (linear fallback).
"""
from __future__ import annotations
import logging

from .embeddings import MockEmbeddingProvider, unpack_embedding
from .retrieval import HIDDEN_KINDS   # shared: kinds a kind=None recall hides
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
        import os
        import tempfile
        # tempfile, not a literal /tmp — Windows has no /tmp
        self._uri = uri or os.path.join(tempfile.gettempdir(), "dreamlayer-lance")
        self._table = table

    def search(self, query: str, kind=None, top_k: int = 3):
        if not _HAS_LANCE:
            return self._fallback.search(query, kind=kind, top_k=top_k)
        try:
            rows = list(self.db.memories(kind=kind))
            if kind is None:                      # mirror the linear reference:
                rows = [m for m in rows            # a kind-less recall hides
                        if m.get("kind") not in HIDDEN_KINDS]  # stasis bookmarks
            if not rows:
                return []
            data = []
            for i, m in enumerate(rows):
                emb = unpack_embedding(m["embedding"]) if m.get("embedding") else self.embedder.embed(m["summary"])
                conf = m.get("confidence")
                conf = 0.5 if conf is None else float(conf)   # explicit 0.0 stays 0.0
                data.append({"idx": i, "vector": emb, "conf": conf})
            conn = lancedb.connect(self._uri)
            tbl = conn.create_table(self._table, data=data, mode="overwrite")
            # Lance ranks by RAW vector distance; the confidence blend can
            # reorder neighbours, so asking for only top_k could drop a
            # high-confidence memory whose blended score would win. Over-fetch
            # every candidate, re-score with the confidence blend, then re-sort
            # — the same semantics VectorStore._linear uses, so the two paths
            # agree on the ranking by construction (issue #395).
            q = tbl.search(self.embedder.embed(query))
            # Request cosine so `1 - _distance` IS cosine similarity. Lance
            # defaults to L2, which the `1 - dist` read below would misinterpret
            # as cosine. `.metric` was renamed `.distance_type` across versions;
            # try both. If NEITHER setter exists we cannot force cosine, so fall
            # through to the linear scan rather than silently read L2 as cosine —
            # the comment promised this fallback but the code used to proceed on
            # default L2, reintroducing the very bug this guards (refute 2026-07-17).
            if hasattr(q, "metric"):
                q = q.metric("cosine")
            elif hasattr(q, "distance_type"):
                q = q.distance_type("cosine")
            else:
                return self._fallback.search(query, kind=kind, top_k=top_k)
            hits = q.limit(len(rows)).to_list()
            out = []
            for h in hits:
                m = rows[int(h["idx"])]
                sim = 1.0 - float(h.get("_distance", 0.0))   # cosine dist -> sim
                conf = m.get("confidence")
                conf = 0.5 if conf is None else float(conf)   # explicit 0.0 stays 0.0
                out.append((0.5 * sim + 0.5 * conf, m))
            out.sort(key=lambda x: x[0], reverse=True)
            return out[:top_k]
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
