from __future__ import annotations
from .embeddings import MockEmbeddingProvider, cosine, unpack_embedding


def _confidence(m) -> float:
    """A memory's confidence, defaulting to 0.5 ONLY when absent. `or 0.5`
    coerced a legitimate 0.0 (a memory we're genuinely unsure of) up to 0.5,
    inflating its blended score — so a low-confidence chatter row could outrank
    a real answer. `None` means unset; 0.0 means known-unsure."""
    c = m.get("confidence")
    return 0.5 if c is None else float(c)


class Retriever:
    """Memory recall: ANN-accelerated when a live index is wired, exact
    linear cosine scan otherwise.

    Score = 0.5 * similarity + 0.5 * confidence; search() returns
    [(score, memory_dict)] best-first.

    ANN vs exact: the ANN index ranks by *similarity*, but the final score
    blends in confidence, so a high-confidence answer sitting just outside the
    similarity shortlist can be reordered above a nearer neighbour. We therefore
    over-fetch (ANN_CANDIDATES × top_k) and, crucially, fall through to the exact
    linear scan whenever the ANN shortlist yields FEWER than top_k results after
    filtering — so a kind= query is never starved by a kind-blind over-fetch, and
    a cold index never returns fewer than exist. The exact scan is authoritative;
    the ANN path is a fast approximation of it, not a claim of identical ranking.
    """

    # ANN over-fetch: the confidence blend can reorder neighbors, so pull
    # more candidates than top_k before blending. Wider than before so the
    # blend is less likely to promote a row from outside the shortlist.
    ANN_CANDIDATES = 8

    # Rows that ride the memories table but are NOT recall answers. A live
    # Stasis frame is stored as a kind="stasis" row so a held thought survives
    # a restart — but its summary is the wearer's verbatim unfinished sentence,
    # a bookmark, not something "what did I say about X" should surface. A
    # kind-less search excludes these by construction (a caller that explicitly
    # asks for kind="stasis" still gets them). When such a frame composts it is
    # rewritten as an ordinary kind="memory" row, which is findable as normal.
    HIDDEN_KINDS = frozenset({"stasis"})

    def __init__(self, db, embedder=None, ann=None, ember_store=None,
                 bias_store=None, bias_dir=None, vector_store=None):
        self.db = db
        self.embedder = embedder or MockEmbeddingProvider()
        self.ann = ann                       # PersistentAnnIndex or None
        # An optional ALTERNATE vector store (VectorStore/Chroma/Lance) that
        # indexes the same MemoryDB in its own table/collection. When one is
        # wired, forget must reach it too or it becomes purge-blind — its index
        # is NOT the ann/usearch one and NOT among the tables db.purge_* delete,
        # so a "forget that" would leave a fully recallable embedding behind
        # (audit 2026-07-14 HIGH). Duck-typed: anything exposing evict(id) and
        # purge_all(). None = no alternate store enabled (the default posture).
        self.vector_store = vector_store
        # The ember practice is a separate SQLite file that holds consolidated
        # cue+answer engrams. It is retention-immune by design, but the
        # wearer's erase-everything must reach it too — so purge_all() wipes it
        # here, at the primitive, not bolted onto each call-site. Duck-typed:
        # anything exposing purge_all() (an EmberStore) plugs in. None = no
        # ember file wired (the engram wipe is then a no-op).
        self.ember_store = ember_store
        # The REM consolidation bias (rem_bias.json) is keyed by memory content
        # identity, so forgetting a memory must also drop its rank opinion here
        # — otherwise a content-hash fingerprint of the forgotten memory (and a
        # rank-ghost that re-attaches on re-ingest) survives forget/erase (audit
        # 2026-07-14). Duck-typed: a RetrievalBias exposing discard()/clear().
        # bias_dir is the vault directory so the change is persisted, not just
        # applied to the in-memory copy that a restart would overwrite.
        self.bias_store = bias_store
        self.bias_dir = bias_dir

    def index_memory(self, memory_id: int, embedding) -> None:
        """Keep the ANN index in step with an ingest (no-op without one)."""
        if self.ann is not None and embedding:
            self.ann.add(memory_id, embedding)

    def _persist_bias(self) -> None:
        if self.bias_store is not None and self.bias_dir is not None:
            try:
                self.bias_store.save(self.bias_dir)
            except Exception:
                pass                          # a save failure must not block forget

    def purge_memory(self, memory_id: int) -> None:
        """Forget one memory *everywhere* — the row, its vector, and its REM
        consolidation opinion. Without the ANN eviction, a "forget that" left
        the embedding in the .usearch index forever; without the bias discard it
        left a content-hash fingerprint + rank-ghost in rem_bias.json. Keep all
        three stores in step."""
        # read the row BEFORE deleting it — the bias is keyed by kind+summary
        row = self.db.memory(memory_id) if self.bias_store is not None else None
        self.db.purge_memory(memory_id)
        if self.ann is not None:
            self.ann.remove(memory_id)
        if self.vector_store is not None:
            self.vector_store.evict(memory_id)   # alternate store, else purge-blind
        if row is not None:
            self.bias_store.discard(row.get("kind", ""), row.get("summary", ""))
            self._persist_bias()

    def purge_all(self) -> None:
        """Forget everything — rows, the whole index, the ember practice, and
        the REM consolidation bias.

        Erase-everything must erase everything, by construction: a caller that
        reaches for the retrieval primitive to wipe memory must not have to
        remember to also wipe the ember sidecar. Whatever ember store is wired
        goes with the rows (its own purge_all VACUUMs, so answer bytes leave
        the file, not just the pages)."""
        self.db.purge_all()
        if self.ann is not None:
            self.ann.rebuild(self.db)        # db is now empty → index cleared
        if self.vector_store is not None:
            self.vector_store.purge_all()    # alternate store's index emptied too
        if self.ember_store is not None:
            self.ember_store.purge_all()     # engrams + staged offers, VACUUMed
        if self.bias_store is not None:
            self.bias_store.clear()          # no consolidation fingerprints left
            self._persist_bias()

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
                    if kind is None and m.get("kind") in self.HIDDEN_KINDS:
                        continue                 # bookmarks aren't recall answers
                    score = 0.5 * sim + 0.5 * _confidence(m)
                    scored.append((score, m))
                scored.sort(key=lambda x: x[0], reverse=True)
                # Only trust the ANN shortlist when it actually produced enough
                # results. The over-fetch is kind-BLIND, so a kind= query whose
                # matching rows sit outside the sim-top-N gets starved: the
                # filter drops the wrong-kind neighbours and returns fewer than
                # top_k while more matches exist. Falling through to the exact
                # scan (which filters by kind and is exhaustive) restores them.
                if len(scored) >= top_k:
                    return scored[:top_k]
            # empty / short / failed ANN result → exact scan below (never
            # silently return fewer than exist because the index was cold or
            # kind-blind)

        scored = []
        for m in self.db.memories(kind=kind):
            if kind is None and m.get("kind") in self.HIDDEN_KINDS:
                continue                          # bookmarks aren't recall answers
            emb = unpack_embedding(m.get("embedding")) \
                or self.embedder.embed(m["summary"])
            sim = cosine(qv, emb)
            score = 0.5 * sim + 0.5 * _confidence(m)
            scored.append((score, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]
