"""ai_brain/cloud.py — the opt-in cloud tier (Phase 4).

The most capable tier, for the hardest asks — and the only one that leaves
your devices, so the router never uses it unless you `opt_in_cloud()` for the
session. The actual API call is injected (`ask_fn` / `explain_fn`), so this
is provider-agnostic and testable without a network: point it at the repo's
existing LLM client, or any vision API.
"""
from __future__ import annotations

from typing import Callable, Optional

from .schema import Answer


class CloudKnowledgeBrain:
    tier = "cloud"
    is_cloud = True

    def __init__(self, ask_fn: Callable[[str], str], name: str = "cloud"):
        self._ask = ask_fn
        self.tier = name

    def ask(self, query: str) -> Optional[Answer]:
        try:
            text = self._ask(query)
        except Exception:
            return None
        if not text:
            return None
        return Answer(text=text, tier=self.tier, sources=[self.tier],
                      confidence=0.6)


class CloudVisionBrain:
    tier = "cloud"
    is_cloud = True

    def __init__(self, explain_fn: Callable[[object, str, str], str],
                 name: str = "cloud"):
        self._explain = explain_fn
        self.tier = name

    def explain(self, frame, label: str, want: str = "quick") -> Optional[Answer]:
        try:
            text = self._explain(frame, label, want)
        except Exception:
            return None
        if not text:
            return None
        return Answer(text=text, tier=self.tier, sources=[self.tier],
                      confidence=0.65)
