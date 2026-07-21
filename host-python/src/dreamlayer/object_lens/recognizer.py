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

Privacy boundary: the recogniser panels a label only if it names something in
the object taxonomy (an allowlist). Any other label — an unknown object, a
person-ish word, an open-vocab description of a human — is declined and left to
the Social Lens. People are its consented domain; the Object Lens is for things.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

import numpy as np

from .schema import ObjectSighting

# A person is never an "object" here — defer to Social Lens. The recognizer must
# still accept open-vocabulary OBJECT labels the small taxonomy never lists
# ("almond milk", "espresso machine") because those flow on to the Label /
# Rosetta / AI providers — so the person defence is a denylist of person
# indicators, NOT an object allowlist (an allowlist would decline every novel
# object and break the open-vocab object path). The audit's real complaint was
# that the ORIGINAL set was only 6 words, so "boy"/"man in a suit" slipped
# through; the set below is widened to ~30 person indicators (audit 2026-07-15),
# which catches those via their person-indicator token while objects pass.
PERSON_TOKENS = frozenset({
    "person", "people", "persons", "face", "faces", "man", "men",
    "woman", "women", "child", "children", "kid", "kids", "boy", "boys",
    "girl", "girls", "toddler", "toddlers", "baby", "babies", "infant",
    "infants", "human", "humans", "lady", "ladies", "gentleman", "gentlemen",
    "guy", "guys", "adult", "adults", "teenager", "teenagers", "teen", "teens",
    "pedestrian", "pedestrians", "someone", "somebody", "everyone", "crowd",
    "portrait", "portraits", "selfie", "selfies",
    # relations / roles that name a present human
    "bride", "groom", "couple", "mother", "father", "mom", "dad", "mum",
    "parent", "parents", "son", "daughter", "husband", "wife", "spouse",
    "brother", "sister", "friend", "colleague", "coworker", "worker",
    # pronouns pointing at a present human (whole-token matches only)
    "he", "she", "him", "her", "his", "hers", "they", "them", "folks",
})
PERSON_LABELS = PERSON_TOKENS

# gendered/relational SUFFIXES for compound nouns where the person indicator is
# not a standalone token: "businessman", "policewoman", "schoolboy",
# "grandchild", "salesperson". Suffix (not substring) so an object like
# "mandarin"/"manual"/"command" is NOT mis-flagged. len>4 avoids the bare tokens
# already caught above. ("german" ending in "man" is the accepted rare cost.)
_PERSON_SUFFIX = ("man", "men", "woman", "women", "boy", "girl",
                  "person", "people", "child", "children")

_WORD_RE = re.compile(r"[a-z]+")

# A proper-name SHAPE the person-token denylist can't see: a name-shaped word —
# Title-Case (Maya, Chen, Taylor) OR ALL-CAPS (MAYA, CHEN). All-caps is the
# COMMON nametag/badge/lanyard rendering, and a Title-Case-ONLY rule let it walk
# straight onto the glass ("MAYA CHEN" matched neither token → identified in the
# default, no-Presidio config — refute 2026-07-18). Legit object labels are
# lowercase category nouns ("almond milk", "espresso machine"), so a run of these
# still signals a proper NAME, not an object; a rare all-caps object label
# ("DUCT TAPE") over-defers to the Social Lens, which is the privacy-safe
# direction. Mixed-case brands ("McDonald", "ThinkPad") are NOT name tokens, so a
# lone brand word does not trip the 2-token threshold.
_NAME_TOKEN_RE = re.compile(r"^[A-Z]([a-z]+|[A-Z]+)$")


def _looks_like_a_personal_name(label: str) -> bool:
    """True when the label has 2+ name-shaped words — a personal-name shape in
    Title-Case (``Maya Chen``) OR all-caps (``MAYA CHEN``, the nametag case).

    The person-token denylist catches CATEGORIES of humans ("a man", "the woman")
    but not IDENTITIES: a VLM that names a person — celebrity recognition, or a
    crafted nametag/caption steering the label — returns a proper name that no
    person-word matches, and it lands as the panel title on the glass (refute
    2026-07-18, a live break of the "never identify a stranger" contract). Object
    labels are lowercase common nouns, so this fires only on proper names; it
    over-defers a multi-word proper-noun brand/landmark to the Social-Lens path,
    which is the privacy-safe direction (brand/title still ride the attributes)."""
    caps = [t for t in (label or "").split() if _NAME_TOKEN_RE.match(t)]
    return len(caps) >= 2


DEFAULT_TAXONOMY = [
    "laptop", "mug", "book", "houseplant", "phone", "keys",
    "bottle", "backpack", "car", "watch",
]


def _names_a_person(label: str) -> bool:
    """True if any word in the label is a person-indicator.

    The recognizer must keep accepting open-vocabulary OBJECT labels the small
    taxonomy never lists ("almond milk", "espresso machine") — those flow to the
    Label / Rosetta / AI providers. So the person defence is a denylist of
    person-indicator tokens, not an object allowlist (an allowlist would decline
    every novel object). The token set was widened from the audit's 6 words to
    ~30 (man/woman/boy/girl/person/guy/lady/pedestrian/someone/…), so the
    open-vocab humans the audit flagged — "boy", "man in a suit", "the woman" —
    are now caught via their person-indicator token and deferred to the Social
    Lens, while objects pass. (Role-only words like "surgeon" carry no
    person-indicator and read as scene description, not identification.)
    """
    if _looks_like_a_personal_name(label):              # "Maya Chen" — a NAMED person
        return True
    toks = _WORD_RE.findall((label or "").lower())
    for t in toks:
        if t in PERSON_TOKENS:
            return True
        if len(t) > 4 and t.endswith(_PERSON_SUFFIX):   # businessman, policewoman, schoolboy
            return True
    return False

