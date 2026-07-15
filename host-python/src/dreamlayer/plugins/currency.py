"""plugins/currency.py — Currency Converter (object-lens + network).

Look at a foreign price tag and see it in your own money, inline on the
look-at-a-thing panel. A vision/OCR upstream tags a sighting with an `amount`
and a `currency`; this provider converts it to your home currency using live
rates (a `network` fetch behind a seam, so it tests offline).

Demonstrates: an object-lens `PanelProvider` + the `network` capability, and
(API v2) a persisted `home` currency the wearer can set once and keep.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Callable, Optional

from dreamlayer.sdk import PanelProvider, PanelRow

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
            kind="stat", value=str(home_amount), source="currency")]


class CurrencyPlugin:
    """API v2 plugin (lifecycle + settings). register() wires the converter
    exactly as v1; start() restores the wearer's chosen home currency from
    ctx.settings, and set_home() persists a new one — so "your money" follows
    you across sessions. Dogfoods per-plugin settings first-party."""
    name = "currency-converter"
    version = "0.1.0"
    requires = ("object_lens", "network")

    def __init__(self, home: str = "USD", rates_fetch=None):
        self._default_home = home.upper()
        self._rates_fetch = rates_fetch
        self.provider: Optional[CurrencyProvider] = None
        self._settings = None            # name-bound settings (captured in register)

    def register(self, ctx):
        # ctx.settings is scoped to this plugin during load; capture the bound
        # handle so setters called later (by the host, outside a lifecycle
        # callback) still write to *this* plugin's bucket.
        self._settings = ctx.settings
        self.provider = CurrencyProvider(home=self._default_home,
                                         rates_fetch=self._rates_fetch)
        ctx.add_object_provider(self.provider)

    def start(self, ctx):
        # restore the wearer's saved home currency (falls back to the default)
        home = str(self._get("home", self._default_home)).upper()
        if self.provider is not None:
            self.provider.home = home

    def _get(self, key, default):
        return self._settings.get(key, default) if self._settings else default

    def set_home(self, code: str) -> None:
        """Set (and persist) the home currency the panel converts to."""
        code = str(code).upper()
        if self.provider is not None:
            self.provider.home = code
        if self._settings is not None:
            self._settings.set("home", code)


def currency_plugin(home: str = "USD", rates_fetch=None):
    """The Currency Converter as an API v2 plugin (lifecycle + settings).
    requires=('object_lens','network')."""
    return CurrencyPlugin(home=home, rates_fetch=rates_fetch)
