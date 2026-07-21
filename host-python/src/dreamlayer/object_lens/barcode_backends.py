"""On-device barcode / QR decoding — read the code off a product in view.

ADD-alongside: new sibling of classify_backends.py / ocr_backends.py. A
`decode_fn(frame) -> list[(symbology, value)] | None` that lazy-imports zxing-cpp
(extras group `vision`); when absent it returns None ("no decoder wired"), so a
look carries no `barcode` attribute and the food lens simply stays quiet.

Decoding is pure on-device pixel work — no network, no identity — so nothing
here touches person_guard or the egress gate. The *lookup* of a decoded code
(Open Food Facts) is a separate, posture-gated step (barcode_lens.py).
"""
from __future__ import annotations

import logging
import re
from typing import Callable, List, Optional, Tuple

log = logging.getLogger("dreamlayer.barcode_backends")

# A product barcode is 8-14 digits (EAN-8, UPC-A/12, EAN-13, GTIN-14). We keep
# every decoded symbology's value, but this validates the numeric ones a food
# lookup can actually use.
_GTIN_RE = re.compile(r"^\d{8,14}$")


def _has(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _to_image(frame):
    """Coerce to an HWC uint8 ndarray zxing-cpp accepts (it also takes PIL, but
    normalizing once keeps the backends uniform). None if it can't."""
    try:
        import numpy as np
        try:
            from PIL import Image  # type: ignore
        except Exception:
            Image = None
        if Image is not None and isinstance(frame, Image.Image):
            frame = np.asarray(frame.convert("RGB"))
        arr = np.asarray(frame)
        if arr.dtype != np.uint8:
            arr = (np.clip(arr, 0, 1) * 255).astype("uint8") \
                if arr.size and arr.max() <= 1.0 else arr.astype("uint8")
        if arr.ndim == 2:
            arr = np.stack([arr] * 3, axis=-1)
        if arr.ndim == 3 and arr.shape[2] == 4:
            arr = arr[:, :, :3]
        if arr.ndim != 3 or arr.shape[2] != 3 or arr.size == 0:
            return None
        return arr
    except Exception as exc:                           # noqa: BLE001
        log.debug("[barcode] frame coerce failed: %s", exc)
        return None


def is_gtin(value: str) -> bool:
    """A numeric product code (EAN/UPC/GTIN) an Open Food Facts lookup accepts."""
    return bool(_GTIN_RE.match((value or "").strip()))


class ZxingBarcodeDecoder:
    """A `decode_fn(frame) -> [(symbology, value), ...] | None`. Real zxing-cpp
    when the wheel is present; otherwise __call__ returns None."""

    dep = "zxingcpp"
    available = _has("zxingcpp")

    def __call__(self, frame) -> Optional[List[Tuple[str, str]]]:
        if not self.available:
            return None
        img = _to_image(frame)
        if img is None:
            return None
        try:
            import zxingcpp  # type: ignore
            results = zxingcpp.read_barcodes(img)
        except Exception as exc:                       # noqa: BLE001
            log.warning("[barcode] decode failed: %s", exc)
            return None
        out: List[Tuple[str, str]] = []
        for r in (results or []):
            try:
                text = str(getattr(r, "text", "") or "").strip()
                if not text:
                    continue
                fmt = str(getattr(r, "format", "") or "barcode")
            except Exception:                          # noqa: BLE001
                continue
            out.append((fmt, text))
        return out or None


def default_barcode_decoder() -> Optional[Callable[[object], Optional[list]]]:
    """The best barcode decoder available, or None when no decoder wheel is
    installed — paralleling default_classifier()/default_ocr()."""
    dec = ZxingBarcodeDecoder()
    return dec if dec.available else None
