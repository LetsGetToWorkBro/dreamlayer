"""object_lens/label.py — Label Lens: your own facts about a product.

Look at a product, a food, or a menu and it surfaces what *you* know: a
dietary rule you set ("you're avoiding dairy"), whether you've bought or
returned it before, allergens you've logged. All from your own data, on
device — the privacy-safe half of "superhuman shopping."

The *other* half — "cheaper nearby", "reviews mention the battery" — needs
the open web, so it's a separate ShoppingProvider fed by an injected
`shop_fn` (the AI brain's opt-in cloud tier). Off until you turn cloud on.

Both are Object Lens providers, so they drop into the same panel machinery
(and the same World lens).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .providers import PanelProvider
from .schema import PanelRow

# a dietary rule expands to the words that would appear on a label
DIET_GROUPS = {
    "dairy": {"dairy", "milk", "cheese", "butter", "cream", "yogurt",
              "yoghurt", "whey", "lactose", "casein"},
    "gluten": {"gluten", "wheat", "barley", "rye", "malt", "flour"},
    "nuts": {"nut", "nuts", "peanut", "almond", "cashew", "walnut", "pecan"},
    "peanut": {"peanut", "peanuts", "groundnut"},
    "egg": {"egg", "eggs", "albumin"},
    "soy": {"soy", "soya", "soybean", "tofu", "edamame"},
    "shellfish": {"shrimp", "prawn", "crab", "lobster", "shellfish"},
    "meat": {"meat", "beef", "pork", "chicken", "bacon", "ham", "turkey"},
    "sugar": {"sugar", "syrup", "glucose", "fructose", "sucrose"},
}


@dataclass
class DietaryProfile:
    """What you're avoiding. Terms may be group names ('dairy') or literals."""
    avoid: set[str] = field(default_factory=set)

    def hits(self, text: str) -> list[str]:
        t = (text or "").lower()
        found = []
        for rule in self.avoid:
            terms = DIET_GROUPS.get(rule.lower(), {rule.lower()})
            if any(term in t for term in terms):
                found.append(rule)
        return found


class LabelProvider(PanelProvider):
    """Your own facts about a product/food/menu — dietary + purchase history."""
    name = "label"

    def __init__(self, profile: Optional[DietaryProfile] = None,
                 ring=None, lookback: int = 200):
        self.profile = profile or DietaryProfile()
        self.ring = ring
        self.lookback = lookback

    def matches(self, sighting) -> bool:
        return True                           # any product could be relevant

    def _text(self, sighting) -> str:
        attrs = sighting.attributes or {}
        return " ".join(str(x) for x in (
            sighting.label, attrs.get("text", ""), attrs.get("brand", ""),
            attrs.get("ingredients", "")))

    def build(self, sighting, now=None) -> list[PanelRow]:
        rows: list[PanelRow] = []
        for rule in self.profile.hits(self._text(sighting)):
            rows.append(PanelRow(label="⚠ avoiding", detail=rule, kind="info",
                                 source=self.name))
        rows += self._history(sighting)
        return rows

    def _history(self, sighting) -> list[PanelRow]:
        if self.ring is None:
            return []
        key = sighting.key()
        owned = returned = 0
        for b in self.ring.latest(limit=self.lookback):
            ev = b.event
            meta = getattr(ev, "meta", None) or {}
            if meta.get("private"):
                continue
            summary = (getattr(ev, "summary", "") or "").lower()
            if key not in summary and key != str(meta.get("object", "")).lower():
                continue
            if meta.get("returned"):
                returned += 1
            if meta.get("owned") or "bought" in summary:
                owned += 1
        out = []
        if owned:
            out.append(PanelRow(label="you already own this", kind="info",
                                source=self.name))
        if returned:
            out.append(PanelRow(label="you returned this before",
                                detail=(f"{returned}×" if returned > 1 else ""),
                                kind="info", source=self.name))
        return out


class ShoppingProvider(PanelProvider):
    """The open-web half: prices + reviews via an injected shop_fn (the AI
    brain's opt-in cloud tier). Inert until shop_fn is wired — nothing hits
    the web unless you turn cloud on and register this.

    shop_fn(label, attributes) -> {"cheaper": str, "reviews": str, ...}
    """
    name = "shopping"

    def __init__(self, shop_fn: Callable[[str, dict], dict]):
        self._shop = shop_fn

    def matches(self, sighting) -> bool:
        return True

    def build(self, sighting, now=None) -> list[PanelRow]:
        try:
            data = self._shop(sighting.label, sighting.attributes or {}) or {}
        except Exception:
            return []
        rows = []
        if data.get("cheaper"):
            rows.append(PanelRow(label="cheaper nearby", detail=str(data["cheaper"]),
                                 kind="action", source=self.name))
        if data.get("reviews"):
            rows.append(PanelRow(label="reviews", detail=str(data["reviews"]),
                                 kind="info", source=self.name))
        if data.get("rating") is not None:
            rows.append(PanelRow(label="rating", value=str(data["rating"]),
                                 kind="stat", source=self.name))
        return rows
