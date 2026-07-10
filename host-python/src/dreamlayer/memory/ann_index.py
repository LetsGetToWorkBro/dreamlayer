"""memory/ann_index.py — a PERSISTENT approximate-nearest-neighbor index.

The default recall path was a linear cosine scan over every stored row —
fine at hundreds of memories, 100ms+ at 10k, seconds at 100k. A year of
heavy wear is 50–150k structured memories, so the default path broke
inside year one. This index keeps recall glance-speed at scale.

ADD-alongside, seam-with-fallback (the house pattern):
- lazy-imports usearch (extras group `memory`); `available` says whether
  the real HNSW index is live. Without it every method is a cheap no-op
  and Retriever's exact linear scan remains the behavior — nothing breaks.
- the index lives in ONE file beside the vault/db and is updated on every
  ingest, not rebuilt per query (the old sqlite-vec adapter rebuilt an
  ephemeral in-memory table per query — O(n) with extra steps).
- vectors from different embedding spaces must never share an index:
  the stored `signature` (memory.embeddings.embedder_signature) is checked
  by the owner and a mismatch triggers rebuild() from the DB rows.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("dreamlayer.ann_index")

try:  # optional dep — extras group `memory`
    from usearch.index import Index as _UsearchIndex  # type: ignore
    _HAS_USEARCH = True
except ImportError:
    _HAS_USEARCH = False


class PersistentAnnIndex:
    """HNSW index over memory embeddings, persisted to `path`.

    Keys are memory row ids. `dim` is fixed at construction; add() refuses
    a vector of any other length (a dimension mix would silently poison
    every search)."""

    available = _HAS_USEARCH

    def __init__(self, path: str | Path | None, dim: int):
        self.path = Path(path) if path else None
        self.dim = int(dim)
        self._index = None
        if not _HAS_USEARCH or dim <= 0:
            return
        try:
            self._index = _UsearchIndex(ndim=self.dim, metric="cos")
            if self.path and self.path.exists():
                self._index.load(str(self.path))
        except Exception as exc:
            log.error("[ann_index] init failed: %s; linear scan fallback", exc)
            self._index = None

    # ------------------------------------------------------------------

    @property
    def live(self) -> bool:
        return self._index is not None

    def __len__(self) -> int:
        return len(self._index) if self._index is not None else 0

    def add(self, memory_id: int, vector) -> bool:
        if self._index is None:
            return False
        vec = list(vector or ())
        if len(vec) != self.dim:
            log.warning("[ann_index] refused %d-d vector (index is %d-d)",
                        len(vec), self.dim)
            return False
        try:
            import numpy as np
            key = int(memory_id)
            if self._index.contains(key):
                self._index.remove(key)
            self._index.add(key, np.asarray(vec, dtype=np.float32))
            self._save()
            return True
        except Exception as exc:
            log.error("[ann_index] add failed: %s", exc)
            return False

    def remove(self, memory_id: int) -> None:
        if self._index is None:
            return
        try:
            self._index.remove(int(memory_id))
            self._save()
        except Exception:
            pass

    def search(self, vector, k: int = 10) -> list[tuple[int, float]]:
        """Return [(memory_id, cosine_similarity)] best-first, or [] when
        the index isn't live/populated (callers fall back to linear)."""
        if self._index is None or len(self._index) == 0:
            return []
        try:
            import numpy as np
            hits = self._index.search(
                np.asarray(list(vector), dtype=np.float32), k)
            return [(int(key), 1.0 - float(dist))
                    for key, dist in zip(hits.keys, hits.distances)]
        except Exception as exc:
            log.error("[ann_index] search failed: %s; linear fallback", exc)
            return []

    def rebuild(self, db) -> int:
        """Re-index every embedded row in `db` (embedder change, corruption).
        Returns the number of vectors indexed."""
        if self._index is None:
            return 0
        from .embeddings import unpack_embedding
        try:
            self._index.reset()
        except Exception:
            pass
        n = 0
        for m in db.memories():
            vec = unpack_embedding(m.get("embedding"))
            if vec and len(vec) == self.dim:
                try:
                    import numpy as np
                    self._index.add(int(m["id"]),
                                    np.asarray(vec, dtype=np.float32))
                    n += 1
                except Exception:
                    continue
        self._save()
        return n

    # ------------------------------------------------------------------

    def _save(self) -> None:
        if self._index is None or self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._index.save(str(self.path))
        except Exception as exc:
            log.error("[ann_index] save failed: %s", exc)
