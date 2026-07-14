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

    def __init__(self, db, embedder=None, ann=None, ember_store=None):
        self.db = db
        self.embedder = embedder or MockEmbeddingProvider()
        self.ann = ann                       # PersistentAnnIndex or None
        # The ember practice is a separate SQLite file that holds consolidated
        # cue+answer engrams. It is retention-immune by design, but the
        # wearer's erase-everything must reach it too — so purge_all() wipes it
        # here, at the primitive, not bolted onto each call-site. Duck-typed:
        # anything exposing purge_all() (an EmberStore) plugs in. None = no
        # ember file wired (the engram wipe is then a no-op).
        self.ember_store = ember_store

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
        """Forget everything — rows, the whole index, and the ember practice.

        Erase-everything must erase everything, by construction: a caller that
        reaches for the retrieval primitive to wipe memory must not have to
        remember to also wipe the ember sidecar. Whatever ember store is wired
        goes with the rows (its own purge_all VACUUMs, so answer bytes leave
        the file, not just the pages)."""
        self.db.purge_all()
        if self.ann is not None:
            self.ann.rebuild(self.db)        # db is now empty → index cleared
        if self.ember_store is not None:
            self.ember_store.purge_all()     # engrams + staged offers, VACUUMed

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
