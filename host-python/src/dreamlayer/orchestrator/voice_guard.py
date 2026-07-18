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
import unicodedata
from typing import Iterable, Optional

# The wearer themself — always an enrolled, consenting identity (their own device,
# their own voice). Case-insensitive.
SELF_LABELS = frozenset({"me", "self", "wearer", "owner", "i"})

# Diarization placeholders and non-identities: a resolver emits these when it
# could NOT put a name to the voice. They denote "someone", never "a specific
# enrolled someone", so they are strangers for retention purposes.
PLACEHOLDER_LABELS = frozenset({
    "", "them", "they", "other", "others", "unknown", "unk", "stranger",
    "strangers", "guest", "guests", "someone", "somebody", "person", "people",
    "speaker", "voice", "talker", "caller", "party", "member", "participant",
    "anon", "anonymous", "user", "cluster", "segment", "diarized", "n/a", "na",
    "none", "null", "?", "-", "--",
})

# Enumerated diarization slots — "speaker0", "spk_3", "voice-2", "guest 2",
# "unknown_2", "person 3", "Speaker A", "participant1", "p1", "s5" … — a
# placeholder PREFIX, any separator, then a number OR a single trailing letter
# (or nothing). A denylist can never be exhaustive (that is what the explicit
# `enrolled` allowlist is for); this catches the realistic families a resolver
# emits for an UNIDENTIFIED speaker, so the no-registry fallback isn't porous.
_PLACEHOLDER_PREFIXES = (
    "speaker", "spk", "spkr", "voice", "vox", "talker", "cluster", "segment",
    "seg", "diariz[a-z]*", "user", "usr", "person", "guest", "member",
    "participant", "caller", "party", "unknown", "unk", "anon", "anonymous",
    "stranger", "other", "others", "someone", "somebody", "id", "uid",
    "s", "p", "d", "u", "v", "c", "m", "g", "n",
)
_PLACEHOLDER_RE = re.compile(
    r"^(?:" + "|".join(_PLACEHOLDER_PREFIXES) + r")[\s_\-.:#/]*(?:\d+|[a-z])?$",
    re.IGNORECASE)


def _norm(label: Optional[str]) -> str:
    """Normalise a label for comparison: NFKC (folds fullwidth/compatibility
    homoglyphs), strip zero-width joiners a resolver or attacker might smuggle in,
    then lower + trim."""
    s = unicodedata.normalize("NFKC", label or "")
    s = s.replace("​", "").replace("‌", "").replace("‍", "").replace("﻿", "")
    return s.strip().lower()


def _is_placeholder(norm: str) -> bool:
    if (not norm) or (norm in PLACEHOLDER_LABELS) or _PLACEHOLDER_RE.match(norm):
        return True
    # multi-word placeholders ("someone else", "guest of honor", "speaker two"):
    # if the LEADING token is itself a placeholder, the whole label is one.
    first = norm.split(maxsplit=1)[0] if norm.split() else ""
    return first in PLACEHOLDER_LABELS or bool(_PLACEHOLDER_RE.match(first))


def is_self(label: Optional[str]) -> bool:
    """True when the label denotes the wearer — their own voiceprint is theirs to
    keep."""
    return _norm(label) in SELF_LABELS


def is_enrolled_label(label: Optional[str], enrolled: Optional[Iterable[str]] = None) -> bool:
    """True when *label* denotes an ENROLLED speaker — the wearer, or an identity
    we are entitled to keep a voiceprint for.

    When an explicit *enrolled* registry is supplied it is AUTHORITATIVE: the
    label must be a member (self always passes), and the placeholder heuristic is
    NOT consulted — so an enrolled speaker registered under a short id like "S1"
    or "Voice2" is still retained (the heuristic must never override the registry
    the caller actually holds). With NO registry we fall back to a placeholder
    denylist: a resolver returns a real name only when a voice matched a
    registered voiceprint, and an unmatched voice comes back empty or as a
    diarization placeholder — so a non-empty, non-placeholder label is treated as
    a match. That fallback is best-effort (a denylist can't be exhaustive); pass
    an `enrolled` allowlist for a strict guarantee. Fail-safe: not positively
    enrolled → stranger.
    """
    norm = _norm(label)
    if norm in SELF_LABELS:
        return True
    if enrolled is not None:                     # registry is authoritative
        return norm in {_norm(e) for e in enrolled}
    return not _is_placeholder(norm)


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
