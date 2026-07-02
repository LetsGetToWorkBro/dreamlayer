"""ai_brain/router.py — pick the tier, honour the cloud gate.

The router holds vision and knowledge tiers in preference order (device →
laptop → cloud) and answers a request from the lowest tier that can. Cloud
tiers are skipped unless cloud is opted in for this session — and nothing
crosses to the cloud silently.

    brain = BrainRouter()
    brain.add_vision(device_vlm)          # is_cloud=False, small
    brain.add_vision(laptop_vlm)          # is_cloud=False, rich (Mac mini)
    brain.add_vision(cloud_vlm)           # is_cloud=True  (opt-in only)
    brain.explain(frame, "snake plant")           # -> device answer
    brain.explain(frame, "snake plant", "more")   # -> laptop answer
    brain.opt_in_cloud(True)              # this session only
"""
from __future__ import annotations

from typing import Optional

from .schema import Answer
from .brains import VisionBrain, KnowledgeBrain


class BrainRouter:
    def __init__(self, cloud_opt_in: bool = False):
        self._vision: list[VisionBrain] = []
        self._knowledge: list[KnowledgeBrain] = []
        self.cloud_opt_in = cloud_opt_in

    # -- registration (in preference order) -----------------------------

    def add_vision(self, brain: VisionBrain) -> None:
        self._vision.append(brain)

    def add_knowledge(self, brain: KnowledgeBrain) -> None:
        self._knowledge.append(brain)

    def opt_in_cloud(self, on: bool = True) -> None:
        """Allow cloud tiers for this session. Off by default; never sticky
        beyond the session — the caller re-opts each time."""
        self.cloud_opt_in = on

    def has_vision(self) -> bool:
        return any(self._allowed(b) for b in self._vision)

    # -- routing ---------------------------------------------------------

    def _allowed(self, brain) -> bool:
        return self.cloud_opt_in or not getattr(brain, "is_cloud", False)

    def explain(self, frame, label: str,
                want: str = "quick") -> Optional[Answer]:
        """Explain an object from the lowest tier that can answer."""
        for brain in self._vision:
            if not self._allowed(brain):
                continue                      # cloud, not opted in
            try:
                ans = brain.explain(frame, label, want=want)
            except Exception:
                continue                      # a dead tier is skipped, not fatal
            if ans is not None and not ans.is_empty():
                if not ans.tier:
                    ans.tier = getattr(brain, "tier", "")
                return ans
        return None

    def ask(self, query: str) -> Optional[Answer]:
        """Answer a question from your own knowledge (folds into Lucid Recall)."""
        for brain in self._knowledge:
            if not self._allowed(brain):
                continue
            try:
                ans = brain.ask(query)
            except Exception:
                continue
            if ans is not None and not ans.is_empty():
                if not ans.tier:
                    ans.tier = getattr(brain, "tier", "")
                return ans
        return None
