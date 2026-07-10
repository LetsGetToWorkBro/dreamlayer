"""answer_ahead.py — the answer-ahead copilot.

Someone asks you something across the table. Before you've even opened your
mouth, the answer is waiting at the edge of your vision — pulled from your own
knowledge (the Brain, the cloud if you've opted in), in time to say it yourself,
naturally. No wake word: the glasses simply heard the question.

Two jobs:
  detect   Is this spoken line a *question*, and is it aimed at you (or is it a
           plain factual question worth having the answer to)? Rhetorical asides,
           tag questions ("…right?"), and "you know?" filler never count.
  fetch    Hand the question to an answer seam (Brain / cloud) and surface the
           answer only when it comes back confident — so the HUD stays quiet on
           the things it can't actually help with.

Conservative and paced: one prompt per cooldown, above a confidence floor, held
during Focus, Veil-gated by the caller. The mic + ASR are the device seam; the
answer source is the same knowledge tier the Juno asks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

_WH = ("what", "where", "when", "who", "whom", "whose", "why", "how", "which")
_AUX_YOU = re.compile(
    r"^\s*(?:do|did|does|can|could|would|will|are|is|were|was|have|has|had)\s+you\b",
    re.IGNORECASE)
# throwaway questions that aren't really asking you anything
_RHETORICAL = re.compile(
    r"\b(?:you know|you see|right|okay|ok|yeah|huh|isn'?t it|aren'?t (?:they|we)|"
    r"don'?t you think|guess what)\b\s*\??\s*$",
    re.IGNORECASE)
_SECOND_PERSON = re.compile(r"\byou\b|\byour\b|\byours\b", re.IGNORECASE)


@dataclass
class Question:
    text: str
    speaker: str
    is_question: bool
    directed_at_me: bool
    kind: str            # "" | "factual" | "personal" | "yesno"


def detect_question(text: str, speaker: str = "") -> Question:
    """Judge whether `text` is a question worth pre-answering."""
    t = (text or "").strip()
    miss = Question(t, speaker, False, False, "")
    if not t:
        return miss
    low = t.lower()
    first = re.findall(r"[a-z']+", low)
    first = first[0] if first else ""
    marked = t.endswith("?")
    interrogative = marked or first in _WH or bool(_AUX_YOU.search(t))
    if not interrogative:
        return miss
    if _RHETORICAL.search(t):           # "…right?", "you know?" — not a real ask
        return miss
    at_me = bool(_SECOND_PERSON.search(t)) or bool(_AUX_YOU.search(t))
    if first in _WH and not at_me:
        kind = "factual"                # "what year did the wall fall?"
    elif at_me:
        kind = "personal"              # "when did you last see Marcus?"
    else:
        kind = "yesno"
    # only surface for something we can genuinely help with: a factual lookup, or
    # a question pointed at you. A bare yes/no aside to no one is left alone.
    if kind == "yesno" and not at_me:
        return miss
    return Question(t, speaker, True, at_me, kind)


# --- the answer seam ---------------------------------------------------------
# answer_fn(question) -> {"text": str, "confidence": 0-1, "source": str} | None.
# The hub injects one that routes through the Brain (and cloud if opted in); pure
# here so tests pin the answer.

AnswerFn = Callable[[str], Optional[dict]]


@dataclass
class Prompt:
    fired: bool
    question: str
    speaker: str
    answer: str
    confidence: float
    source: str
    card: Optional[dict]


class AnswerAhead:
    """Pre-answers questions it overhears, in time for you to speak."""

    def __init__(self, answer_fn: Optional[AnswerFn] = None, *,
                 min_confidence: float = 0.55, cooldown_s: float = 20.0):
        self.answer_fn = answer_fn
        self.min_confidence = float(min_confidence)
        self.cooldown_s = float(cooldown_s)
        self._last = -1e9

    def consider(self, text: str, speaker: str = "", now: float = 0.0) -> Prompt:
        """Look at one spoken line; if it's an answerable question, fetch and
        surface the answer. Returns a Prompt — fired only when confident and the
        cooldown has passed."""
        idle = Prompt(False, text, speaker, "", 0.0, "", None)
        q = detect_question(text, speaker)
        if not q.is_question or self.answer_fn is None:
            return idle
        if (now - self._last) < self.cooldown_s:
            return idle
        try:
            a = self.answer_fn(text)
        except Exception:
            a = None
        if not a:
            return idle
        ans = (a.get("text") or "").strip()
        conf = float(a.get("confidence", 0.0) or 0.0)
        if not ans or conf < self.min_confidence:
            return idle
        self._last = now
        source = (a.get("source") or "").strip()
        from ..hud import cards
        card = cards.answer_ahead(question=text, answer=ans,
                                  speaker=speaker or "", source=source)
        return Prompt(True, text, speaker, ans, conf, source, card)
