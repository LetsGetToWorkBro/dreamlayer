"""ember/grading.py — did you reach it? Graded gently, offline, in words.

The wearer speaks their recall out loud at the doorway; this module compares
it to the guarded answer and maps the overlap to a scheduler grade. The
measure is *recall of the answer's content words* (how much of the moment the
wearer reproduced), not precision — someone who retells the moment in three
warm sentences must never score worse than someone who parrots four words.

Tier-1 and deterministic: lowercase, strip stopwords/punctuation, count.
An optional `similarity_fn(spoken, answer) -> 0..1` hook lets a connected
Brain blend in semantic similarity (embeddings catch "dad" ≈ "my father");
offline, the lexical measure stands alone. Thresholds are deliberately
forgiving — Ember is a practice, not an exam, and a wrongly-harsh FORGOT
both stings and mis-teaches the curve.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from .scheduler import RecallOutcome

EASY_AT = 0.75     # nearly whole → EASY
GOOD_AT = 0.45     # the shape of it → GOOD
HARD_AT = 0.15     # a fragment, reached with effort → HARD
                   # below: an honest miss → FORGOT

_WORD = re.compile(r"[a-zA-Z0-9']+")
_STOP = frozenset(
    "the a an and or but of to in on at by for with from as is are was were "
    "be been being it its this that these those i you he she we they my your "
    "his her our their me him us them so then than too very just about what "
    "did do does had has have will would could should".split())


def _content_words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text or "")
            if w.lower() not in _STOP and len(w) > 1}


def recall_score(spoken: str, answer: str,
                 similarity_fn: Optional[Callable[[str, str], float]] = None) -> float:
    """0..1: how much of the answer's content the spoken attempt carries.
    With a similarity hook, the score is the *better* of lexical and semantic
    — an upgrade path that can only ever grade more gently, never harsher."""
    target = _content_words(answer)
    if not target:
        return 1.0 if (spoken or "").strip() else 0.0
    got = _content_words(spoken)
    lexical = len(target & got) / len(target)
    if similarity_fn is not None:
        try:
            lexical = max(lexical, max(0.0, min(1.0, float(
                similarity_fn(spoken, answer)))))
        except Exception:
            pass   # a broken upgrade must never break the offline grade
    return lexical


def grade_recall(spoken: str, answer: str,
                 similarity_fn: Optional[Callable[[str, str], float]] = None) -> RecallOutcome:
    score = recall_score(spoken, answer, similarity_fn)
    if score >= EASY_AT:
        return RecallOutcome.EASY
    if score >= GOOD_AT:
        return RecallOutcome.GOOD
    if score >= HARD_AT:
        return RecallOutcome.HARD
    return RecallOutcome.FORGOT
