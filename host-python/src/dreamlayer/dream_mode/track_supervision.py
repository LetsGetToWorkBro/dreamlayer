"""supervision object tracking — stable IDs + world-anchored card positioning so
a ghost-layer card stays on its object across frames.

ADD-alongside: new sibling to ghost_layer.py (untouched). Lazy-imports
supervision (extras group `vision`); when absent it falls back to a nearest-
centroid tracker so IDs still persist frame-to-frame.
"""
from __future__ import annotations
import logging

log = logging.getLogger("dreamlayer.track_supervision")

try:
    import supervision as sv  # type: ignore
    _HAS_SV = True
except ImportError:
    _HAS_SV = False


class SupervisionTracker:
    available = _HAS_SV

    def __init__(self, max_dist: float = 0.15):
        self.max_dist = max_dist
        self._tracker = None
        self._prev: dict[int, tuple] = {}
        self._next_id = 1
        if _HAS_SV:
            try:
                self._tracker = sv.ByteTrack()
            except Exception as exc:
                log.warning("[track_supervision] init failed: %s; centroid fallback", exc)
                self._tracker = None

    def update(self, detections):
        """`detections` = list of (cx, cy) centroids in [0,1]. Returns list of
        stable ids aligned to the input order."""
        if self._tracker is not None:
            try:
                tracked = self._tracker.update_with_detections(detections)
                return list(getattr(tracked, "tracker_id", []) or [])
            except Exception as exc:
                log.warning("[track_supervision] update failed: %s; centroid", exc)
        # nearest-centroid fallback
        ids, used = [], set()
        new_prev = {}
        for (cx, cy) in detections:
            best, best_d = None, self.max_dist
            for tid, (px, py) in self._prev.items():
                if tid in used:
                    continue
                d = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
                if d < best_d:
                    best, best_d = tid, d
            if best is None:
                best = self._next_id
                self._next_id += 1
            used.add(best)
            new_prev[best] = (cx, cy)
            ids.append(best)
        self._prev = new_prev
        return ids
