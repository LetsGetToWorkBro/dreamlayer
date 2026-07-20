"""object_lens/vision_recognizer.py — a VLM-backed structured recognizer.

The device recognizer (recognizer.py) names an object with a small
`(label, confidence)` classifier — enough for "that's a mug", but blind to the
*fields* the plugin providers actually consume: the CurrencyProvider needs an
`amount` + `currency`, a book connector needs a `title`/`isbn`. On the Halo NPU
that structured read comes off the on-device vision model; here — pre-hardware,
on the Mac-mini Brain — we reuse the Brain's OWN vision model to do the same job.

`VisionSightingRecognizer` is a drop-in ``classify_fn`` for
:class:`ObjectRecognizer`: it hands the photo to a ``describe_fn(prompt,
image_b64) -> str`` (the Brain's vision backend), asks for one compact JSON
object, and returns ``(label, confidence, attributes)``. When there is no vision
tier — or the model declines / returns junk — it falls back to the
dependency-free heuristic ladder (``default_classifier``), so a look always gets
a real, gated answer rather than silence.

Layering: this module is pure ``object_lens`` (no ai_brain import). The Brain
wiring — building ``describe_fn`` from its backend — lives in
``ai_brain/server/world_lens.py``.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
from typing import Callable, Optional

log = logging.getLogger("dreamlayer.vision_recognizer")

# One tight instruction: name the object AND pull the few fields a panel can act
# on. "person" is called out so a human subject is labelled as such and the
# recognizer's person-defence hands it to the Social Lens (objects only here).
EXTRACT_PROMPT = (
    "Look at this image for an object assistant. Reply with ONE JSON object and "
    "nothing else:\n"
    '{"label": "<1-3 word lowercase name of the single main object; if a human '
    'being is the main subject use exactly \\"person\\" and NEVER a personal '
    'name, even for someone famous>", "confidence": <0-1>, "attributes": {'
    '"amount": <number on a visible price/banknote, else omit>, '
    '"currency": "<ISO code like EUR/JPY/USD if a price is shown, else omit>", '
    '"title": "<book or product title if clearly legible, else omit>", '
    '"isbn": "<ISBN digits if visible, else omit>", '
    '"brand": "<brand if legible, else omit>", '
    '"text": "<short salient text on the object, else omit>"}}\n'
    "Only include an attribute when you actually see it. Do not guess a price or "
    "a title that is not there."
)

_CODE_FENCE = re.compile(r"```(?:json)?|```", re.IGNORECASE)
_CURRENCY_RE = re.compile(r"^[A-Za-z]{2,4}$")
# An email address, or a phone-number-like run of 7-15 digits with common
# separators — contact-detail PII that must never ride onto a panel via an
# object's free-text attribute (refute 2026-07-18).
_PII_RE = re.compile(r"[\w.+-]+@[\w-]+\.\w{2,}|(?:\+?\d[\s().-]?){7,15}")


def frame_to_b64(frame) -> Optional[str]:
    """A frame → JPEG base64 (what a vision model wants). Passes a str straight
    through (already base64); encodes an ndarray/PIL image via Pillow; returns
    None when it can't (no Pillow, a bad array) so the caller falls back."""
    if frame is None:
        return None
    if isinstance(frame, str):
        return frame
    try:
        from PIL import Image  # type: ignore
        import numpy as np
        img = frame
        if not isinstance(img, Image.Image):
            arr = np.asarray(img)
            if arr.dtype != np.uint8:
                arr = ((np.clip(arr, 0, 1) * 255).astype("uint8")
                       if float(arr.max() if arr.size else 0) <= 1.0
                       else arr.astype("uint8"))
            img = Image.fromarray(arr).convert("RGB")
        else:
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:            # no Pillow / bad frame → let the caller fall back
        log.debug("[vision_recognizer] frame encode failed: %s", exc)
        return None


# A real (downscaled) phone photo is a few megapixels; anything past this is a
# decompression bomb — a tiny solid-colour JPEG that decodes to hundreds of MB —
# or a mistake. The 16 MiB body cap bounds the COMPRESSED bytes, not the decoded
# pixels, so this is the pixel-layer bound (refute 2026-07-18: a 379 KiB payload
# decoded to a 300 MB ndarray; 64 concurrent looks → OOM).
MAX_FRAME_PIXELS = 50 * 1024 * 1024        # 50 MP — above any real photo, below a bomb


