"""truth_lens/linguistic.py — Linguistic deception marker extractor.

Maps to the BERT-tiny distilled NLU stage of the Lie Lens pipeline.
Extracts hedging rate, first-person pronoun rate, sentence complexity,
and negation rate from raw transcript text.

No ML model required: pure token-frequency heuristics that match
the distilled BERT-tiny feature set used on the Halo NPU.
"""
from __future__ import annotations

import re
from typing import Optional

from .schema import LinguisticFrame

# Token sets
HEDGE_WORDS = {
    "maybe", "perhaps", "possibly", "probably", "might", "could", "should",
    "seem", "seems", "appeared", "appears", "think", "thought", "believe",
    "guess", "suppose", "kinda", "sorta", "somewhat", "around", "approximately",
    "kind of", "sort of", "i guess", "i think", "i mean", "you know",
    "like", "basically", "literally", "honestly", "honestly speaking",
}

FIRST_PERSON = {"i", "i'm", "i've", "i'd", "i'll", "me", "my", "mine", "myself"}

NEGATION_WORDS = {
    "no", "not", "never", "none", "nothing", "nobody", "nowhere",
    "neither", "nor", "don't", "doesn't", "didn't", "won't", "wouldn't",
    "can't", "cannot", "couldn't", "shouldn't", "isn't", "aren't",
    "wasn't", "weren't", "haven't", "hasn't", "hadn't",
}


class LinguisticAnalyzer:
    """Extracts linguistic deception markers from transcript text."""

    def analyse(self, text: Optional[str]) -> Optional[LinguisticFrame]:
        """Return LinguisticFrame for text, or None if text is empty."""
        if not text or not text.strip():
            return None

        tokens = self._tokenize(text)
        if not tokens:
            return None

        n = len(tokens)
        hedges = sum(1 for t in tokens if t in HEDGE_WORDS)
        first_p = sum(1 for t in tokens if t in FIRST_PERSON)
        negations = sum(1 for t in tokens if t in NEGATION_WORDS)

        # Complexity: average sentence length (longer = more complex)
        sentences = re.split(r'[.!?]+', text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        avg_sent_len = (sum(len(s.split()) for s in sentences) /
                        max(len(sentences), 1))
        # Normalize: 0 = simple (5 words/sentence), 1 = complex (25+ words)
        complexity = min(max((avg_sent_len - 5) / 20, 0.0), 1.0)

        return LinguisticFrame(
            hedging_rate=round(hedges / n, 4),
            first_person_rate=round(first_p / n, 4),
            complexity_score=round(complexity, 4),
            negation_rate=round(negations / n, 4),
            word_count=n,
        )

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-z']+", text.lower())
