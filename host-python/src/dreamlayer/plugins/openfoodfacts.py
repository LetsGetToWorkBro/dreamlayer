"""plugins/openfoodfacts.py — a real TasteLens connector.

The showcase of the marketplace: a *shop provider* plugin that gives TasteLens
something to rank against, from a genuine open data source — **Open Food
Facts** (openfoodfacts.org), a free, keyless, community food database. Look at a
shelf and TasteLens now scores each item by its Nutri-Score and flags its
allergens, no account and no vendor lock-in — on-ethos for an open project.

Shape: it registers a `shop_fn(label, attrs) -> {rating, nutriscore, allergens,
brand}` through the plugin API. The HTTP call is a seam (`fetch_fn`) so the
logic tests fully offline; the shipped plugin uses urllib, which is why it
declares `requires=("network",)` — and the validation gate lets the import
through *because* that capability is declared.
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Callable, Optional

from .base import make_plugin

# Nutri-Score grade → a 0–5 rating TasteLens can rank on (A is best).
NUTRISCORE_RATING = {"a": 4.8, "b": 4.0, "c": 3.0, "d": 2.0, "e": 1.0}

SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"


def build_query(label: str) -> str:
    q = urllib.parse.urlencode({
        "search_terms": label or "", "search_simple": 1, "action": "process",
        "json": 1, "page_size": 1,
        "fields": "product_name,nutriscore_grade,brands,allergens_tags",
    })
    return f"{SEARCH_URL}?{q}"


def parse_product(product: dict) -> dict:
    """Map one Open Food Facts product to a shop_fn result. Only fields that
    are present are returned (so a missing grade never fakes a rating)."""
    out: dict = {}
    grade = str((product or {}).get("nutriscore_grade", "")).lower()
    if grade in NUTRISCORE_RATING:
        out["rating"] = NUTRISCORE_RATING[grade]
        out["nutriscore"] = grade.upper()
    allergens = [t.split(":", 1)[-1] for t in (product or {}).get("allergens_tags", []) if t]
    if allergens:
        out["allergens"] = allergens
    brand = (product or {}).get("brands")
    if brand:
        out["brand"] = str(brand).split(",")[0].strip()
    return out


def lookup(label: str, fetch_fn: Callable[[str], object]) -> dict:
    """Query Open Food Facts for `label` and return a shop_fn dict. `fetch_fn`
    takes a URL and returns the JSON body (str or already-parsed dict). Any
    failure yields {} — a connector never breaks a ranking."""
    if not label:
        return {}
    try:
        raw = fetch_fn(build_query(label))
        data = json.loads(raw) if isinstance(raw, (str, bytes)) else (raw or {})
        products = data.get("products") or []
        return parse_product(products[0]) if products else {}
    except Exception:
        return {}


def off_shop_fn(fetch_fn: Callable[[str], object]) -> Callable[[str, dict], dict]:
    """A TasteLens shop provider bound to a fetch function."""
    def shop(label: str, attrs: dict) -> dict:
        return lookup(label, fetch_fn)
    return shop


def _default_fetch(url: str) -> str:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "DreamLayer-TasteLens/0.1"})
    with urllib.request.urlopen(req, timeout=4) as r:      # network capability
        return r.read().decode("utf-8", "replace")


def openfoodfacts_plugin(fetch_fn: Optional[Callable[[str], object]] = None):
    """The plugin. Registers the Open Food Facts shop provider into TasteLens.
    Declares requires=('network',); loaded from a package, it uses urllib."""
    def register(ctx):
        ctx.add_shop_provider(off_shop_fn(fetch_fn or _default_fetch))
    return make_plugin("open-food-facts", register, requires=("network",),
                       version="0.1.0")
