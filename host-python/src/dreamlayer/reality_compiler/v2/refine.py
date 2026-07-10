"""v2/refine.py — rehearsal refinement (INNOVATION_SESSION 5.3).

The compiler watches how its machines actually run. When a figment keeps getting
banished at the *same* scene, that's not a rejection of the behavior — it's a
tuning note: you always cut this timer short. So the compiler proposes the edit
in rehearsal words — "you end this around 20:00 of 25:00 — shorten it?" — and on
one tap re-signs a *variant* with that scene trimmed. The original stays; the
variant records its lineage (`meta.refined_from`), so the vault keeps the whole
family tree. A behavior that learns from how you quit it.

Nothing here weakens the proof: a refined variant is a brand-new figment that
goes back through `keep()` — budget-verified and freshly signed — before it can
ever deploy.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from .figment import Figment, MIN_SCENE_SEC
from .teach import TeachCard


def _mmss(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def banish_hotspot(history: list[dict], min_banishes: int = 2) -> Optional[dict]:
    """The scene a figment is banished at most, if it clears `min_banishes` and
    is the clear favourite. Returns {scene, count, elapsed} or None. `elapsed`
    is the mean time-into-that-scene at banish when the records carry it."""
    per_scene: dict[str, list] = {}
    for rec in history or []:
        if rec.get("action") != "banish":
            continue
        scene = rec.get("scene")
        if scene is None:
            continue
        per_scene.setdefault(scene, []).append(rec.get("elapsed"))
    if not per_scene:
        return None
    scene, elapseds = max(per_scene.items(), key=lambda kv: len(kv[1]))
    count = len(elapseds)
    if count < min_banishes:
        return None
    known = [e for e in elapseds if isinstance(e, (int, float))]
    return {"scene": scene, "count": count,
            "elapsed": (sum(known) / len(known)) if known else None}


@dataclass
class RefineProposal:
    figment_id: str
    scene: str
    current_sec: float
    suggested_sec: float
    count: int                    # how many times you banished here
    reason: str                   # the human line

    def card(self) -> TeachCard:
        return TeachCard(
            title="TUNE IT?",
            lines=[self.reason],
            suggestion=f'shorten to {_mmss(self.suggested_sec)}',
        )

    def as_dict(self) -> dict:
        return {"figment_id": self.figment_id, "scene": self.scene,
                "current_sec": self.current_sec, "suggested_sec": self.suggested_sec,
                "count": self.count, "reason": self.reason,
                "card": self.card().hud_lines()}


def propose_refinement(fig: Figment, history: list[dict],
                       min_banishes: int = 2) -> Optional[RefineProposal]:
    """Propose shortening the scene a figment is repeatedly quit at. Only for a
    timed scene long enough to be worth trimming; None otherwise."""
    hot = banish_hotspot(history, min_banishes=min_banishes)
    if hot is None:
        return None
    scene = fig.scenes.get(hot["scene"])
    if scene is None or not scene.duration_sec or scene.duration_sec <= MIN_SCENE_SEC:
        return None
    current = float(scene.duration_sec)
    elapsed = hot["elapsed"]
    if elapsed is not None and MIN_SCENE_SEC <= elapsed < current:
        # you keep stopping at ~elapsed — meet you there
        suggested = round(elapsed, 1)
        reason = (f"You end {fig.name} around {_mmss(elapsed)} of "
                  f"{_mmss(current)} — every time.")
    else:
        # no timing captured: fall back to a modest trim
        suggested = max(MIN_SCENE_SEC, round(current * 0.8, 1))
        if suggested >= current:
            return None
        reason = (f"You keep stopping {fig.name} at this scene "
                  f"({hot['count']}×) — shorten it?")
    if current - suggested < 1.0:      # not worth a card for a sub-second trim
        return None
    return RefineProposal(figment_id=fig.id, scene=hot["scene"],
                          current_sec=current, suggested_sec=suggested,
                          count=hot["count"], reason=reason)


def build_variant(fig: Figment, scene_id: str, new_duration_sec: float) -> Figment:
    """A deep copy of `fig` with one scene trimmed, a fresh identity, and the
    lineage recorded. Not signed here — the caller runs it back through keep()
    so budgets are re-proven before it can deploy."""
    variant = Figment.from_dict(fig.to_dict())
    variant.id = uuid.uuid4().hex[:12]            # a new identity for the variant
    scene = variant.scenes.get(scene_id)
    if scene is None:
        raise KeyError(f"no scene {scene_id!r} to refine")
    scene.duration_sec = max(MIN_SCENE_SEC, round(float(new_duration_sec), 1))
    variant.meta = dict(variant.meta or {})
    variant.meta["refined_from"] = fig.id
    variant.meta["refined_scene"] = scene_id
    return variant
