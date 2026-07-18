"""orchestrator/voice_guard.py — "never voiceprint a stranger".

person_guard refuses to IDENTIFY a stranger's face; this is its voice twin. An
ECAPA speaker embedding is a biometric — a voiceprint that re-identifies a person
across sessions and rooms. The capture pipeline computes one for every speech
segment to resolve who is speaking, but a segment is just as often a bystander,
a passer-by, a barista — someone who never consented to being biometrically
enrolled. Retaining their voiceprint is exactly the "identify a stranger" harm
person_guard exists to prevent, one sense over.

The rule mirrors person_guard.defers_person: a transient embedding MAY be
computed to answer "are you one of my enrolled people?", but it is RETAINED only
for an enrolled speaker. A non-enrolled voice — the resolver returned no identity,
or only a diarization placeholder ("them" / "unknown" / "speaker0") — has its
voiceprint discarded immediately and is never stored, enrolled, or routed onward.
And when identification is impossible in the first place (no resolver, or no
enrolled population to match against), no voiceprint is computed at all: banking a
biometric that can never be used is pure collection of strangers' data.

Centralised on purpose (the same lesson as person_guard's refute): every surface
that turns audio into a stored voiceprint routes the keep/discard decision through
this one primitive, so a new surface cannot silently start banking strangers'
biometrics. Fail-safe throughout — when in doubt, DON'T retain.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

# The wearer themself — always an enrolled, consenting identity (their own device,
# their own voice). Case-insensitive.
SELF_LABELS = frozenset({"me", "self", "wearer", "owner", "i"})

# Diarization placeholders and non-identities: a resolver emits these when it
# could NOT put a name to the voice. They denote "someone", never "a specific
# enrolled someone", so they are strangers for retention purposes.
PLACEHOLDER_LABELS = frozenset({
    "", "them", "they", "other", "others", "unknown", "unk", "stranger",
    "guest", "someone", "person", "speaker", "voice", "n/a", "none", "?",
})

# "speaker0", "spk_3", "voice-2", "s1" … — enumerated diarization slots, not names.
_PLACEHOLDER_RE = re.compile(r"^(?:speaker|spk|voice|s)[\s_\-]?\d+$", re.IGNORECASE)


def _norm(label: Optional[str]) -> str:
    return (label or "").strip().lower()


def is_self(label: Optional[str]) -> bool:
    """True when the label denotes the wearer — their own voiceprint is theirs to
    keep."""
    return _norm(label) in SELF_LABELS


def is_enrolled_label(label: Optional[str], enrolled: Optional[Iterable[str]] = None) -> bool:
    """True when *label* denotes an ENROLLED speaker — the wearer, or an identity
    the resolver could actually name.

    A resolver returns a real name ONLY when the voice matched a registered
    voiceprint above threshold; an unmatched voice comes back empty or as a
    diarization placeholder. So a non-empty, non-placeholder label already means
    "matched an enrolled speaker". When an explicit *enrolled* set is supplied,
    the label must additionally be a member of it (self always passes) — a
    stricter check for callers that hold the registry. Fail-safe: anything not
    positively enrolled is treated as a stranger.
    """
    norm = _norm(label)
    if norm in SELF_LABELS:
        return True
    if not norm or norm in PLACEHOLDER_LABELS or _PLACEHOLDER_RE.match(norm):
        return False
    if enrolled is not None:
        return norm in {_norm(e) for e in enrolled}
    return True


def defers_speaker(label: Optional[str], enrolled: Optional[Iterable[str]] = None) -> bool:
    """The voice twin of person_guard.defers_person: True when this speaker is a
    stranger whose biometric must NOT be retained/identified."""
    return not is_enrolled_label(label, enrolled)


def retain_voiceprint(label: Optional[str], enrolled: Optional[Iterable[str]] = None) -> bool:
    """The single keep/discard decision every voiceprint-storing surface applies:
    keep the biometric ONLY for an enrolled speaker; discard a stranger's."""
    return is_enrolled_label(label, enrolled)


def guard_embedding(embedding, label: Optional[str],
                    enrolled: Optional[Iterable[str]] = None):
    """Return *embedding* when the resolved speaker is enrolled, else None — so a
    caller can write ``self.voiceprint = guard_embedding(emb, label)`` and know a
    stranger's vector is dropped, not banked."""
    return embedding if retain_voiceprint(label, enrolled) else None


def should_attempt_voiceprint(has_resolver: bool,
                              enrolled: Optional[Iterable[str]] = None) -> bool:
    """Whether computing a voiceprint is warranted at all. Identification needs a
    resolver; without one (or with an empty enrolled population that a supplied
    registry proves) there is no one to match against, so computing a biometric
    only banks strangers' data. Fail-safe: no resolver → don't."""
    if not has_resolver:
        return False
    if enrolled is not None and not list(enrolled):
        return False
    return True
