"""object_lens/recognizer.py — general object recognition (pluggable).

The hard part of an Object Lens is a vision model that names *arbitrary*
objects, not just faces. That model runs on the Halo NPU in production; here
the recognizer is a clean seam:

    ObjectRecognizer(classify_fn=my_npu_model)   # real quantized classifier
    ObjectRecognizer()                           # deterministic mock

`classify_fn(frame) -> (label, confidence, attributes)`. When absent, a
deterministic mock maps frame statistics onto a small taxonomy so the rest
of the lens — providers, panels, HUD — is fully exercisable and testable
without a model.

Privacy boundary: if the recogniser names a *person*, the Object Lens
declines and returns nothing. People are Social Lens's consented domain;
the Object Lens is for things.
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np

from .schema import ObjectSighting

# a person is never an "object" here — defer to Social Lens
PERSON_LABELS = frozenset({"person", "face", "man", "woman", "child", "people"})

DEFAULT_TAXONOMY = [
    "laptop", "mug", "book", "houseplant", "phone", "keys",
    "bottle", "backpack", "car", "watch",
]

MIN_FRAME_VARIANCE = 1e-4       # a flat/black frame has nothing to recognise


class ObjectRecognizer:
    def __init__(self, classify_fn: Optional[Callable] = None,
                 min_confidence: float = 0.5,
                 taxonomy: Optional[list[str]] = None):
        self._classify = classify_fn
        self.min_confidence = min_confidence
        self.taxonomy = taxonomy or DEFAULT_TAXONOMY

    def recognize(self, frame) -> Optional[ObjectSighting]:
        """Name the object in a frame, or None (no frame / low confidence /
        a person)."""
        if frame is None:
            return None
        if self._classify is not None:
            out = self._classify(frame)
            if out is None:
                return None
            label, confidence, attrs = _unpack(out)
        else:
            got = self._mock(frame)
            if got is None:
                return None
            label, confidence, attrs = got

        if label.strip().lower() in PERSON_LABELS:
            return None                       # people belong to Social Lens
        if confidence < self.min_confidence:
            return None
        return ObjectSighting(label=label, confidence=confidence,
                              attributes=attrs or {})

    # -- deterministic mock ------------------------------------------------

    def _mock(self, frame):
        arr = np.asarray(frame, dtype=np.float32)
        if arr.size == 0 or float(arr.var()) < MIN_FRAME_VARIANCE:
            return None                       # a blank frame recognises nothing
        # a stable index into the taxonomy from the frame's coarse statistics
        mean = float(arr.mean())
        idx = int(round(mean * 97 + arr.size)) % len(self.taxonomy)
        label = self.taxonomy[idx]
        # confidence rises with contrast, capped
        conf = min(0.98, 0.55 + float(arr.std()) * 0.6)
        return label, conf, {}


def _unpack(out):
    if isinstance(out, ObjectSighting):
        return out.label, out.confidence, out.attributes
    if isinstance(out, dict):
        return out.get("label", "unknown"), float(out.get("confidence", 0.0)), \
            out.get("attributes", {})
    # tuple/list
    label = out[0]
    confidence = float(out[1]) if len(out) > 1 else 0.0
    attrs = out[2] if len(out) > 2 else {}
    return label, confidence, attrs
