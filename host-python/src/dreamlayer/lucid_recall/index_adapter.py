"""lucid_recall/index_adapter.py — the concrete memory_index for LucidRecall.

The audit noted LucidRecall's `memory_index.get(query) -> str` contract was
"implemented nowhere in src" — the router was wired to an interface that had no
real backend, so it could never actually answer a fact query. This adapter is
that backend: it reads the wearer's own memory through the Retriever (the same
ANN + exact-scan recall the rest of the system uses), and — when the optional
mem0 layer is present — consults it first, so the three previously-disjoint
lucid_recall pieces (router, Mem0Layer, the Retriever) now compose behind one
surface instead of sitting unwired beside each other.

Recall gating is upstream: LucidRecall.query() already short-circuits on
allow_recall(); this adapter only runs once a query is permitted.
"""
from __future__ import annotations


class RetrieverRecallIndex:
    """`get(query) -> str` over the real memory layer.

    Parameters
    ----------
    retriever : Retriever
        The orchestrator's memory retriever (ANN + exact scan).
    mem0 : Mem0Layer, optional
        When mem0 is installed, its semantic store is consulted first; a miss
        (or its absence) falls through to the Retriever, so the offline default
        behaves identically to a Retriever-only index.
    """

    def __init__(self, retriever, mem0=None):
        self._retriever = retriever
        self._mem0 = mem0

    def get(self, query: str) -> str:
        if not query:
            return ""
        if self._mem0 is not None:
            try:
                hits = self._mem0.search(query, limit=1)
                if hits:
                    top = hits[0]
                    text = top.get("text") if isinstance(top, dict) else str(top)
                    if text:
                        return text
            except Exception:
                pass                      # mem0 optional — fall through to core recall
        return self._best_summary(query)

    def _best_summary(self, query: str) -> str:
        try:
            scored = self._retriever.search(query, top_k=1)
        except Exception:
            return ""
        if not scored:
            return ""
        _, m = scored[0]
        return (m.get("summary") or "").strip()
