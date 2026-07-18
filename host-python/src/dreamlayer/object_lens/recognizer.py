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

# A proper-name SHAPE the person-token denylist can't see: a Title-Case
# alphabetic word (Maya, Chen, Taylor). Legit object labels are lowercase
# category nouns ("almond milk", "espresso machine"), so a run of these signals a
# proper NAME, not an object.
_NAME_TOKEN_RE = re.compile(r"^[A-Z][a-z]+$")


def _looks_like_a_personal_name(label: str) -> bool:
    """True when the label has 2+ Title-Case alphabetic words — a personal-name
    shape (``Maya Chen``, ``Taylor Swift``, ``John Smith``).

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

        # Layered "never identify a stranger" defence: the deterministic
        # denylist + name-shape (_names_a_person), then the OPTIONAL Presidio
        # text-NER layer (catches a lone given name the shape rule misses), then
        # the OPTIONAL visual person DETECTOR (defers a human the VLM mislabelled
        # as an object). The two optional layers are fail-safe — a missing dep or
        # any error is a no-op, so they can only ADD a deferral (person_guard.py).
        from . import person_guard
        if _names_a_person(label) or person_guard.label_is_a_person(label):
            return None                       # a person → defer to Social Lens
        if confidence < self.min_confidence:
            return None
        if person_guard.frame_is_dominated_by_a_person(frame):
            return None                       # visual ground truth: a human subject
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