def b64_to_frame(image_b64):
    """Decode a base64 image into an ndarray for the pixel/heuristic path.

    Returns the base64 string unchanged when Pillow is absent or the bytes don't
    decode — the VLM path reads that string directly, and the heuristic fallback
    simply declines rather than crashing. None for empty input OR an image whose
    pixel count exceeds MAX_FRAME_PIXELS (a decompression bomb — declined before
    the pixels are ever materialised, so the look returns blind instead of OOMing)."""
    if not image_b64:
        return None
    try:
        from PIL import Image  # type: ignore
        import numpy as np
        raw = base64.b64decode(image_b64)
        img = Image.open(io.BytesIO(raw))          # lazy — no pixels materialised yet
        w, h = img.size
        if w * h > MAX_FRAME_PIXELS:
            log.warning("[vision_recognizer] frame %dx%d exceeds %d MP — refused "
                        "(decompression bomb guard)", w, h,
                        MAX_FRAME_PIXELS // (1024 * 1024))
            return None                            # never call .convert()/asarray on it
        return np.asarray(img.convert("RGB"))
    except Exception as exc:
        log.debug("[vision_recognizer] b64 decode failed: %s", exc)
        return image_b64


def _clean_attrs(raw) -> dict:
    """Keep only the fields a provider can trust, coerced to safe types. An
    untrusted model reply could carry inf/NaN/huge numbers or wrong types; the
    CurrencyProvider does ``float(amount)`` and prints ``currency`` on the glass,
    so bound them here (mirrors the openlibrary rating-clamp posture)."""
    out: dict = {}
    if not isinstance(raw, dict):
        return out
    amt = raw.get("amount")
    if amt is not None:
        try:
            f = float(amt)
            import math
            if math.isfinite(f):
                out["amount"] = round(f, 2)
        except (TypeError, ValueError):
            pass
    cur = raw.get("currency")
    if isinstance(cur, str) and _CURRENCY_RE.match(cur.strip()):
        out["currency"] = cur.strip().upper()
    for key in ("title", "isbn", "brand", "text"):
        v = raw.get(key)
        if isinstance(v, str) and v.strip():
            val = v.strip()[:120]
            # Drop free-text carrying obvious PII (an email or a phone-number-like
            # digit run) — an object's brand/title/salient-text is never a
            # contact detail, so a nametag/lanyard caption reading "Maya Chen —
            # 555-123-4567" must not ride onto the panel via an object attribute
            # (refute 2026-07-18). ISBN is legitimately a digit run, so it skips
            # the phone check.
            if key != "isbn" and _PII_RE.search(val):
                continue
            out[key] = val
    return out


def parse_sighting_json(text: str) -> Optional[tuple]:
    """Pull ``(label, confidence, attributes)`` from a model reply, or None.

    Tolerant: strips code fences and grabs the first ``{...}`` block, so a model
    that wraps the JSON in prose still parses. An empty/whitespace label is a
    non-answer (None)."""
    if not text:
        return None
    s = _CODE_FENCE.sub("", text).strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(s[start:end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    label = str(data.get("label", "") or "").strip()
    if not label:
        return None
    raw_conf = data.get("confidence")
    conf = 0.75                         # VLMs rarely self-score; a reasonable prior
    if isinstance(raw_conf, (int, float, str)):
        try:
            conf = float(raw_conf)
        except ValueError:
            pass
    conf = max(0.0, min(1.0, conf))
    return (label, conf, _clean_attrs(data.get("attributes")))


class VisionSightingRecognizer:
    """A ``classify_fn`` that reads structured fields off a photo via a vision
    model, falling back to a plain classifier when there is no model or it
    declines. Wire it into ``ObjectRecognizer(classify_fn=...)``.

    ``describe_fn(prompt, image_b64) -> str`` is the Brain's vision seam.
    ``fallback`` is another ``classify_fn`` (default: the dependency-free
    heuristic ladder) used when the model path yields nothing. ``available`` is an
    optional predicate: when it returns False the VLM path is skipped ENTIRELY —
    no frame encode, no describe call — and the look goes straight to the fallback.
    On the common default install (``_backend is None``) ``describe_fn`` is a bound
    method that always returns ``""`` after re-encoding the frame to base64, so
    every look paid for a JPEG encode + a no-op call it could never use (refute
    2026-07-20). Wiring ``available`` to the backend's presence removes that cost."""

    def __init__(self, describe_fn: Callable[[str, Optional[str]], str],
                 fallback: Optional[Callable] = None,
                 prompt: str = EXTRACT_PROMPT,
                 available: Optional[Callable[[], bool]] = None):
        self._describe = describe_fn
        self._prompt = prompt
        self._available = available
        if fallback is None:
            from .classify_backends import default_classifier
            fallback = default_classifier()
        self._fallback = fallback

    def __call__(self, frame):
        if self._available is None or self._available():
            b64 = frame_to_b64(frame)
            if b64 and self._describe is not None:
                try:
                    reply = self._describe(self._prompt, b64)
                except Exception as exc:
                    log.warning("[vision_recognizer] describe failed: %s", exc)
                    reply = ""
                parsed = parse_sighting_json(reply)
                if parsed is not None:
                    return parsed
        # no model / declined / unparseable → the heuristic ladder (real pixels)
        return self._fallback(frame) if self._fallback else None
