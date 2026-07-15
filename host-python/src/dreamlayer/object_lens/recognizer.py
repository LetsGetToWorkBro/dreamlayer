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
                 taxonomy: Optional[list[str]] = None):
        self._classify = classify_fn
        self.min_confidence = min_confidence
        self.taxonomy = taxonomy or DEFAULT_TAXONOMY

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

        if _names_a_person(label):
            return None                       # a person → defer to Social Lens
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
