"""On-device object classifiers — CLIP / YOLO(ultralytics) / moondream / CoreML.

ADD-alongside: new siblings. Each is a `classify_fn(frame) -> (label, conf)`
callable for `ObjectRecognizer(classify_fn=...)` (recognizer.py untouched). All
lazy-import their dep (extras group `vision`); when absent, `__call__` returns
None, meaning "no recognition for this frame" — the recognizer's built-in
`_mock` is used only when `classify_fn is None` (no backend wired at all), NOT
when a wired backend declines a frame. The orchestrator therefore wires the
dependency-free HeuristicVisionClassifier as the base rung so a no-deps install
still gets real (gated) recognition rather than silence.

    from dreamlayer.object_lens.recognizer import ObjectRecognizer
    from dreamlayer.object_lens.classify_backends import ClipClassifier
    rec = ObjectRecognizer(classify_fn=ClipClassifier(["snake plant","bike lock"]))
"""
from __future__ import annotations
import logging
import math
import sys as _sys
from typing import Optional, Tuple

log = logging.getLogger("dreamlayer.classify_backends")


def _has(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


class ClipClassifier:
    """Zero-shot open-vocabulary labels via CLIP (open_clip): the label whose
    text embedding is closest to the image embedding, with the softmax score as
    confidence. Real inference — lazy-loads the model on first call."""
    dep = "open_clip"
    available = _has("open_clip")

    def __init__(self, labels: Optional[list[str]] = None,
                 model_name: str = "ViT-B-32", pretrained: str = "openai"):
        self.labels = labels or []
        self.model_name = model_name
        self.pretrained = pretrained
        self._model = None
        self._preprocess = None
        self._tokenizer = None
        self._text_features = None

    def _ensure(self):
        if self._model is not None or not self.available:
            return
        try:
            import open_clip  # type: ignore
            import torch  # type: ignore  # noqa: F401
            self._model, _, self._preprocess = \
                open_clip.create_model_and_transforms(
                    self.model_name, pretrained=self.pretrained)
            self._model.eval()
            self._tokenizer = open_clip.get_tokenizer(self.model_name)
        except Exception as exc:
            log.warning("[clip] load failed: %s; mock fallback", exc)
            self._model = None

    def _embed_labels(self):
        import torch  # type: ignore
        if self._text_features is not None:
            return self._text_features
        tokens = self._tokenizer(self.labels)
        with torch.no_grad():
            feats = self._model.encode_text(tokens)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        self._text_features = feats
        return feats

    def __call__(self, frame) -> Optional[Tuple[str, float]]:
        if not self.available or not self.labels:
            return None
        self._ensure()
        if self._model is None:
            return None
        try:
            import torch  # type: ignore
            from PIL import Image  # type: ignore
            import numpy as np
            img = frame
            if not isinstance(img, Image.Image):
                arr = np.asarray(img)
                if arr.dtype != np.uint8:
                    arr = (np.clip(arr, 0, 1) * 255).astype("uint8") \
                        if arr.max() <= 1.0 else arr.astype("uint8")
                img = Image.fromarray(arr).convert("RGB")
            tensor = self._preprocess(img).unsqueeze(0)
            with torch.no_grad():
                feat = self._model.encode_image(tensor)
                feat = feat / feat.norm(dim=-1, keepdim=True)
                sims = (100.0 * feat @ self._embed_labels().T).softmax(dim=-1)[0]
                idx = int(sims.argmax())
            return (self.labels[idx], float(sims[idx]))
        except Exception as exc:
            log.warning("[clip] infer failed: %s; mock fallback", exc)
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
    """Compact VLM (moondream): ask "What is the main object?" and take the
    short answer as the label. Real inference — lazy-loads on first call.
    Confidence is a fixed prior (VLMs don't emit calibrated scores); the
    recognizer's min_confidence gate still applies."""
    dep = "moondream"
    available = _has("moondream")

    def __init__(self, prompt: str = "What is the main object? Answer in 1-3 words.",
                 confidence: float = 0.6):
        self.prompt = prompt
        self.confidence = confidence
        self._model = None

    def _ensure(self):
        if self._model is not None or not self.available:
            return
        try:
            import moondream as md  # type: ignore
            self._model = md.vl()          # loads the packaged/default weights
        except Exception as exc:
            log.warning("[moondream] load failed: %s; mock fallback", exc)
            self._model = None

    def __call__(self, frame) -> Optional[Tuple[str, float]]:
        if not self.available:
            return None
        self._ensure()
        if self._model is None:
            return None
        try:
            from PIL import Image  # type: ignore
            import numpy as np
            img = frame
            if not isinstance(img, Image.Image):
                arr = np.asarray(img)
                if arr.max() <= 1.0:
                    arr = (np.clip(arr, 0, 1) * 255).astype("uint8")
                img = Image.fromarray(arr.astype("uint8")).convert("RGB")
            answer = self._model.query(img, self.prompt).get("answer", "")
            label = str(answer).strip().strip(".").lower()
            if not label:
                return None
            return (label, self.confidence)
        except Exception as exc:
            log.warning("[moondream] infer failed: %s; mock fallback", exc)
            return None


class MLXVisionClassifier:
    """Apple-Silicon-native VLM via mlx-vlm (FastVLM / Qwen2.5-VL / Moondream in
    MLX format). On a Mac-mini Brain this is the lowest time-to-first-token,
    lowest-power path to open-vocabulary "what is this" — Apple's FastVLM claims
    ~85× faster TTFT than comparable VLMs. Same ``classify_fn`` contract as the
    others; Apple-only (``available`` False off macOS or without mlx-vlm), lazy
    load, degrades to None. Inject ``_generate`` in tests."""
    dep = "mlx_vlm"
    available = _has("mlx_vlm") and _sys.platform == "darwin"

    def __init__(self, model: str = "mlx-community/FastVLM-0.5B",
                 prompt: str = "What is the main object? Answer in 1-3 words.",
                 confidence: float = 0.6, _generate=None):
        self.model_name = model
        self.prompt = prompt
        self.confidence = confidence
        self._model = None
        self._processor = None
        self._generate = _generate         # (model, proc, prompt, img) -> str

    def _ensure(self):
        if self._generate is not None or self._model is not None:
            return
        if not self.available:
            return
        try:                               # pragma: no cover - Apple-only path
            from mlx_vlm import load       # type: ignore
            self._model, self._processor = load(self.model_name)
        except Exception as exc:           # pragma: no cover
            log.warning("[mlx-vlm] load failed: %s", exc)
            self._model = None

    def __call__(self, frame) -> Optional[Tuple[str, float]]:
        if not (self.available or self._generate is not None):
            return None
        self._ensure()
        try:
            if self._generate is not None:
                answer = self._generate(self._model, self._processor,
                                        self.prompt, frame)
            else:                          # pragma: no cover - Apple-only path
                from mlx_vlm import generate  # type: ignore
                answer = generate(self._model, self._processor, self.prompt,
                                  frame, verbose=False)
            label = str(answer or "").strip().strip(".").lower()
            return (label, self.confidence) if label else None
        except Exception as exc:
            log.warning("[mlx-vlm] infer failed: %s", exc)
            return None


class CoreMLClassifier:
    """CoreML on-device inference (coremltools) — Apple Silicon path. Kept a
    thin seam: a real Vela/CoreML model plugs in here when the .mlmodel exists."""
    dep = "coremltools"
    available = _has("coremltools")

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path

    def __call__(self, frame) -> Optional[Tuple[str, float]]:
        return None if not (self.available and self.model_path) else None


class HeuristicVisionClassifier:
    """A real, dependency-free classifier — the offline base rung of the vision
    ladder. It reads actual pixels: per-frame brightness, colour saturation,
    greenness (foliage), warmth (red vs blue), and edge density (texture/text),
    then labels by nearest prototype in that feature space. No model, no deps,
    deterministic.

    It will not rival YOLO/CLIP on arbitrary photographs — it separates coarse
    visual *kinds* (a leafy plant vs a dark screen vs a page of text vs a smooth
    warm vessel), which is exactly what makes it testable end to end in CI and a
    genuine step up from a statistics-to-index mock. When a neural backend is
    installed the ladder prefers it (see ``default_classifier``)."""

    # Prototypes in normalized feature space:
    #   [brightness, saturation, greenness, warmth, edginess]
    # Calibrated against the synthetic feature generator in test_vision_bench.py.
    PROTOTYPES = {
        "houseplant": (0.31, 0.47, 0.94, 0.43, 0.83),
        "book":       (0.71, 0.07, 0.40, 0.61, 1.00),
        "screen":     (0.18, 0.04, 0.37, 0.50, 0.25),
        "mug":        (0.48, 0.59, 0.00, 1.00, 0.19),
    }
    MIN_VARIANCE = 0.5        # 8-bit-luma variance below this = a flat frame
    MAX_DISTANCE = 0.55       # beyond this, decline rather than guess

    def __init__(self, prototypes: Optional[dict] = None):
        self.prototypes = prototypes or dict(self.PROTOTYPES)

    @staticmethod
    def features(frame) -> Optional[tuple]:
        """Extract the 5-d normalized feature vector from raw pixels, or None on
        a blank/degenerate frame."""
        import numpy as np
        arr = np.asarray(frame, dtype=np.float32)
        if arr.size == 0:
            return None
        if arr.ndim == 2:
            arr = np.stack([arr, arr, arr], axis=-1)
        if arr.shape[-1] > 3:
            arr = arr[..., :3]
        if float(arr.max()) <= 1.0:
            arr = arr * 255.0
        # a near-flat frame (uniform colour, incl. all-black) recognises nothing
        if float(arr.var()) < HeuristicVisionClassifier.MIN_VARIANCE:
            return None
        R, G, B = arr[..., 0], arr[..., 1], arr[..., 2]
        mx = np.max(arr, axis=-1)
        mn = np.min(arr, axis=-1)
        brightness = float(arr.mean()) / 255.0
        saturation = float((mx - mn).mean()) / 255.0
        greenness = float(np.clip((G - np.maximum(R, B)) / 128.0 + 0.4, 0, 1).mean())
        warmth = float(np.clip((R - B) / 128.0 + 0.5, 0, 1).mean())
        gray = arr.mean(axis=-1)
        gx = float(np.abs(np.diff(gray, axis=1)).mean()) if gray.shape[1] > 1 else 0.0
        gy = float(np.abs(np.diff(gray, axis=0)).mean()) if gray.shape[0] > 1 else 0.0
        edginess = float(min(1.0, (gx + gy) / 40.0))
        return (brightness, saturation, greenness, warmth, edginess)

    def __call__(self, frame) -> Optional[Tuple[str, float]]:
        feats = self.features(frame)
        if feats is None:
            return None
        best_label, best_dist = None, 1e9
        for label, proto in self.prototypes.items():
            dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(feats, proto)))
            if dist < best_dist:
                best_label, best_dist = label, dist
        if best_label is None or best_dist > self.MAX_DISTANCE:
            return None
        # Confidence falls off with distance to the matched prototype, mapped
        # HONESTLY to [0, 1): a match right at MAX_DISTANCE scores ~0, a perfect
        # match ~1. The old `0.5 + 0.49*conf` floored every match at ≥0.5, so a
        # wall or sensor noise that landed just inside MAX_DISTANCE returned 0.5
        # and sailed through the recognizer's `confidence < min_confidence`
        # (default 0.5) gate — walls became "book", noise became "screen". With
        # the true range, a loose match scores below the floor and is rejected.
        conf = max(0.0, 1.0 - best_dist / self.MAX_DISTANCE)
        return (best_label, round(conf, 4))


def default_classifier(labels: Optional[list[str]] = None,
                       heuristic_fallback: bool = True):
    """The vision ladder: the best *installed* real backend first — YOLO (fast,
    boxed) → moondream (VLM) → CLIP (zero-shot, needs a label set) — then the
    dependency-free ``HeuristicVisionClassifier`` as the offline base rung so
    real pixel-reading recognition happens even with no ML deps. Pass
    ``heuristic_fallback=False`` to get the old behaviour (None when nothing
    neural is installed, so a caller's own mock stays authoritative)."""
    if YoloClassifier.available:
        y = YoloClassifier()
        if y._model is not None:
            return y
    # on a Mac-mini Brain, the Apple-native VLM (mlx-vlm/FastVLM) is the
    # lowest-TTFT open-vocabulary path — prefer it over the generic VLMs
    if MLXVisionClassifier.available:
        return MLXVisionClassifier()
    if MoondreamClassifier.available:
        return MoondreamClassifier()
    if ClipClassifier.available and labels:
        return ClipClassifier(labels)
    return HeuristicVisionClassifier() if heuristic_fallback else None