MIN_FRAME_VARIANCE = 1e-4       # a flat/black frame has nothing to recognise


class ObjectRecognizer:
    def __init__(self, classify_fn: Optional[Callable] = None,
                 min_confidence: float = 0.5,
                 taxonomy: Optional[list[str]] = None,
                 ocr_fn: Optional[Callable] = None,
                 barcode_fn: Optional[Callable] = None):
        self._classify = classify_fn
        self.min_confidence = min_confidence
        self.taxonomy = taxonomy or DEFAULT_TAXONOMY
        # OCR reader: an explicit read_fn(frame)->str, else the default RapidOCR
        # rung is resolved lazily on first look (None when no OCR wheel is
        # installed — the text channel simply stays the VLM's / empty).
        self._ocr_fn = ocr_fn
        self._ocr_ready = ocr_fn is not None
        # Barcode decoder: an explicit decode_fn(frame)->[(sym,value),...], else
        # the default zxing-cpp rung, resolved lazily (None when absent → no
        # barcode attribute, and the food lens stays quiet).
        self._barcode_fn = barcode_fn
        self._barcode_ready = barcode_fn is not None

    def _ocr(self) -> Optional[Callable]:
        if not self._ocr_ready:
            try:
                from .ocr_backends import default_ocr
                self._ocr_fn = default_ocr()
            except Exception:                          # noqa: BLE001 — OCR is never load-bearing
                self._ocr_fn = None
            self._ocr_ready = True
        return self._ocr_fn

    def _barcode(self) -> Optional[Callable]:
        if not self._barcode_ready:
            try:
                from .barcode_backends import default_barcode_decoder
                self._barcode_fn = default_barcode_decoder()
            except Exception:                          # noqa: BLE001 — never load-bearing
                self._barcode_fn = None
            self._barcode_ready = True
        return self._barcode_fn

    def recognize(self, frame) -> Optional[ObjectSighting]:
        """Name the object in a frame, or None (no frame / low confidence /
        a label that names no object in the taxonomy — e.g. a person)."""
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

        # Layered "never identify a stranger" defence: the deterministic
        # denylist + name-shape (_names_a_person), then the OPTIONAL Presidio
        # text-NER layer (catches a lone given name the shape rule misses), then
        # the OPTIONAL visual person DETECTOR (defers a human the VLM mislabelled
        # as an object). The two optional layers are fail-safe — a missing dep or
        # any error is a no-op, so they can only ADD a deferral (person_guard.py).
        from . import person_guard
        if person_guard.defers_person(label):     # denylist + name-shape + Presidio
            return None                       # a person → defer to Social Lens
        if confidence < self.min_confidence:
            return None
        if person_guard.frame_is_dominated_by_a_person(frame):
            return None                       # visual ground truth: a human subject
        attrs = self._read_text_into(frame, attrs)
        attrs = self._decode_barcode_into(frame, attrs)
        return ObjectSighting(label=label, confidence=confidence,
                              attributes=attrs or {})

    def _decode_barcode_into(self, frame, attrs) -> dict:
        """Attach attributes["barcode"] with the first numeric product code (or
        any decoded symbology) read off the frame, so the food lens can look it
        up. Pure on-device decode — no network, no identity. A no-op when no
        decoder wheel is installed or nothing scans."""
        decode = self._barcode()
        if decode is None:
            return attrs
        try:
            hits = decode(frame) or []
            from .barcode_backends import is_gtin
            # tolerate any (sym, value) or bare-value shape a decoder returns —
            # unpacking a malformed row must not break the look (the unpack has
            # to sit INSIDE the guard; audit 2026-07-21)
            values = [row[-1] if isinstance(row, (tuple, list)) else row
                      for row in hits]
            values = [str(v) for v in values if v]
            # a numeric GTIN (a food/product code) is what the lookup wants; fall
            # back to the first decoded value (e.g. a QR) so the attribute is honest
            code = next((v for v in values if is_gtin(v)),
                        values[0] if values else "")
        except Exception:                              # noqa: BLE001 — never breaks a look
            return attrs
        if not code:
            return attrs
        attrs = dict(attrs or {})
        attrs["barcode"] = code
        return attrs

    def _read_text_into(self, frame, attrs) -> dict:
        """Fill attributes["text"] with what OCR actually reads on the object —
        real text beats the VLM's guess, and it lights up the translation, taste,
        and price/ISBN providers that consume this field. A no-op when no OCR
        wheel is installed (reader is None) or nothing legible/allowed is read.
        The reader has already dropped any person-named or contact-detail line,
        so this can only add safe text."""
        reader = self._ocr()
        if reader is None:
            return attrs
        try:
            text = reader(frame)
        except Exception:                              # noqa: BLE001 — OCR never breaks a look
            return attrs
        if not text:
            return attrs
        # Boundary re-gate on the ASSEMBLED text — the reader filters line by
        # line, but a name badge renders "Maya" and "Chen" as SEPARATE regions
        # that each pass the per-line shape rule and only read as a person once
        # joined. Running person_guard on the whole string catches the reassembled
        # name (and defends any non-default ocr_fn), and it fails CLOSED: an
        # error here drops the text rather than surfacing a possible name
        # (audit 2026-07-21).
        try:
            from . import person_guard
            if person_guard.defers_person(text):
                return attrs
        except Exception:                              # noqa: BLE001 — can't confirm safe → drop
            return attrs
        attrs = dict(attrs or {})
        attrs["text"] = text                           # OCR is ground truth over a guess
        return attrs

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
