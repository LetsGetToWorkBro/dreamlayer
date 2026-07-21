"""dream_mode/dream_style.py — see the world as a painting (#12).

Dream Mode already paints reactive weather and synesthesia; this restyles the
CAMERA FRAME itself so what you look at comes back as a painting. Two honest
tiers, so it works out of the box and gets better if you add a model:

  PainterlyFilter — ALWAYS on, pure-numpy. An impressionist wash: soften, quantise
                    the palette to a few dream-tones, then lift the edges back in
                    as ink. Honestly procedural — a stylisation, not a neural net.
  DreamStylizer   — OPT-IN neural fast-style-transfer (ONNX), the real "Starry
                    Night over your street" when you drop a .onnx model in and
                    install onnxruntime (extra `dream-style`). Absent either, it
                    returns None and the caller uses the painterly wash instead.

Everything is on-device — a frame is never sent anywhere to be painted.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("dreamlayer.dream_style")


def _has(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _np_image(frame):
    """Coerce to an HWC uint8 RGB ndarray, or None (same discipline as
    object_lens.vision_extras — one source of truth would be nicer, but this
    module must stand alone under the optional dream extra)."""
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
                if arr.size and arr.max() <= 1.0 else arr.astype("uint8")
        if arr.ndim == 2:
            arr = np.stack([arr] * 3, axis=-1)
        if arr.ndim == 3 and arr.shape[2] == 4:
            arr = arr[:, :, :3]
        return arr if (arr.ndim == 3 and arr.shape[2] == 3 and arr.size) else None
    except Exception as exc:                           # noqa: BLE001
        log.debug("[dream_style] coerce failed: %s", exc)
        return None


class PainterlyFilter:
    """The always-available procedural wash. No model, no dependency beyond
    numpy — so Dream Mode can paint the world the moment it's turned on."""

    # honest label so nothing downstream mistakes this for a trained model
    kind = "procedural"

    def __init__(self, levels: int = 6):
        # palette depth: fewer levels = more poster-like. Clamped to a sane band.
        self.levels = max(3, min(12, int(levels)))

    def stylize(self, frame):
        """Return a painted uint8 RGB ndarray, or None if the frame can't be
        read. Never raises — Dream Mode must not fall over on a bad frame."""
        arr = _np_image(frame)
        if arr is None:
            return None
        try:
            import numpy as np
            a = arr.astype(np.float32)
            # 1) soften: a cheap 3x3 box blur (separable), edge-replicated so the
            #    border doesn't darken. This is the "wet brush".
            soft = _box_blur(a)
            # 2) quantise to `levels` dream-tones per channel — the poster wash.
            step = 255.0 / (self.levels - 1)
            quant = np.round(soft / step) * step
            # 3) lift the edges back in as ink so shapes stay legible.
            gray = a.mean(axis=2)
            gx = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
            gy = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :]))
            edge = np.clip((gx + gy) / 32.0, 0.0, 1.0)[:, :, None]
            out = quant * (1.0 - 0.6 * edge)
            return np.clip(out, 0, 255).astype(np.uint8)
        except Exception as exc:                       # noqa: BLE001
            log.error("[dream_style] painterly failed: %s", exc)
            return None


def _box_blur(a):
    """Separable 3x3 box blur on an HWC float array, edge-replicated."""
    import numpy as np

    def _blur1(x, axis):
        left = np.take(x, [0], axis=axis)
        right = np.take(x, [x.shape[axis] - 1], axis=axis)
        padded = np.concatenate([left, x, right], axis=axis)
        lo = np.take(padded, range(0, x.shape[axis]), axis=axis)
        mid = np.take(padded, range(1, x.shape[axis] + 1), axis=axis)
        hi = np.take(padded, range(2, x.shape[axis] + 2), axis=axis)
        return (lo + mid + hi) / 3.0

    return _blur1(_blur1(a, 0), 1)


class DreamStylizer:
    """Opt-in neural fast-style-transfer over an ONNX model asset. `ready` is
    True only when onnxruntime imports AND a model file exists — otherwise every
    call returns None and the caller uses the painterly wash. The model is any
    fast-neural-style net exported to ONNX (1x3xHxW float in → 1x3xHxW out); the
    user supplies it (nothing is bundled or fetched)."""

    dep = "onnxruntime"
    available = _has("onnxruntime")
    kind = "neural"

    def __init__(self, model_path: Optional[str] = None):
        self._sess = None
        self._in = None
        if not self.available or not model_path:
            return
        p = Path(model_path)
        if not p.exists():
            return
        try:
            import onnxruntime as ort  # type: ignore
            self._sess = ort.InferenceSession(
                str(p), providers=["CPUExecutionProvider"])
            self._in = self._sess.get_inputs()[0].name
        except Exception as exc:                       # noqa: BLE001
            log.info("[dream_style] onnx load failed: %s", exc)
            self._sess = None

    @property
    def ready(self) -> bool:
        return self._sess is not None

    def stylize(self, frame):
        """Painted uint8 RGB ndarray from the neural model, or None when the
        engine/model is absent or inference fails."""
        if self._sess is None:
            return None
        arr = _np_image(frame)
        if arr is None:
            return None
        try:
            import numpy as np
            x = arr.astype(np.float32).transpose(2, 0, 1)[None]   # 1x3xHxW
            out = self._sess.run(None, {self._in: x})[0]
            y = np.asarray(out)[0]                                # 3xHxW
            y = np.clip(y, 0, 255).transpose(1, 2, 0)
            return y.astype(np.uint8)
        except Exception as exc:                       # noqa: BLE001
            log.error("[dream_style] neural stylize failed: %s", exc)
            return None


def default_stylizer(model_path: Optional[str] = None):
    """The best painter available: the neural stylizer when a model + runtime are
    present, else the always-on painterly wash. Never None — Dream Mode always
    has a brush."""
    neural = DreamStylizer(model_path)
    return neural if neural.ready else PainterlyFilter()
