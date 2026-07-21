"""On-device OCR — read the text in a frame (prices, menus, signs, ISBNs).

ADD-alongside: new sibling of classify_backends.py. A `read_fn(frame) -> str`
callable that lazy-imports RapidOCR (extras group `vision`); when absent it
returns "" — so `attributes["text"]` stays an empty string the downstream
providers (Rosetta translation, the taste lens, currency/pokemon/vinyl) already
treat as "no text". Real inference — the ONNX models load on first call.

Privacy is baked in, not bolted on: every OCR line passes through
`person_guard` (a name badge / lanyard / ID is dropped) AND a contact-detail
scrub (an email or phone number is dropped) BEFORE the text is ever returned.
OCR is the first thing in the system that reads free text off the world, so it
is the one place that guarantee has to live — a stranger's name read off a
badge must never reach a panel, a translation, or a memory.
"""
from __future__ import annotations

import logging
import re
from typing import Callable, Optional

log = logging.getLogger("dreamlayer.ocr_backends")


def _has(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


# An email, or a phone-number-like run of 7-15 digits — the same contact-detail
# PII that vision_recognizer._clean_attrs strips from a VLM's "text" field, held
# here so an OCR read of a business card is scrubbed identically (a raw digit run
# of an ISBN length is kept; only phone-shaped separators trip it).
_PII_RE = re.compile(r"[\w.+-]+@[\w-]+\.\w{2,}|(?:\+?\d[\s().-]?){7,15}")


def _to_ocr_image(frame):
    """Coerce a PIL image / ndarray / anything array-like to an HWC uint8 RGB
    ndarray RapidOCR accepts. Returns None if it can't (caller → "")."""
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
        if arr.ndim == 2:                              # grayscale → RGB
            arr = np.stack([arr] * 3, axis=-1)
        if arr.ndim == 3 and arr.shape[2] == 4:        # RGBA → RGB
            arr = arr[:, :, :3]
        if arr.ndim != 3 or arr.shape[2] != 3 or arr.size == 0:
            return None
        return arr
    except Exception as exc:                           # noqa: BLE001
        log.debug("[ocr] frame coerce failed: %s", exc)
        return None


def _keep_line(line: str) -> bool:
    """A single OCR line survives only if it names no person and carries no
    contact detail. `defers_person(line)` (no frame) runs the deterministic
    name-shape + person-word denylist and, when present, the Presidio NER
    layer — all fail-safe, so a missing dep can only KEEP the line, never leak
    one it should have dropped."""
    line = line.strip()
    if not line:
        return False
    if _PII_RE.search(line):
        return False
    try:
        from . import person_guard
        if person_guard.defers_person(line):
            return False
    except Exception:                                  # noqa: BLE001 — fail toward the guard's own no-op
        pass
    return True


class RapidOcrReader:
    """A `read_fn(frame) -> str`. Real RapidOCR when the wheel is present;
    otherwise __call__ returns "" (the recognizer keeps its VLM guess / no text).
    Every returned line is person- and PII-scrubbed (see _keep_line)."""

    dep = "rapidocr_onnxruntime"
    available = _has("rapidocr_onnxruntime")

    def __init__(self):
        self._engine = None

    def _ensure(self):
        if self._engine is not None or not self.available:
            return
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore
            self._engine = RapidOCR()
        except Exception as exc:                       # noqa: BLE001
            log.warning("[ocr] RapidOCR load failed: %s; no-text fallback", exc)
            self._engine = None

    def __call__(self, frame) -> str:
        if not self.available:
            return ""
        img = _to_ocr_image(frame)
        if img is None:
            return ""
        self._ensure()
        if self._engine is None:
            return ""
        try:
            result, _elapse = self._engine(img)
        except Exception as exc:                       # noqa: BLE001
            log.warning("[ocr] inference failed: %s", exc)
            return ""
        # RapidOCR → [[box, text, score], ...] (or None when nothing is read)
        lines = []
        for row in (result or []):
            try:
                txt = str(row[1]).strip()
            except (IndexError, TypeError):
                continue
            if txt and _keep_line(txt):
                lines.append(txt)
        # cap the length the same way _clean_attrs caps a text field, so a wall
        # of text can't bloat a panel row or a memory summary
        return " ".join(lines)[:240].strip()

    # explicit alias for readers who prefer the verb
    read_text = __call__


def default_ocr() -> Optional[Callable[[object], str]]:
    """The best OCR reader available, or None when no OCR wheel is installed —
    paralleling default_classifier(). None means "leave the text channel to the
    VLM / empty", so the caller adds nothing rather than erroring."""
    reader = RapidOcrReader()
    return reader if reader.available else None
