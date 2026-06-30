"""lie_lens/linguistic.py — Linguistic deception marker extraction.

Extracts hedging, pronoun use, complexity, negation, and specificity
from a plain-text utterance (output of the on-device STT pipeline).
No external NLP library required — pure Python regex + word lists.
"""
from __future__ import annotations

import re
from typing import Optional

from .schema import LinguisticFrame

# Hedging word/phrase patterns (from deception research literature)
HEDGE_PATTERNS = re.compile(
    r"\b(maybe|perhaps|possibly|probably|might|could|sort of|kind of"
    r"|i think|i believe|i guess|i suppose|i feel like|it seems"
    r"|more or less|in a way|somehow|apparently|i'm not sure"
    r"|if i remember|as far as i know|roughly|approximately)\b",
    re.IGNORECASE,
)

FIRST_PERSON = re.compile(r"\b(i|me|my|mine|myself)\b", re.IGNORECASE)

NEGATION = re.compile(
    r"\b(not|no|never|nobody|nothing|nowhere|neither|nor|cannot|can't"
    r"|don't|doesn't|didn't|won't|wouldn't|shouldn't|couldn't|isn't"
    r"|aren't|wasn't|weren't|hasn't|haven't|hadn't)\b",
    re.IGNORECASE,
)

# Specificity markers: dates, numbers, names of places/objects
SPECIFICITY = re.compile(
    r"\b(\d{1,2}[:/]\d{2}|\d{4}|\$\d+|\d+ (minutes?|hours?|days?|weeks?)"
    r"|exactly|specifically|precisely|at \d|on \w+day)\b",
    re.IGNORECASE,
)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b[a-z']+\b", text.lower())


def _sentence_count(text: str) -> int:
    return max(len(re.findall(r"[.!?]+", text)), 1)


def extract_linguistic_features(text: str) -> LinguisticFrame:
    """Extract all linguistic deception markers from a text utterance."""
    if not text or not text.strip():
        return LinguisticFrame(
            text=text,
            hedging_score=0.0,
            first_person_rate=0.0,
            complexity_score=0.5,
            negation_rate=0.0,
            specificity_score=0.0,
        )

    tokens = _tokenize(text)
    n = max(len(tokens), 1)
    sentences = _sentence_count(text)

    hedge_count = len(HEDGE_PATTERNS.findall(text))
    fp_count = len(FIRST_PERSON.findall(text))
    neg_count = len(NEGATION.findall(text))
    spec_count = len(SPECIFICITY.findall(text))

    # Complexity: avg words per sentence, normalised to 0-1
    avg_words = n / sentences
    complexity = min(avg_words / 25.0, 1.0)  # 25 words/sentence = max complexity

    return LinguisticFrame(
        text=text,
        hedging_score=min(hedge_count / max(n * 0.05, 1), 1.0),
        first_person_rate=fp_count / n,
        complexity_score=complexity,
        negation_rate=min(neg_count / max(n * 0.05, 1), 1.0),
        specificity_score=min(spec_count / max(sentences, 1) / 3.0, 1.0),
    )
