"""tell.py — deviation detection between promise baseline and new transcript.

TellEngine maintains a promise baseline from recent ring commitment/task events
and scores each new transcript against it using lexical overlap + confidence
delta. When the deviation score clears a threshold it fires a DeviationAlertCard
with the conflicting prior and current summaries side by side.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from ..memory.ring_buffer import SemanticRingBuffer


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


_STOPWORDS = {
    "i", "me", "my", "the", "a", "an", "and", "or", "to", "of",
    "in", "on", "at", "it", "is", "was", "be", "will", "for",
    "that", "this", "with", "you", "your",
}


def _keywords(text: str) -> set[str]:
    return _tokens(text) - _STOPWORDS


def _overlap(a: str, b: str) -> float:
    """Jaccard overlap on meaningful keywords."""
    ka, kb = _keywords(a), _keywords(b)
    if not ka or not kb:
        return 0.0
    return len(ka & kb) / len(ka | kb)


@dataclass
class DeviationResult:
    fired: bool
    score: float          # 0-1; higher = more deviant
    prior_summary: str
    prior_confidence: float
    new_summary: str
    new_confidence: float
    card: dict | None


class TellEngine:
    """Detect contradictions between ring promise baseline and new transcripts."""

    def __init__(
        self,
        ring: SemanticRingBuffer,
        *,
        lookback_limit: int = 20,
        deviation_threshold: float = 0.55,
        min_prior_confidence: float = 0.10,  # low floor: don't discard weak priors
    ):
        self.ring = ring
        self.lookback_limit = lookback_limit
        self.deviation_threshold = deviation_threshold
        self.min_prior_confidence = min_prior_confidence

    def _baseline(self) -> list:
        """Return recent task/commitment ring buckets above the confidence floor."""
        buckets = self.ring.latest(kind="task", limit=self.lookback_limit)
        return [b for b in buckets if b.event.confidence >= self.min_prior_confidence]

    def check(self, transcript: str, confidence: float = 0.80) -> DeviationResult:
        """Score transcript against the promise baseline.

        Deviation is defined as: moderate topic overlap (same topic) AND
        a large confidence delta between prior and new claim.

        Returns a DeviationResult; .fired is True when score >= deviation_threshold.
        """
        baseline = self._baseline()
        if not baseline:
            return DeviationResult(
                fired=False, score=0.0,
                prior_summary="", prior_confidence=0.0,
                new_summary=transcript, new_confidence=confidence,
                card=None,
            )

        best_prior = None
        best_score = 0.0
        for bucket in baseline:
            prior_text = bucket.event.summary
            overlap = _overlap(prior_text, transcript)
            conf_delta = abs(confidence - bucket.event.confidence)
            # Score peaks when overlap is moderate (same topic) but conf differs
            score = overlap * conf_delta * 2.0  # scale to ~0-1
            score = min(score, 1.0)
            if score > best_score:
                best_score = score
                best_prior = bucket

        fired = best_score >= self.deviation_threshold
        prior_summary = best_prior.event.summary if best_prior else ""
        prior_conf = best_prior.event.confidence if best_prior else 0.0

        card = None
        if fired:
            card = _deviation_alert_card(
                prior_summary=prior_summary,
                prior_confidence=prior_conf,
                new_summary=transcript,
                new_confidence=confidence,
                score=best_score,
            )

        return DeviationResult(
            fired=fired,
            score=best_score,
            prior_summary=prior_summary,
            prior_confidence=prior_conf,
            new_summary=transcript,
            new_confidence=confidence,
            card=card,
        )


def _deviation_alert_card(
    prior_summary: str,
    prior_confidence: float,
    new_summary: str,
    new_confidence: float,
    score: float,
) -> dict:
    from ..hud import themes as T
    return {
        "type":             "DeviationAlertCard",
        "dismiss_ms":       5000,
        "score":            round(score, 3),
        "prior_summary":    prior_summary,
        "prior_confidence": prior_confidence,
        "new_summary":      new_summary,
        "new_confidence":   new_confidence,
        "primary":          new_summary,
        "eyebrow":          "Sounds different\u2026",
        "footer":           prior_summary,
        "lines":            ["Sounds different\u2026", new_summary, prior_summary],
        "layout": {
            "eyebrow":   {"x": 128, "y": 64,  "size": "sm",   "color": T.WARNING_AMBER, "tracking": 2},
            "separator": {"x1": 48, "x2": 208, "y": 80},
            "primary":   {"x": 128, "y": 108, "size": "md",   "color": T.TEXT_PRIMARY},
            "divider":   {"x1": 80, "x2": 176, "y": 132},
            "footer":    {"x": 128, "y": 156, "size": "sm",   "color": T.TEXT_GHOST},
            "score_dot": {"x": 128, "y": 178, "r": 4,         "color": T.ACCENT_ATTENTION},
        },
    }
