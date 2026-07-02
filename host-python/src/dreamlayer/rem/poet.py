"""rem/poet.py — free association across the day's anchors.

Dreams recombine: the poet takes two memories from different hours and
composes one phrase that belongs to neither — "the gym's clock in your
mother's kitchen". Fully offline and deterministic under the cycle's
seed: fragments are extracted with the same shallow noun heuristics the
ingest pipeline uses, then rewoven through a small template grammar.

The poet never invents content. Every word in a dream phrase traces to
one of the two source summaries (plus glue words), so the morning reel
is a readout, not a hallucination.
"""
from __future__ import annotations

import random
import re
from typing import Optional

_STOP = {
    "the", "a", "an", "my", "your", "our", "their", "his", "her", "its",
    "to", "of", "in", "on", "at", "by", "for", "with", "and", "or", "but",
    "i", "you", "we", "they", "he", "she", "it", "is", "was", "are", "were",
    "will", "would", "should", "did", "do", "done", "have", "has", "had",
    "that", "this", "there", "here", "about", "promised", "remember",
    "said", "told", "asked", "need", "needs", "left", "put",
}

# "at the gym", "on the kitchen table" → trailing noun phrase
_PLACE_RE = re.compile(
    r"\b(?:at|in|on|near|by|inside|behind|under)\s+"
    r"(?:the\s+|a\s+|my\s+|your\s+|our\s+)?([a-z][a-z ]{2,24}?)(?:[,.;]|$)",
    re.IGNORECASE,
)

_TEMPLATES = [
    "the {a}'s {b}",
    "{a} in the {b}",
    "the {b} remembers {a}",
    "{a}, but the {b} is watching",
    "a {a} made of {b}",
    "the {b} at the hour of {a}",
    "{a} waiting under the {b}",
]


def _fragments(summary: str) -> list[str]:
    """Content words + place phrases from one summary, order-stable."""
    out: list[str] = []
    text = (summary or "").strip()
    for m in _PLACE_RE.finditer(text):
        out.append(m.group(1).strip().lower())
    for tok in re.findall(r"[a-zA-Z][a-zA-Z'-]+", text):
        low = tok.lower()
        if low not in _STOP and len(low) > 2 and low not in out:
            out.append(low)
    return out or ["something"]


class DreamPoet:
    def __init__(self, rng: Optional[random.Random] = None) -> None:
        self._rng = rng or random.Random()

    def weave(self, summary_a: str, summary_b: str) -> str:
        """One dream phrase from two memories. Deterministic under the
        poet's rng; every content word traces to a source summary."""
        frags_a = _fragments(summary_a)
        frags_b = _fragments(summary_b)
        a = self._rng.choice(frags_a)
        b = self._rng.choice(frags_b)
        if a == b and len(frags_b) > 1:
            b = frags_b[(frags_b.index(b) + 1) % len(frags_b)]
        template = self._rng.choice(_TEMPLATES)
        phrase = template.format(a=a, b=b)
        # HUD discipline: six-ish words, no sprawl
        words = phrase.split()
        return " ".join(words[:8])
