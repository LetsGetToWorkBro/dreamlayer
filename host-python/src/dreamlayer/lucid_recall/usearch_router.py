"""Dense embedding router (usearch) — replaces keyword routing with a nearest
exemplar lookup over intent prototypes.

ADD-alongside: new sibling to lucid_recall/router.py (LucidRecall keyword
classifier is untouched). Lazy-imports usearch (extras group `memory`); when
absent it falls back to an exact linear cosine over the same exemplars, so
routing decisions are identical — usearch only makes it faster/smaller.

    r = DenseRouter(embedder)
    r.add("recall", "what did I say about the lease")
    r.route("remind me about marcus")   -> "recall"
"""
from __future__ import annotations
import logging

from ..memory.embeddings import MockEmbeddingProvider, cosine

log = logging.getLogger("dreamlayer.usearch_router")

try:  # optional dep — extras group `memory`
    from usearch.index import Index  # type: ignore
    _HAS_USEARCH = True
except ImportError:
    _HAS_USEARCH = False


class DenseRouter:
    available = _HAS_USEARCH

    def __init__(self, embedder=None):
        self.embedder = embedder or MockEmbeddingProvider()
        self._labels: list[str] = []
        self._vecs: list[list[float]] = []
        self._index = None
        self._dim = None

    def add(self, label: str, exemplar: str) -> None:
        vec = self.embedder.embed(exemplar)
        self._labels.append(label)
        self._vecs.append(vec)
        self._index = None  # invalidate; rebuilt lazily

    def _build(self):
        if not _HAS_USEARCH or not self._vecs:
            return None
        try:
            import numpy as np
            self._dim = len(self._vecs[0])
            idx = Index(ndim=self._dim, metric="cos")
            idx.add(list(range(len(self._vecs))), np.array(self._vecs, dtype="float32"))
            return idx
        except Exception as exc:
            log.error("[usearch_router] build failed: %s; linear fallback", exc)
            return None

    def route(self, text: str, threshold: float = 0.0) -> str | None:
        if not self._vecs:
            return None
        qv = self.embedder.embed(text)
        if _HAS_USEARCH:
            if self._index is None:
                self._index = self._build()
            if self._index is not None:
                try:
                    import numpy as np
                    m = self._index.search(np.array(qv, dtype="float32"), 1)
                    if len(m):
                        key = int(m.keys[0]); sim = 1.0 - float(m.distances[0])
                        return self._labels[key] if sim >= threshold else None
                except Exception as exc:
                    log.error("[usearch_router] search failed: %s; linear", exc)
        # linear fallback
        best_i, best = -1, threshold - 1e-9
        for i, v in enumerate(self._vecs):
            s = cosine(qv, v)
            if s > best:
                best, best_i = s, i
        return self._labels[best_i] if best_i >= 0 else None
