"""veritas.py — Veritas: is what's being said actually *true*?

The live fact-checker. While Candor keeps your own story honest and Truth Lens
reads a face for deception, Veritas checks the *content* of what's said against
what can be verified — quietly, in time for you to respond naturally.

Two independent checks over each spoken line:

  self-contradiction   Does the speaker contradict what *they themselves* told
                       you before? Deterministic, offline — it reuses Candor's
                       contradiction test, scoped to this one speaker's prior
                       lines in the conversation ledger. "Last week you said the
                       deal closed at 2M; now you're saying 3."

  world check          Is this checkable claim actually so? A verifiable
                       assertion ("the capital of Australia is Sydney") is handed
                       to a verifier — your Brain, or the cloud tier if you've
                       opted in — which returns supported / disputed / unverified.
                       The verifier is a *seam*: pure here, injected by the hub.

Speed: the offline self-contradiction pass fires synchronously and instantly;
the world check is meant to run *off* the caption path. `check(..., world=False)`
takes only the fast half, and `world_result()` folds an externally-fetched
verdict back in under the same worth/cooldown rules — so the hub can cache the
verify, run it on a background worker with a deadline (see
`ai_brain/world_check.py`), and deliver the card when it lands in time.

Claim detection is a conservative heuristic: only assertive, checkable
statements (a number, a date, a factual predicate) are ever sent on — hedged
opinions ("I think", "maybe") and questions never are. It fires sparingly, one
verdict per speaker per cooldown, and only above a confidence floor, so it
informs without heckling. Veil-gated by the caller.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from .consistency import contradicts

# --- what counts as a checkable, assertive claim ----------------------------

# hedges: if the line leads with one of these, it's an opinion, not a claim
_HEDGE = re.compile(
    r"^\s*(?:i think|i feel|i guess|i believe|i suppose|maybe|perhaps|probably|"
    r"i'?d say|in my opinion|i reckon|might be|could be|it seems|kind of|sort of)\b",
    re.IGNORECASE)

# a numeric / date signal — years, quantities, measurements, percentages
_NUMERIC = re.compile(
    r"\b(?:\d{4}s?|\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?\s*(?:%|percent|million|billion|"
    r"thousand|meters?|metres?|feet|miles|km|kg|pounds|dollars|degrees|years?))\b",
    re.IGNORECASE)

# factual predicates — the vocabulary of a verifiable statement of fact
_FACT_WORDS = frozenset({
    "capital", "invented", "founded", "discovered", "largest", "smallest",
    "tallest", "highest", "lowest", "oldest", "longest", "biggest", "first",
    "population", "born", "died", "located", "distance", "invented", "author",
    "wrote", "directed", "won", "founded", "president", "capital", "speed",
    "temperature", "boiling", "melting", "orbit", "element", "atomic",
    "discovered", "originally", "actually", "the fact", "official",
})

_ASSERT = re.compile(r"\b(?:is|are|was|were|has|have|had|equals?|means?)\b",
                     re.IGNORECASE)


@dataclass
class Claim:
    """A checkable assertion pulled from a spoken line."""
    text: str
    speaker: str
    checkable: bool
    reason: str          # why we judged it checkable ("numeric" | "factual")


def detect_claim(text: str, speaker: str = "") -> Claim:
    """Judge whether `text` is an assertive, checkable factual claim.

    Conservative by design: a question, a hedge, or a bare opinion is *not*
    checkable, so Veritas never second-guesses feelings or small talk.
    """
    t = (text or "").strip()
    if not t or t.endswith("?"):
        return Claim(t, speaker, False, "")
    if _HEDGE.search(t):
        return Claim(t, speaker, False, "hedged")
    low = t.lower()
    if _NUMERIC.search(t):
        return Claim(t, speaker, True, "numeric")
    if _ASSERT.search(t) and any(w in low for w in _FACT_WORDS):
        return Claim(t, speaker, True, "factual")
    return Claim(t, speaker, False, "")


# --- the verifier seam -------------------------------------------------------
# A verifier takes a claim string and returns a verdict dict, or None when it
# can't reach any authority (offline, no cloud). The hub injects one that routes
# through the Brain / cloud tier; here we stay pure so tests can pin the outcome.
#
#   {"verdict": "supported" | "disputed" | "unverified",
#    "basis":   "<one short line of why>",
#    "confidence": 0.0-1.0}

VerifyFn = Callable[[str], Optional[dict]]

_VERDICTS = ("supported", "disputed", "unverified")


@dataclass
class FactCheck:
    fired: bool
    verdict: str          # "" | supported | disputed | self_contradiction | unverified
    claim: str
    speaker: str
    basis: str            # short, human: the correction or the corroboration
    detail: str
    confidence: float
    card: Optional[dict]


class Veritas:
    """Fact-checks a live conversation, line by line.

    `verify_fn` is the world-check seam (Brain / cloud). Self-contradiction
    needs no network — it only reads the ledger you already have.
    """

    def __init__(self, verify_fn: Optional[VerifyFn] = None, *,
                 min_shared: int = 2, min_confidence: float = 0.55,
                 per_speaker_cooldown_s: float = 45.0):
        self.verify_fn = verify_fn
        self.min_shared = min_shared
        self.min_confidence = float(min_confidence)
        self.cooldown_s = float(per_speaker_cooldown_s)
        self._last: dict[str, float] = {}     # speaker -> last-fired ts

    def _who(self, speaker: str) -> str:
        return (speaker or "").strip().lower() or "me"

    def cooling(self, speaker: str, now: float) -> bool:
        last = self._last.get(self._who(speaker))
        return last is not None and (now - last) < self.cooldown_s

    def mark(self, speaker: str, now: float) -> None:
        self._last[self._who(speaker)] = now

    def checkable(self, text: str, speaker: str = "") -> bool:
        """Would this line ever be worth a world check? Cheap and offline, so
        the caller can gate an async verify without touching the network."""
        return detect_claim(text, speaker).checkable

    def check(self, text: str, speaker: str = "",
              prior: Optional[list[str]] = None,
              now: float = 0.0, world: bool = True) -> FactCheck:
        """Fact-check one spoken line.

        `prior` is this speaker's earlier lines (the self-contradiction pass,
        offline and instant). The world check runs through the injected
        verifier only when `world=True`; set `world=False` to take just the
        fast offline pass and schedule the world check asynchronously via
        `world_result()`. Returns a FactCheck — fired only when something is
        worth surfacing and the cooldown has elapsed.
        """
        idle = FactCheck(False, "", text, speaker, "", "", 0.0, None)
        claim = detect_claim(text, speaker)
        if not claim.checkable:
            return idle

        # 1) does the speaker contradict their *own* earlier words? (instant)
        for line in reversed(prior or []):
            clash = contradicts(text, line, self.min_shared)
            if clash is not None:
                if self.cooling(speaker, now):
                    return idle
                self.mark(speaker, now)
                basis = f"earlier: “{_clip(line, 34)}”"
                return FactCheck(
                    True, "self_contradiction", text, speaker, basis,
                    clash[1], 0.9,
                    _card("self_contradiction", speaker, text, basis, clash[1]))

        # 2) world check — hand the claim to the verifier (Brain / cloud seam)
        if world and self.verify_fn is not None:
            try:
                v = self.verify_fn(text)
            except Exception:
                v = None
            return self.world_result(text, speaker, v, now)
        return idle

    def world_result(self, text: str, speaker: str, verdict: Optional[dict],
                     now: float = 0.0) -> FactCheck:
        """Turn an external world-check verdict into a FactCheck, applying the
        same 'is this worth surfacing?' rule and per-speaker cooldown as the
        inline path. Safe to call from the async world-check callback: a
        None/unknown verdict, a bare supported, or a cooling speaker all yield
        an idle (unfired) result."""
        idle = FactCheck(False, "", text, speaker, "", "", 0.0, None)
        if not verdict or verdict.get("verdict") not in _VERDICTS:
            return idle
        v = verdict["verdict"]
        conf = float(verdict.get("confidence", 0.0) or 0.0)
        # only "disputed" is worth interrupting for; a bare "supported" stays
        # quiet unless it's a strong corroboration.
        worth = (v == "disputed" and conf >= self.min_confidence) or \
                (v == "supported" and conf >= 0.85)
        if not worth:
            return idle
        if self.cooling(speaker, now):
            return idle
        self.mark(speaker, now)
        basis = (verdict.get("basis") or "").strip()
        return FactCheck(True, v, text, speaker, basis, "",
                         conf, _card(v, speaker, text, basis, ""))


def _clip(s: str, n: int = 60) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# --- the HUD card ------------------------------------------------------------

def _card(verdict: str, speaker: str, claim: str, basis: str, detail: str) -> dict:
    """Build a fact-check card without importing the whole cards module (avoids a
    cycle: cards may reference orchestrator helpers). Colors resolve in themes."""
    from ..hud import cards
    return cards.fact_check(verdict=verdict, speaker=speaker or "them",
                            claim=claim, basis=basis, detail=detail)
