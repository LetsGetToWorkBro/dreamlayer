"""supervision object tracking — stable IDs + world-anchored card positioning so
a ghost-layer card stays on its object across frames.

ADD-alongside: new sibling to ghost_layer.py (untouched). Lazy-imports
supervision (extras group `vision`); when absent it falls back to a nearest-
centroid tracker so IDs still persist frame-to-frame.
"""
from __future__ import annotations
import logging

import numpy as np

log = logging.getLogger("dreamlayer.track_supervision")

try:
    import supervision as sv  # type: ignore
    _HAS_SV = True
except ImportError:
    _HAS_SV = False

# Half-size of the synthetic box built around each input centroid to bridge
# the documented (cx, cy) contract onto sv.Detections. Centroids are in a
# normalized [0,1] space, so 0.02 is a small, fixed footprint; it is also the
# acceptance radius when mapping returned detections back to input positions.
_SYNTH_BOX_HALF = 0.02


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
        centroids = list(detections)
        if self._tracker is not None:
            try:
                if not centroids:
                    return []
                boxes = [
                    [cx - _SYNTH_BOX_HALF, cy - _SYNTH_BOX_HALF,
                     cx + _SYNTH_BOX_HALF, cy + _SYNTH_BOX_HALF]
                    for (cx, cy) in centroids
                ]
                sv_dets = sv.Detections(
                    xyxy=np.asarray(boxes, dtype=float),
                    confidence=np.ones(len(centroids), dtype=float),
                    class_id=np.zeros(len(centroids), dtype=int),
                )
                tracked = self._tracker.update_with_detections(sv_dets)
                raw = getattr(tracked, "tracker_id", None)
                if raw is None:
                    raw = []
                # update_with_detections returns a filtered, reordered set;
                # map each returned box centre back to the nearest input
                # centroid (within _SYNTH_BOX_HALF) so ids align to input order.
                result = [None] * len(centroids)
                xyxy = getattr(tracked, "xyxy", None)
                if xyxy is not None:
                    for row, tid in zip(xyxy, raw):
                        bx = (float(row[0]) + float(row[2])) / 2.0
                        by = (float(row[1]) + float(row[3])) / 2.0
                        best_i, best_d = None, _SYNTH_BOX_HALF
                        for i, (cx, cy) in enumerate(centroids):
                            if result[i] is not None:
                                continue
                            d = ((bx - cx) ** 2 + (by - cy) ** 2) ** 0.5
                            if d <= best_d:
                                best_i, best_d = i, d
                        if best_i is not None:
                            result[best_i] = int(tid)
                # one id per input, in input order — a partial mapping serves
                # the whole frame from the centroid fallback instead.
                if all(r is not None for r in result):
                    return [int(r) for r in result]
            except Exception as exc:
                log.warning("[track_supervision] update failed: %s; centroid", exc)
        return self._centroid_fallback(centroids)

    def _centroid_fallback(self, detections):
        """nearest-centroid fallback: IDs persist frame-to-frame by matching
        each centroid to the closest previous-track centroid within max_dist."""
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
