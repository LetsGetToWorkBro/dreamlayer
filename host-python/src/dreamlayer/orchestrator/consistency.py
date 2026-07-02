"""consistency.py — Candor: does this contradict what you already recorded?

Display name: **Candor** — the inward twin of Truth Lens (Truth Lens judges
others' credibility; Candor keeps your own story honest). Class stays
ConsistencyEngine.

The privacy-respecting reimagining of "fact-check": no cloud, no web, no
external claim-of-truth. It only ever compares a new statement against
*your own* memories on the device, and flags when the two can't both be
true — "you said the meeting was at 3, now you're saying 4."

Three kinds of contradiction over a shared subject:
  negation  one side asserts, the other denies the same thing
  antonym   the two sides name opposite states (open/closed, on/off)
  value     the two sides give different numbers/times for the same thing

Everything is a deterministic, offline heuristic over the memory ring. It
never claims *which* statement is right — only that they disagree, so you
can notice. Private memories (meta.private) are never compared; the caller
gates the whole thing behind the Privacy Veil.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_TOKEN = re.compile(r"[a-z0-9:]+")
_NUM = re.compile(r"\b\d{1,4}(?::\d{2})?\b")

_NEGATORS = frozenset({
    "not", "no", "never", "none", "cannot", "cant", "nope", "without",
    "isnt", "arent", "wasnt", "werent", "wont", "dont", "doesnt", "didnt",
    "cant", "couldnt", "wouldnt", "shouldnt", "aint", "nothing",
})

# opposite states — if one side has a, the other b, over a shared subject
_ANTONYMS = [
    ("open", "closed"), ("on", "off"), ("up", "down"), ("in", "out"),
    ("cheap", "expensive"), ("early", "late"), ("free", "busy"),
    ("true", "false"), ("yes", "no"), ("win", "lose"), ("won", "lost"),
    ("alive", "dead"), ("full", "empty"), ("hot", "cold"), ("left", "right"),
    ("start", "end"), ("began", "ended"), ("increase", "decrease"),
    ("up", "off"), ("paid", "unpaid"), ("done", "pending"),
]

_STOP = frozenset({
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "at", "it",
    "is", "was", "be", "will", "for", "that", "this", "with", "you",
    "your", "i", "we", "he", "she", "they", "them", "my", "me", "are",
    "were", "so", "but", "as", "by", "from", "have", "has", "had",
    "about", "there", "their", "his", "her", "our",
}) | _NEGATORS


def _words(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


def _keywords(text: str) -> set[str]:
    return {w for w in _words(text) if w not in _STOP and len(w) >= 3
            and not w.isdigit()}


def _has_negator(words: list[str]) -> bool:
    return any(w in _NEGATORS for w in words)


def contradicts(claim: str, prior: str, min_shared: int = 2):
    """Pairwise contradiction test over a shared subject. Returns
    (reason, detail) or None. Shared by Candor and the Provenance Lens."""
    claim_words = _words(claim)
    claim_keys = _keywords(claim)
    if len(claim_keys & _keywords(prior)) < min_shared:
        return None                       # not clearly the same subject
    pwords = _words(prior)
    if _has_negator(claim_words) != _has_negator(pwords):
        return ("negation", "one asserts, one denies")
    pset, cset = set(pwords), set(claim_words)
    for a, b in _ANTONYMS:
        if (a in pset and b in cset) or (b in pset and a in cset):
            return ("antonym", f"{a} vs {b}")
    cnums = set(_NUM.findall(claim.lower()))
    pnums = set(_NUM.findall(prior.lower()))
    if pnums and cnums and pnums.isdisjoint(cnums):
        return ("value", f"{sorted(pnums)[0]} vs {sorted(cnums)[0]}")
    return None


@dataclass
class ConsistencyResult:
    fired: bool
    reason: str            # "" | "negation" | "antonym" | "value"
    prior_summary: str
    new_summary: str
    detail: str            # the specific clash (the antonym pair, the values)
    card: Optional[dict]


class ConsistencyEngine:
    """Compares a new statement against your recorded memories."""

    def __init__(self, ring, *, lookback: int = 40,
                 min_shared: int = 2, min_prior_confidence: float = 0.30):
        self.ring = ring
        self.lookback = lookback
        self.min_shared = min_shared
        self.min_prior_confidence = min_prior_confidence

    def _baseline(self):
        out = []
        for b in self.ring.latest(limit=self.lookback):
            ev = b.event
            if (getattr(ev, "meta", None) or {}).get("private"):
                continue                      # private is never compared
            if float(getattr(ev, "confidence", 0.0) or 0.0) < self.min_prior_confidence:
                continue
            out.append(ev)
        return out

    def check(self, claim: str, now: Optional[float] = None) -> ConsistencyResult:
        """Compare `claim` against the memory baseline for a contradiction."""
        for ev in self._baseline():
            prior = getattr(ev, "summary", "") or ""
            clash = contradicts(claim, prior, self.min_shared)
            if clash is not None:
                return self._fire(clash[0], prior, claim, clash[1])
        return ConsistencyResult(False, "", "", claim, "", None)

    def _fire(self, reason, prior, claim, detail) -> ConsistencyResult:
        return ConsistencyResult(
            fired=True, reason=reason, prior_summary=prior,
            new_summary=claim, detail=detail,
            card=_consistency_card(prior, claim, reason, detail))


def _consistency_card(prior: str, claim: str, reason: str, detail: str) -> dict:
    return {
        "type": "ConsistencyCard",
        "dismiss_ms": 5000,
        "eyebrow": "You said different before",
        "primary": claim,
        "footer": prior,
        "reason": reason,
        "detail": detail,
        "color": "accent_attention",
        "lines": ["You said different before", claim, "earlier:", prior],
    }
