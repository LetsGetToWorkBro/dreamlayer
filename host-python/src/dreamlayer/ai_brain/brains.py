"""ai_brain/brains.py — the brain interfaces and their deterministic mocks.

Two capabilities, each a tiny protocol so any model drops in behind it:

    VisionBrain.explain(frame, label, want) -> Answer   # name/explain a thing
    KnowledgeBrain.ask(query)               -> Answer   # ask your own stuff

Phase 1 ships mocks so the whole pipeline — router, AI Object Lens panel,
HUD, tests — runs today with no model. A real tier (an Ollama vision model
on the Mac mini, or an opt-in cloud API) is the same three methods behind
the same protocol.
"""
from __future__ import annotations

import re
from typing import Optional, Protocol, runtime_checkable

from .schema import Answer


@runtime_checkable
class VisionBrain(Protocol):
    tier: str
    is_cloud: bool

    def explain(self, frame, label: str,
                want: str = "quick") -> Optional[Answer]: ...


@runtime_checkable
class KnowledgeBrain(Protocol):
    tier: str
    is_cloud: bool

    def ask(self, query: str) -> Optional[Answer]: ...


# ---------------------------------------------------------------------------
# Deterministic mocks (Phase 1)
# ---------------------------------------------------------------------------

class MockVisionBrain:
    """A stand-in vision model. Answers from a fixed fact table.

    serves_deep=False models a small on-device tier: it answers a "quick"
    ask but declines "more", so the router escalates to a richer tier.
    """

    def __init__(self, tier: str, facts: dict[str, str],
                 is_cloud: bool = False, serves_deep: bool = True,
                 confidence: float = 0.8):
        self.tier = tier
        self._facts = {k.lower(): v for k, v in facts.items()}
        self.is_cloud = is_cloud
        self._serves_deep = serves_deep
        self._confidence = confidence

    def explain(self, frame, label, want="quick") -> Optional[Answer]:
        if want == "more" and not self._serves_deep:
            return None                       # too small — escalate
        fact = self._facts.get((label or "").lower())
        if fact is None:
            return None
        return Answer(text=fact, tier=self.tier, sources=[self.tier],
                      confidence=self._confidence)


class MockKnowledgeBrain:
    """A stand-in RAG over your own documents (a dict of name -> text)."""

    tier = "laptop"
    is_cloud = False

    def __init__(self, docs: dict[str, str], tier: str = "laptop"):
        self.tier = tier
        self._docs = docs

    _STOP = frozenset({
        "the", "and", "for", "are", "was", "that", "this", "with", "you",
        "your", "what", "how", "who", "why", "when", "where", "does", "did",
        "per", "due", "from", "into", "out", "not", "but", "its", "our",
    })

    def _keywords(self, text: str) -> set[str]:
        return {w for w in re.findall(r"[a-z0-9']{3,}", (text or "").lower())
                if w not in self._STOP}

    def ask(self, query: str) -> Optional[Answer]:
        q = self._keywords(query)
        best, best_hits, best_name = None, 0, ""
        for name, text in self._docs.items():
            hits = len(q & self._keywords(text))
            if hits > best_hits:
                best, best_hits, best_name = text, hits, name
        if best is None or best_hits == 0:
            return None
        # return the most relevant line of the best document
        line = max(best.splitlines() or [best],
                   key=lambda ln: len(q & self._keywords(ln)))
        return Answer(text=line.strip(), tier=self.tier, sources=[best_name],
                      confidence=min(1.0, 0.4 + 0.2 * best_hits))
