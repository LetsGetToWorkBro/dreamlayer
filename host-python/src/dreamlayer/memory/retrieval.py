from __future__ import annotations
from .embeddings import MockEmbeddingProvider, cosine, unpack_embedding


class Retriever:
    """Memory recall: ANN-accelerated when a live index is wired, exact
    linear cosine scan otherwise (identical scoring either way).

    Score = 0.5 * similarity + 0.5 * confidence — unchanged contract:
    search() returns [(score, memory_dict)] best-first.
    """

    # ANN over-fetch: the confidence blend can reorder neighbors, so pull
    # more candidates than top_k before blending.
    ANN_CANDIDATES = 4

    def __init__(self, db, embedder=None, ann=None):
        self.db = db
        self.embedder = embedder or MockEmbeddingProvider()
        self.ann = ann                       # PersistentAnnIndex or None

    def index_memory(self, memory_id: int, embedding) -> None:
        """Keep the ANN index in step with an ingest (no-op without one)."""
        if self.ann is not None and embedding:
            self.ann.add(memory_id, embedding)

    def purge_memory(self, memory_id: int) -> None:
        """Forget one memory *everywhere* — the row and its vector. Without
        the ANN eviction, a "forget that" left the embedding in the .usearch
        index forever: recall could still surface it and the index grew with
        the dead. Keep the two stores in step."""
        self.db.purge_memory(memory_id)
        if self.ann is not None:
            self.ann.remove(memory_id)

    def purge_all(self) -> None:
        """Forget everything — rows and the whole index."""
        self.db.purge_all()
        if self.ann is not None:
            self.ann.rebuild(self.db)        # db is now empty → index cleared

    def search(self, query: str, kind=None, top_k=3):
        qv = self.embedder.embed(query)

        if self.ann is not None and getattr(self.ann, "live", False) \
                and len(self.ann) > 0:
            hits = self.ann.search(qv, k=max(top_k * self.ANN_CANDIDATES, 16))
            if hits:
                scored = []
                for mid, sim in hits:
                    m = self.db.memory(mid)
                    if m is None or (kind and m.get("kind") != kind):
                        continue
                    score = 0.5 * sim + 0.5 * (m.get("confidence") or 0.5)
                    scored.append((score, m))
                scored.sort(key=lambda x: x[0], reverse=True)
                if scored:
                    return scored[:top_k]
            # empty/failed ANN result → exact scan below (never silently
            # return nothing because an index was cold)

        scored = []
        for m in self.db.memories(kind=kind):
            emb = unpack_embedding(m.get("embedding")) \
                or self.embedder.embed(m["summary"])
            sim = cosine(qv, emb)
            score = 0.5 * sim + 0.5 * (m.get("confidence") or 0.5)
            scored.append((score, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]
