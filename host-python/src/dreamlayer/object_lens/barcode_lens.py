"""object_lens/barcode_lens.py — the Barcode → Nutrition lens.

When the recognizer decodes a product barcode (barcode_backends.py, attached as
`attributes["barcode"]`), this provider looks it up on Open Food Facts and vets
it against *your* DietaryProfile: it surfaces the Nutri-Score, what the product
contains, and — the point — a plain "you avoid dairy — milk" when an allergen
you set matches. Your dietary rules never leave the device; only the numeric
barcode is sent, and only when the egress shield is down.

The provider is pure: it takes an injected `lookup_fn(barcode) -> product dict`
(the composition root wires the Open Food Facts connector's `off_barcode_fn`)
and an `allow_network()` gate, so it tests fully offline and honors the Veil the
same way the taste read does.
"""
from __future__ import annotations

from typing import Callable, Optional

from .label import DietaryProfile
from .providers import PanelProvider
from .schema import PanelRow


class BarcodeFoodProvider(PanelProvider):
    """Barcode → Open Food Facts → your dietary rules. Emits nothing until a
    barcode is present AND the network is allowed (Veil down)."""

    name = "barcode"
    facet = "shop"

    def __init__(self, profile: Optional[DietaryProfile] = None,
                 lookup_fn: Optional[Callable[[str], dict]] = None,
                 allow_network: Optional[Callable[[], bool]] = None):
        self.profile = profile or DietaryProfile()
        self._lookup = lookup_fn
        # fail CLOSED by default: no gate wired → no egress. A caller that wants
        # the permissive posture must pass one explicitly (matches the project's
        # NullGate/requires_capture convention; audit 2026-07-21).
        self._allow = allow_network or (lambda: False)

    def matches(self, sighting) -> bool:
        return bool((sighting.attributes or {}).get("barcode"))

    def _allowed(self) -> bool:
        # fail CLOSED: a gate that raises means "don't send" (a decoded barcode
        # is still a network lookup, and silence is not permission)
        try:
            return bool(self._allow())
        except Exception:                              # noqa: BLE001
            return False

    def build(self, sighting, now=None) -> list[PanelRow]:
        code = str((sighting.attributes or {}).get("barcode") or "").strip()
        if not code or self._lookup is None:
            return []
        if not self._allowed():
            return []                                  # Veil up → no egress, stay quiet
        try:
            product = self._lookup(code) or {}
        except Exception:                              # noqa: BLE001 — a connector never breaks a look
            return []
        if not product:
            return []
        rows: list[PanelRow] = []
        name = product.get("product_name")
        if name:
            rows.append(PanelRow(label=str(name), kind="info", source=self.name))
        if product.get("nutriscore"):
            rows.append(PanelRow(label="Nutri-Score", value=str(product["nutriscore"]),
                                 kind="stat", source=self.name))
        allergens = [str(a) for a in (product.get("allergens") or []) if a]
        if allergens:
            rows.append(PanelRow(label="contains", detail=", ".join(allergens[:6]),
                                 kind="info", source=self.name))
        # the point: vet the product's allergens + ingredients against YOUR rules
        haystack = " ".join(allergens + [str(product.get("ingredients", ""))])
        for rule in self.profile.hits(haystack):
            rows.append(PanelRow(label="⚠ you avoid", detail=rule, kind="action",
                                 source=self.name))
        return rows
