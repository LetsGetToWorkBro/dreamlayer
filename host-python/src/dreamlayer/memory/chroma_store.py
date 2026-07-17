"""ChromaDB persistent vector store — the Mac-Brain-tier semantic recall.

ADD-alongside: new sibling. Retriever-compatible `search(query, kind, top_k)`.
Lazy-imports chromadb (extras group `memory`); when absent, delegates to
VectorStore (which itself falls back to the exact linear scan). So behaviour is
always correct — Chroma only adds persistence + speed when installed.
"""
from __future__ import annotations
import logging

from .embeddings import MockEmbeddingProvider, unpack_embedding
from .retrieval import HIDDEN_KINDS   # shared: kinds a kind=None recall hides
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
            # Key vectors by the STABLE memory_id, mirroring vector_store.py —
            # never by row position. The old `str(i)` keys went stale the moment
            # a narrower kind= call re-upserted ids 0..M-1 over a collection
            # still holding M..N-1: a stale hit made `rows[int(idx)]` raise
            # IndexError and the blanket except silently degraded every later
            # query to the linear fallback (issue #409).
            #
            # Stable ids mean a persistent collection accumulates rows across
            # ALL kind= filters, so kind isolation must live in the QUERY (a
            # where={"kind": ...} metadata filter), not in the upsert set —
            # otherwise a kind="commitment" query could surface an object vector
            # a prior kind=None call upserted.
            rows = list(self.db.memories())
            if not rows:
                return []
            ids, embs, metas = [], [], []
            by_id = {}
            for m in rows:
                emb = unpack_embedding(m["embedding"]) if m.get("embedding") else self.embedder.embed(m["summary"])
                conf = m.get("confidence")
                conf = 0.5 if conf is None else float(conf)   # explicit 0.0 stays 0.0
                mid = str(m["id"])
                ids.append(mid); embs.append(emb)
                metas.append({"conf": conf, "kind": m.get("kind") or ""})
                by_id[mid] = m
            col.upsert(ids=ids, embeddings=embs, metadatas=metas)
            # Chroma pre-ranks by raw distance, so asking for only top_k could
            # drop a high-confidence memory whose blended score would win. Fetch
            # every candidate, then re-score with the confidence blend and
            # re-sort — the same semantics VectorStore._linear uses, so the two
            # paths agree on the ranking by construction (issue #395). Size the
            # window by the COLLECTION, not the live batch: stale vectors (rows
            # purged from the DB but not yet evicted here) still occupy query
            # slots, and a window sized to the live rows could truncate a live
            # candidate behind them.
            res = col.query(
                query_embeddings=[self.embedder.embed(query)],
                n_results=col.count(),
                where={"kind": kind} if kind is not None else None)
            out = []
            for mid, dist in zip(res["ids"][0], res["distances"][0]):
                m = by_id.get(mid)
                if m is None:
                    continue           # dead row (purged) — skip, don't count it
                if kind is None and m.get("kind") in HIDDEN_KINDS:
                    continue           # hidden bookmark — mirror the linear reference
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
    # purge-blind (audit 2026-07-14). Vectors are keyed by the stable memory_id,
    # so evict() deletes exactly that one vector — "forget that" leaves no
    # recallable embedding behind and the rest of the collection (and its HNSW
    # index) survives. purge_all() still drops the whole persisted collection:
    # erase-everything should leave no index residue at all, and the next search
    # re-derives it from the live DB rows. Best-effort + fallback delegation;
    # never raises into a forget path.
    def evict(self, memory_id: int) -> None:
        # Retry a transient _get_col() open failure a couple of times before
        # giving up: a PersistentClient that momentarily fails to open (a stale
        # lock, a slow disk) returns None here, and skipping the delete would
        # strand the forgotten vector's bytes on disk (not recallable — the DB
        # row is already gone — but a forget-completeness gap). _get_col re-opens
        # the client each call while _col is None, so a later attempt can win. A
        # persistent failure still just logs and delegates to the fallback —
        # best-effort, never raising into the forget path.
        col = None
        for _ in range(3):
            col = self._get_col()
            if col is not None:
                break
        if col is not None:
            try:
                col.delete(ids=[str(memory_id)])
            except Exception as exc:
                log.warning("[chroma_store] evict(%s) failed: %s", memory_id, exc)
        self._fallback.evict(memory_id)

    def purge_all(self) -> None:
        self._drop_collection()
        self._fallback.purge_all()

    def _drop_collection(self) -> None:
        # A PERSISTENT collection can hold a forgotten embedding even when THIS
        # instance never searched — a fresh process after a restart has
        # _client/_col both None, but the on-disk collection from a prior
        # session survives. Early-returning on `_client is None and _col is
        # None` left that collection undropped, so a forget/erase that ran
        # BEFORE any search left the forgotten embedding fully recallable on
        # disk (audit 2026-07-17). Lazily open the persistent client so the
        # on-disk collection is actually dropped.
        client = self._client
        if client is None and _HAS_CHROMA and self._path:
            try:
                client = chromadb.PersistentClient(path=self._path)
            except Exception as exc:
                log.warning("[chroma_store] client open for drop failed: %s", exc)
                client = None
        if client is not None:
            try:
                client.delete_collection(self._collection)
            except Exception as exc:
                log.warning("[chroma_store] collection drop failed: %s", exc)
        self._col = None
        self._client = None
