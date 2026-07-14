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

Recall is not just claimed: tests/test_ann_recall_at_scale.py builds a
realistically-sized set (1.5k clustered memories), computes the exact linear
top-k as ground truth, and enforces a recall@5 / top-1-agreement floor for the
HNSW path — so a silent recall regression at scale fails the build. (The small
parity tests in test_memory_lifecycle.py pin ANN == linear where exact and
approximate must coincide.)
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
    every search).

    Persistence is BATCHED on the hot path (P2-15): add() used to serialize
    the whole index file on every single ingest — at 50–150k memories that is
    tens of MB rewritten per captured moment. add() now marks the index dirty
    and saves once every `save_every` mutations; flush() forces a save and is
    called at the natural quiet points (the retention sweep, dream entry).
    Deletions stay IMMEDIATE: remove() saves on the spot, because a purged
    memory must never resurrect from a stale index file after a crash — purge
    honesty outranks write amortization, and purges are rare anyway. The
    honest crash window on the add side: at most save_every-1 recent vectors
    can be missing from the on-disk index after a hard kill; the rows are
    still in the DB, and the owner's boot check (ops_ingest._build_ann)
    rebuilds when the index disagrees with the DB."""

    available = _HAS_USEARCH

    def __init__(self, path: str | Path | None, dim: int, save_every: int = 64):
        self.path = Path(path) if path else None
        self.dim = int(dim)
        self.save_every = max(1, int(save_every))
        self._dirty = 0
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
            self._dirty += 1
            if self._dirty >= self.save_every:
                self._save()
            return True
        except Exception as exc:
            log.error("[ann_index] add failed: %s", exc)
            return False

    def remove(self, memory_id: int, save: bool = True) -> None:
        # immediate save by default: a single "forget that" must not resurrect
        # from a stale index file after a crash (see class docstring). A BULK
        # caller (RetentionSweep) passes save=False and flushes ONCE at the end,
        # so a 1000-row sweep rewrites the index file once, not 1000 times; a
        # crash mid-sweep is harmless because retrieval skips any indexed id
        # whose DB row is already gone.
        if self._index is None:
            return
        try:
            self._index.remove(int(memory_id))
            if save:
                self._save()
            else:
                self._dirty += 1
        except Exception:
            pass

    def flush(self) -> None:
        """Persist any batched adds now. Cheap no-op when nothing is dirty."""
        if self._dirty:
            self._save()

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
        if self._index is None:
            return
        if self.path is None:
            self._dirty = 0            # in-memory: nothing to persist
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._index.save(str(self.path))
            # Clear the dirty counter ONLY after a durable save. Zeroing it
            # first (the old order) meant a save that threw — disk full —
            # marked the batch clean, so flush() became a no-op and up to
            # save_every unsaved adds could vanish on the next crash, breaking
            # the bound the class docstring promises.
            self._dirty = 0
        except Exception as exc:
            log.error("[ann_index] save failed: %s; batch stays dirty", exc)
