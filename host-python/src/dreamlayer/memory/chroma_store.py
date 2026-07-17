"""ChromaDB persistent vector store — the Mac-Brain-tier semantic recall.

ADD-alongside: new sibling. Retriever-compatible `search(query, kind, top_k)`.
Lazy-imports chromadb (extras group `memory`); when absent, delegates to
VectorStore (which itself falls back to the exact linear scan). So behaviour is
always correct — Chroma only adds persistence + speed when installed.
"""
from __future__ import annotations
import logging

from .embeddings import MockEmbeddingProvider, unpack_embedding
from .vector_store import VectorStore

log = logging.getLogger("dreamlayer.chroma_store")

try:  # optional dep — extras group `memory`
    import chromadb  # type: ignore
    _HAS_CHROMA = True
except ImportError:
    _HAS_CHROMA = False


class ChromaStore:
    available = _HAS_CHROMA

    def __init__(self, db, embedder=None, path: str | None = None, collection: str = "memories"):
        self.db = db
        self.embedder = embedder or MockEmbeddingProvider()
        self._fallback = VectorStore(db, embedder=self.embedder)
        self._client = None
        self._col = None
        self._path = path
        self._collection = collection

    def _get_col(self):
        if self._col is not None:
            return self._col
        if not _HAS_CHROMA:
            return None
        try:
            self._client = (
                chromadb.PersistentClient(path=self._path) if self._path
                else chromadb.EphemeralClient()
            )
            # Cosine space so sim = 1 - cosine_distance is exactly cosine
            # similarity — chroma's default is squared-L2, which the `1 - dist`
            # read below would misinterpret as cosine (issue #395).
            self._col = self._client.get_or_create_collection(
                self._collection, metadata={"hnsw:space": "cosine"})
        except Exception as exc:
            log.error("[chroma_store] init failed: %s; linear fallback", exc)
            return None
        return self._col

    def search(self, query: str, kind=None, top_k: int = 3):
        col = self._get_col()
        if col is None:
            return self._fallback.search(query, kind=kind, top_k=top_k)
        try:
            rows = list(self.db.memories(kind=kind))
            if not rows:
                return []
            ids, embs, metas = [], [], []
            for i, m in enumerate(rows):
                emb = unpack_embedding(m["embedding"]) if m.get("embedding") else self.embedder.embed(m["summary"])
                conf = m.get("confidence")
                conf = 0.5 if conf is None else float(conf)   # explicit 0.0 stays 0.0
                ids.append(str(i)); embs.append(emb); metas.append({"conf": conf})
            col.upsert(ids=ids, embeddings=embs, metadatas=metas)
            # Chroma pre-ranks by raw distance, so asking for only top_k could
            # drop a high-confidence memory whose blended score would win. Fetch
            # every candidate, then re-score with the confidence blend and
            # re-sort — the same semantics VectorStore._linear uses, so the two
            # paths agree on the ranking by construction (issue #395).
            res = col.query(query_embeddings=[self.embedder.embed(query)], n_results=len(ids))
            out = []
            for idx, dist in zip(res["ids"][0], res["distances"][0]):
                m = rows[int(idx)]
                sim = 1.0 - float(dist)   # cosine space -> sim = 1 - cosine_distance = cos
                conf = m.get("confidence")
                conf = 0.5 if conf is None else float(conf)   # explicit 0.0 stays 0.0
                out.append((0.5 * sim + 0.5 * conf, m))
            out.sort(key=lambda x: x[0], reverse=True)
            return out[:top_k]
        except Exception as exc:
            log.error("[chroma_store] query failed: %s; linear fallback", exc)
            return self._fallback.search(query, kind=kind, top_k=top_k)

    # -- forget hooks: wired into Retriever.purge_* so this store is not
    # purge-blind (audit 2026-07-14). Chroma keyed vectors by transient row
    # index, not memory_id, so a single vector can't be precisely targeted;
    # both hooks therefore drop the whole persisted collection and let the next
    # search re-derive it from the (now-purged) live DB rows — no residue, no
    # orphaned vectors. Best-effort + fallback delegation; never raises into a
    # forget path.
    def evict(self, memory_id: int) -> None:
        self._drop_collection()
        self._fallback.evict(memory_id)

    def purge_all(self) -> None:
        self._drop_collection()
        self._fallback.purge_all()

    def _drop_collection(self) -> None:
        if self._client is None and self._col is None:
            return
        try:
            if self._client is not None:
                self._client.delete_collection(self._collection)
        except Exception as exc:
            log.warning("[chroma_store] collection drop failed: %s", exc)
        self._col = None
