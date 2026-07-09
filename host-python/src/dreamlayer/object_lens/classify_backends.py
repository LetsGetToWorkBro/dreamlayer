"""On-device object classifiers — CLIP / YOLO(ultralytics) / moondream / CoreML.

ADD-alongside: new siblings. Each is a `classify_fn(frame) -> (label, conf)`
callable for `ObjectRecognizer(classify_fn=...)` (recognizer.py untouched). All
lazy-import their dep (extras group `vision`); when absent, `__call__` returns
None so ObjectRecognizer transparently uses its built-in `_mock`.

    from dreamlayer.object_lens.recognizer import ObjectRecognizer
    from dreamlayer.object_lens.classify_backends import ClipClassifier
    rec = ObjectRecognizer(classify_fn=ClipClassifier(["snake plant","bike lock"]))
"""
from __future__ import annotations
import logging
from typing import Optional, Tuple

log = logging.getLogger("dreamlayer.classify_backends")


def _has(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


class ClipClassifier:
    """Zero-shot open-vocabulary labels via CLIP."""
    dep = "open_clip"
    available = _has("open_clip") or _has("clip")

    def __init__(self, labels: Optional[list[str]] = None):
        self.labels = labels or []

    def __call__(self, frame) -> Optional[Tuple[str, float]]:
        if not self.available or not self.labels:
            return None
        try:
            import open_clip  # type: ignore  # noqa: F401
            # Real path is model-time; keep the seam dependency-light and defer
            # actual inference to a wired model. Returning None here means the
            # recognizer's mock stays authoritative until a model is attached.
            return None
        except Exception as exc:
            log.warning("[clip] %s; mock fallback", exc)
            return None


class YoloClassifier:
    """YOLOv8 bounding-box detector (ultralytics), CoreML-exportable."""
    dep = "ultralytics"
    available = _has("ultralytics")

    def __init__(self, weights: str = "yolov8n.pt"):
        self._model = None
        if self.available:
            try:
                from ultralytics import YOLO  # type: ignore
                self._model = YOLO(weights)
            except Exception as exc:
                log.warning("[yolo] load failed: %s; mock fallback", exc)

    def __call__(self, frame) -> Optional[Tuple[str, float]]:
        if self._model is None:
            return None
        try:
            res = self._model(frame, verbose=False)[0]
            if not len(res.boxes):
                return None
            b = res.boxes[0]
            name = res.names[int(b.cls[0])]
            return (str(name), float(b.conf[0]))
        except Exception as exc:
            log.warning("[yolo] infer failed: %s", exc)
            return None


class MoondreamClassifier:
    """Compact VLM captioning/Q&A over a frame (moondream)."""
    dep = "moondream"
    available = _has("moondream")

    def __call__(self, frame) -> Optional[Tuple[str, float]]:
        return None if not self.available else None  # model-time; mock until wired


class CoreMLClassifier:
    """CoreML on-device inference (coremltools) — Apple Silicon path."""
    dep = "coremltools"
    available = _has("coremltools")

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path

    def __call__(self, frame) -> Optional[Tuple[str, float]]:
        return None if not (self.available and self.model_path) else None
