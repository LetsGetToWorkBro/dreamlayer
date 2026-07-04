"""plugins/currency.py — Currency Converter (object-lens + network).

Look at a foreign price tag and see it in your own money, inline on the
look-at-a-thing panel. A vision/OCR upstream tags a sighting with an `amount`
and a `currency`; this provider converts it to your home currency using live
rates (a `network` fetch behind a seam, so it tests offline).

Demonstrates: an object-lens `PanelProvider` + the `network` capability.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Callable, Optional

from dreamlayer.object_lens.providers import PanelProvider
from dreamlayer.object_lens.schema import PanelRow
from dreamlayer.plugins import make_plugin

_SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "AUD": "A$",
           "CAD": "C$", "CHF": "CHF ", "CNY": "¥", "INR": "₹", "MXN": "MX$"}


def convert(amount: float, rate: float) -> float:
    """amount in the foreign currency × rate (home per foreign)."""
    return round(float(amount) * float(rate), 2)


def format_money(amount: float, currency: str) -> str:
    sym = _SYMBOL.get(currency.upper(), currency.upper() + " ")
    return f"{sym}{amount:,.2f}"


def _default_rates_fetch(base: str, quote: str) -> Optional[float]:
    """Live rate `quote` per `base` from a free, no-key endpoint. Returns None
    on any failure — the provider then just shows the original price."""
    if base.upper() == quote.upper():
        return 1.0
    url = (f"https://api.frankfurter.app/latest?from={base.upper()}"
           f"&to={quote.upper()}")
    try:
        with urllib.request.urlopen(url, timeout=4) as resp:      # network cap
            data = json.loads(resp.read().decode("utf-8"))
        return float(data["rates"][quote.upper()])
    except Exception:
        return None


class CurrencyProvider(PanelProvider):
    """Adds a converted-price row when you look at a foreign-currency price."""
    name = "currency"
    facet = "ai"                     # a computed/enriched row, not your own data

    def __init__(self, home: str = "USD",
                 rates_fetch: Optional[Callable[[str, str], Optional[float]]] = None):
        self.home = home.upper()
        self._fetch = rates_fetch or _default_rates_fetch

    def matches(self, sighting) -> bool:
        a = sighting.attributes or {}
        cur = str(a.get("currency", "")).upper()
        return bool(cur) and cur != self.home and a.get("amount") is not None

    def build(self, sighting, now=None) -> list:
        a = sighting.attributes
        cur = str(a["currency"]).upper()
        amount = float(a["amount"])
        rate = self._fetch(cur, self.home)
        if rate is None:
            return [PanelRow(label="≈ your money",
                             detail="rate unavailable — check your connection",
                             kind="info", source="currency")]
        home_amount = convert(amount, rate)
        return [PanelRow(
            label=format_money(home_amount, self.home),
            detail=f"{format_money(amount, cur)} · 1 {cur} = {rate:.3f} {self.home}",
            kind="stat", value=home_amount, source="currency")]


def currency_plugin(home: str = "USD", rates_fetch=None):
    """Register the converter. requires=('object_lens','network')."""
    def register(ctx):
        ctx.add_object_provider(CurrencyProvider(home=home, rates_fetch=rates_fetch))
    return make_plugin("currency-converter", register,
                       requires=("object_lens", "network"), version="0.1.0")
