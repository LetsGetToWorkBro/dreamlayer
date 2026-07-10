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
    def __init__(self, cloud_opt_in: bool = False, local_only: bool = False,
                 health=None, deadline_ms: float = 0.0):
        self._vision: list[VisionBrain] = []
        self._knowledge: list[KnowledgeBrain] = []
        self.cloud_opt_in = cloud_opt_in
        # local_only: use ONLY on-device tiers — no Mac mini, no cloud. This
        # is "the phone is the brain" (fully offline, more limited).
        self.local_only = local_only
        # observability + the latency contract: a dead tier is still skipped,
        # not fatal — but the skip is RECORDED (health ledger), and each tier
        # gets a hard per-call deadline so one hung model can't stall a glance
        # (deadline_ms <= 0 disables; orchestrator/budgets.py has the table).
        self.health = health
        self.deadline_ms = deadline_ms

    def _call_tier(self, brain, fn, seam_hint: str):
        """One tier attempt under the deadline; failures recorded, never fatal.
        A success also records the round-trip latency, so the phone's Brain
        screen can show how fast each tier actually is (INNOVATION 3.1)."""
        import time
        from ..orchestrator.budgets import run_with_deadline
        seam = f"brain:{getattr(brain, 'tier', '') or seam_hint}"
        t0 = time.time()
        try:
            ans = run_with_deadline(fn, self.deadline_ms,
                                    health=self.health, seam=seam)
        except Exception as exc:
            if self.health is not None:
                self.health.record_failure(seam, exc)
            return None
        if ans is not None and self.health is not None:
            self.health.record_ok(seam, ms=(time.time() - t0) * 1000.0)
        return ans

    # -- registration (in preference order) -----------------------------

    def add_vision(self, brain: VisionBrain) -> None:
        self._vision.append(brain)

    def add_knowledge(self, brain: KnowledgeBrain) -> None:
        self._knowledge.append(brain)

    def opt_in_cloud(self, on: bool = True) -> None:
        """Allow cloud tiers for this session. Off by default; never sticky
        beyond the session — the caller re-opts each time."""
        self.cloud_opt_in = on

    def set_local_only(self, on: bool = True) -> None:
        """On-device only — the phone is the brain (fully offline)."""
        self.local_only = on

    def has_vision(self) -> bool:
        return any(self._allowed(b) for b in self._vision)

    # -- routing ---------------------------------------------------------

    def _allowed(self, brain) -> bool:
        # local_only ("the phone is the brain") skips the Mac-mini remote tier
        # only — cloud stays an independent choice you can still turn on.
        if self.local_only and getattr(brain, "is_remote", False):
            return False
        # cloud tiers are gated solely by the cloud opt-in, in any mode.
        return self.cloud_opt_in or not getattr(brain, "is_cloud", False)

    def explain(self, frame, label: str,
                want: str = "quick") -> Optional[Answer]:
        """Explain an object from the lowest tier that can answer."""
        for brain in self._vision:
            if not self._allowed(brain):
                continue                      # cloud, not opted in
            ans = self._call_tier(
                brain, lambda b=brain: b.explain(frame, label, want=want),
                "vision")                     # dead tier: skipped AND recorded
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
            ans = self._call_tier(
                brain, lambda b=brain: b.ask(query), "knowledge")
            if ans is not None and not ans.is_empty():
                if not ans.tier:
                    ans.tier = getattr(brain, "tier", "")
                return ans
        return None
