"""object_lens/vision_extras.py — on-demand perception engines.

Five deliberate "look closer" powers, each a lazy adapter with a graceful
fallback (same discipline as classify_backends/ocr_backends): when the wheel is
absent the method returns a neutral value and the lens simply can't do that one
thing. All on-device — no frame ever leaves the Brain for these.

  read_math   — pix2tex: an equation on a board → LaTeX            (extra math-ocr)
  read_doc    — surya:   a form/receipt → text + layout blocks     (extra doc-ocr)
  nearest_m   — Depth Anything V2: how far is the thing in front   (extra depth)
  find        — YOLO-World: open-vocabulary "find my <anything>"   (extra vision)
  segment     — FastSAM: the mask of the thing you're pointing at  (extra vision)
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

log = logging.getLogger("dreamlayer.vision_extras")


def _has(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _np_image(frame):
    """Coerce to an HWC uint8 RGB ndarray, or None."""
    try:
        import numpy as np
        try:
            from PIL import Image  # type: ignore
            if isinstance(frame, Image.Image):
                frame = np.asarray(frame.convert("RGB"))
        except Exception:
            pass
        arr = np.asarray(frame)
        if arr.dtype != np.uint8:
            arr = (np.clip(arr, 0, 1) * 255).astype("uint8") \
                if arr.size and arr.max() <= 1.0 \
                else np.clip(arr, 0, 255).astype("uint8")   # clip: don't wrap negatives
        if arr.ndim == 2:
            arr = np.stack([arr] * 3, axis=-1)
        if arr.ndim == 3 and arr.shape[2] == 1:             # (H,W,1) → real RGB
            arr = np.repeat(arr, 3, axis=2)
        if arr.ndim == 3 and arr.shape[2] == 4:
            arr = arr[:, :, :3]
        return arr if (arr.ndim == 3 and arr.shape[2] == 3 and arr.size) else None
    except Exception as exc:                           # noqa: BLE001
        log.debug("[vision_extras] coerce failed: %s", exc)
        return None


# --- #11 LaTeX / math OCR (pix2tex) ------------------------------------------
class MathOcrReader:
    dep = "pix2tex"
    available = _has("pix2tex")

    def __init__(self):
        self._m = None
        if not self.available:
            return
        try:
            from pix2tex.cli import LatexOCR  # type: ignore
            self._m = LatexOCR()
        except Exception as exc:                       # noqa: BLE001
            log.info("[math_ocr] load failed: %s", exc)
            self._m = None

    @property
    def ready(self) -> bool:
        return self._m is not None

    def read_math(self, frame) -> str:
        """LaTeX for an equation in the frame, or "" when unavailable."""
        if self._m is None:
            return ""
        try:
            from PIL import Image  # type: ignore
            arr = _np_image(frame)
            if arr is None:
                return ""
            return str(self._m(Image.fromarray(arr))).strip()[:400]
        except Exception as exc:                       # noqa: BLE001
            log.error("[math_ocr] read failed: %s", exc)
            return ""


# --- #7 document layout (surya) ----------------------------------------------
class DocReader:
    dep = "surya"
    available = _has("surya")

    def __init__(self):
        self._ok = self.available
        self._rec = None            # cached RecognitionPredictor (loads a model once)
        self._det = None            # cached DetectionPredictor

    @property
    def ready(self) -> bool:
        return self._ok

    def _predictors(self):
        """Build & cache surya's predictors once (each loads a model). Returns
        (recognition, detection) or (None, None) on any import/load failure."""
        if self._rec is not None:
            return self._rec, self._det
        try:
            # surya-ocr >= 0.5 API: predictor objects, not the removed run_ocr /
            # surya.model.* tree (refute 2026-07-21 — the old imports were dead
            # against the pinned surya-ocr>=0.6, so read_doc always returned {}).
            from surya.recognition import RecognitionPredictor  # type: ignore
            from surya.detection import DetectionPredictor  # type: ignore
            self._rec = RecognitionPredictor()
            self._det = DetectionPredictor()
        except Exception as exc:                       # noqa: BLE001
            log.info("[doc] surya predictors unavailable: %s", exc)
            self._rec = self._det = None
        return self._rec, self._det

    def read_doc(self, frame) -> dict:
        """{'text': str, 'blocks': [str, ...]} with reading order, or {} when
        unavailable. surya loads its own models lazily on first call."""
        if not self._ok:
            return {}
        try:
            from PIL import Image  # type: ignore
            rec, det = self._predictors()
            if rec is None:
                return {}
            arr = _np_image(frame)
            if arr is None:
                return {}
            img = Image.fromarray(arr)
            # newer surya auto-detects language and dropped the langs arg; older
            # 0.6.x still accepts it — try the current signature, fall back once.
            try:
                preds = rec([img], det_predictor=det)
            except TypeError:
                preds = rec([img], [["en"]], det)
            lines = [ln.text for ln in (preds[0].text_lines if preds else [])]
            return {"text": " ".join(lines)[:2000], "blocks": lines[:100]}
        except Exception as exc:                       # noqa: BLE001
            log.error("[doc] read failed: %s", exc)
            return {}


# --- #4 monocular depth (Depth Anything V2 via transformers) -----------------
class DepthReader:
    dep = "transformers"
    available = _has("transformers")

    def __init__(self, model: str = "depth-anything/Depth-Anything-V2-Small-hf"):
        self._pipe = None
        if not self.available:
            return
        try:
            from transformers import pipeline  # type: ignore
            self._pipe = pipeline("depth-estimation", model=model)
        except Exception as exc:                       # noqa: BLE001
            log.info("[depth] load failed: %s", exc)
            self._pipe = None

    @property
    def ready(self) -> bool:
        return self._pipe is not None

    def nearest_relative(self, frame) -> Optional[float]:
        """A 0..1 'closeness' of the nearest thing in the CENTRE of view (1.0 =
        very close), or None. Relative depth only — honest: a single camera can't
        give metres without calibration, so this is a proximity cue, not a
        measurement."""
        if self._pipe is None:
            return None
        try:
            from PIL import Image  # type: ignore
            import numpy as np
            arr = _np_image(frame)
            if arr is None:
                return None
            out = self._pipe(Image.fromarray(arr))
            depth = np.asarray(out.get("depth") if isinstance(out, dict) else out,
                               dtype=np.float32)
            if depth.ndim != 2 or depth.size == 0:
                return None
            h, w = depth.shape
            cy, cx = h // 2, w // 2
            # a tiny map (any dim < 6) makes h//6 == 0 and the centre patch empty,
            # whose .mean() is nan — so widen the half-window to at least 1 px so
            # the patch is never empty (refute 2026-07-21: nan escaped the guards).
            hy, hx = max(1, h // 6), max(1, w // 6)
            patch = depth[max(0, cy - hy):cy + hy, max(0, cx - hx):cx + hx]
            if patch.size == 0:
                return None
            # transformers depth maps: larger value = nearer; normalise to 0..1
            lo, hi = float(depth.min()), float(depth.max())
            if hi <= lo:
                return None
            return round((float(patch.mean()) - lo) / (hi - lo), 3)
        except Exception as exc:                       # noqa: BLE001
            log.error("[depth] infer failed: %s", exc)
            return None


# --- #5 open-vocabulary find (YOLO-World, ships in ultralytics) ---------------
class YoloWorldFinder:
    dep = "ultralytics"
    available = _has("ultralytics")

    def __init__(self, model: str = "yolov8s-worldv2.pt"):
        self._model_name = model

    def find(self, frame, terms) -> Optional[List[Tuple[str, float]]]:
        """[(term, confidence), …] for the named things present, or None when
        unavailable / nothing found. `terms` is any list of nouns — 'my keys',
        'a fire extinguisher' — no fixed taxonomy."""
        # accept only a real sequence of nouns: a bare string would iterate into
        # single letters, and a non-iterable (an int) would raise before the try
        # (refute 2026-07-21). Anything else → no terms → None.
        if not isinstance(terms, (list, tuple, set, frozenset)):
            return None
        terms = [str(t).strip() for t in terms if str(t).strip()]
        if not self.available or not terms:
            return None
        arr = _np_image(frame)
        if arr is None:
            return None
        try:
            from ultralytics import YOLOWorld  # type: ignore
            model = YOLOWorld(self._model_name)
            model.set_classes(terms)
            res = model.predict(arr, verbose=False)
            out: List[Tuple[str, float]] = []
            for r in res:
                names = r.names
                for b in r.boxes:
                    out.append((str(names.get(int(b.cls[0]), "")),
                                float(b.conf[0])))
            return [(n, c) for n, c in out if n] or None
        except Exception as exc:                       # noqa: BLE001
            log.error("[yoloworld] find failed: %s", exc)
            return None


# --- #10 segment-anything (FastSAM, ships in ultralytics) --------------------
class FastSamSegmenter:
    dep = "ultralytics"
    available = _has("ultralytics")

    def __init__(self, model: str = "FastSAM-s.pt"):
        self._model_name = model

    def segment(self, frame) -> Optional[int]:
        """The number of distinct regions found (a lightweight 'how busy is this
        scene' + the masks are available to a caller that wants them). None when
        unavailable."""
        if not self.available:
            return None
        arr = _np_image(frame)
        if arr is None:
            return None
        try:
            from ultralytics import FastSAM  # type: ignore
            model = FastSAM(self._model_name)
            res = model.predict(arr, verbose=False)
            for r in res:
                if r.masks is not None:
                    return int(len(r.masks))
            return 0
        except Exception as exc:                       # noqa: BLE001
            log.error("[fastsam] segment failed: %s", exc)
            return None
