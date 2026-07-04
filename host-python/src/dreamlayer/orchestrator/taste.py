"""orchestrator/taste.py — TasteLens: the real-world choice oracle.

Look at a whole shelf or a menu and get a **ranked comparison against your
rules** — dietary vetoes first, then your budget, then quality (rating) and
price, tuned by what you've liked before. Label Lens grown up: it stops telling
you facts about *one* thing and starts telling you *which to pick* among many.

The decomposition (docs/PLATFORM.md):

  - **The lens is a first-party feature.** It owns the read (multi-object), the
    ranking, and the card. Your dietary rules stay local; the Veil gates it.
  - **The data it ranks against is pluggable.** `shop_fn(label, attrs) ->
    {rating, price, ...}` is the seam a price/review provider plugs into — a
    plugin, off by default, on the opt-in cloud tier. Same shape as Label
    Lens's ShoppingProvider.

Two seams keep it testable offline and hardware-ready:
  read_fn(frame) -> [TasteItem]   the multi-object read (NPU coarse + Brain fine)
  shop_fn(label, attrs) -> dict   ratings/prices from a shop plugin (opt-in)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class TasteItem:
    """One thing on the shelf/menu. `text` carries anything a dietary rule
    might match (ingredients, description); price/rating may come from the read
    or be filled by a shop plugin."""
    label: str
    text: str = ""
    price: Optional[float] = None
    rating: Optional[float] = None
    attributes: dict = field(default_factory=dict)

    def blob(self) -> str:
        parts = [self.label, self.text,
                 str(self.attributes.get("ingredients", "")),
                 str(self.attributes.get("brand", ""))]
        return " ".join(p for p in parts if p)


@dataclass
class RankedItem:
    label: str
    score: float
    reasons: list
    ok: bool                     # eligible (not vetoed, within budget)
    price: Optional[float] = None
    rating: Optional[float] = None


@dataclass
class TasteRanking:
    items: list                  # RankedItem, best first
    scene: str = "shelf"
    unavailable: bool = False

    @property
    def winner(self) -> Optional[RankedItem]:
        for it in self.items:
            if it.ok:
                return it
        return None


class TasteLens:
    def __init__(self, read_fn: Optional[Callable] = None,
                 shop_fn: Optional[Callable] = None,
                 profile=None, budget: Optional[float] = None):
        self._read = read_fn
        self._shop = shop_fn
        self.profile = profile          # a DietaryProfile (or None)
        self.budget = budget

    # -- the read -------------------------------------------------------------

    def read(self, frame) -> list:
        if self._read is None:
            return []
        try:
            items = self._read(frame) or []
        except Exception:
            return []
        return [it for it in items if isinstance(it, TasteItem)]

    # -- the pure ranking (fully testable offline) ---------------------------

    def rank(self, items, profile=None, budget=None) -> list:
        prof = profile if profile is not None else self.profile
        bud = budget if budget is not None else self.budget
        scored = []
        for it in items:
            rating, price = it.rating, it.price
            if self._shop is not None and (rating is None or price is None):
                try:
                    data = self._shop(it.label, it.attributes) or {}
                except Exception:
                    data = {}
                rating = rating if rating is not None else data.get("rating")
                price = price if price is not None else data.get("price")
            reasons: list = []
            avoid = prof.hits(it.blob()) if prof is not None else []
            vetoed = bool(avoid)
            if vetoed:
                reasons.append("avoid: " + ", ".join(avoid))
            over = bud is not None and price is not None and price > bud
            if over:
                reasons.append(f"over ${bud:g}")
            score = 0.0
            if rating is not None:
                score += float(rating) / 5.0
                reasons.append(f"{_g(rating)}★")
            if price is not None:
                reasons.append(f"${_g(price)}")
            scored.append(_Scored(it.label, score, list(reasons), price, rating,
                                  vetoed, over))
        # cheaper is a light tiebreak, normalised across the set — never enough
        # to overturn a full rating point (which is worth 0.2), so quality leads
        # and price only settles near-ties.
        prices = [s.price for s in scored if s.price is not None]
        if prices:
            pmax, pmin = max(prices), min(prices)
            span = (pmax - pmin) or 1.0
            for s in scored:
                if s.price is not None:
                    s.score += 0.1 * (pmax - s.price) / span
        scored.sort(key=lambda s: (s.tier(), -s.score, s.label))
        return [RankedItem(label=s.label, score=round(s.score, 3),
                           reasons=s.reasons, ok=(not s.vetoed and not s.over),
                           price=s.price, rating=s.rating) for s in scored]

    # -- the whole look -------------------------------------------------------

    def look(self, frame, profile=None, budget=None,
             scene: str = "shelf") -> TasteRanking:
        items = self.read(frame)
        if not items:
            return TasteRanking(items=[], scene=scene, unavailable=True)
        return TasteRanking(items=self.rank(items, profile, budget), scene=scene)


def _g(x) -> str:
    return f"{float(x):g}"


@dataclass
class _Scored:
    label: str
    score: float
    reasons: list
    price: Optional[float]
    rating: Optional[float]
    vetoed: bool
    over: bool

    def tier(self) -> int:
        # eligible (0) beats over-budget (1) beats vetoed (2), always
        return 2 if self.vetoed else (1 if self.over else 0)
