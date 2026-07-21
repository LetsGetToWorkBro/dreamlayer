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
from typing import Callable, Optional, cast

from ._egress import no_redirect_opener, read_capped

# Nutri-Score grade → a 0–5 rating TasteLens can rank on (A is best).
NUTRISCORE_RATING = {"a": 4.8, "b": 4.0, "c": 3.0, "d": 2.0, "e": 1.0}

SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
# Product-by-barcode endpoint (same pinned host as SEARCH_URL, so the
# no_redirect_opener host-pin still holds). v2 lets us ask for just the fields
# we surface, keeping the reply small.
PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product"

_BARCODE_RE = __import__("re").compile(r"\D")


def build_query(label: str) -> str:
    q = urllib.parse.urlencode({
        "search_terms": label or "", "search_simple": 1, "action": "process",
        "json": 1, "page_size": 1,
        "fields": "product_name,nutriscore_grade,brands,allergens_tags",
    })
    return f"{SEARCH_URL}?{q}"


def build_barcode_query(code: str) -> str:
    """The product-by-code URL for a decoded barcode. `code` is sanitized to
    digits — a barcode is numeric, and this keeps a decoder glitch from
    building a URL with path-traversal or query junk in it."""
    digits = _BARCODE_RE.sub("", code or "")
    fields = "product_name,nutriscore_grade,brands,allergens_tags,ingredients_text"
    q = urllib.parse.urlencode({"fields": fields})
    return f"{PRODUCT_URL}/{digits}.json?{q}"


def lookup_by_barcode(code: str, fetch_fn: Callable[[str], object]) -> dict:
    """Resolve a decoded barcode to a product dict (nutriscore/allergens/brand/
    ingredients/name), or {} on any miss/failure — a lens never breaks on a bad
    scan. Adds `ingredients` and `product_name` on top of parse_product so the
    dietary check has ingredient text to match, not just the allergen tags."""
    digits = _BARCODE_RE.sub("", code or "")
    if not (8 <= len(digits) <= 14):                  # not a product GTIN
        return {}
    try:
        raw = fetch_fn(build_barcode_query(digits))
        data = cast(dict, json.loads(raw) if isinstance(raw, (str, bytes)) else (raw or {}))
        if int(data.get("status", 0)) != 1:           # OFF: 1 = found, 0 = unknown
            return {}
        product = data.get("product") or {}
        out = parse_product(product)
        ing = str(product.get("ingredients_text", "") or "").strip()
        if ing:
            out["ingredients"] = ing[:300]
        name = str(product.get("product_name", "") or "").strip()
        if name:
            out["product_name"] = name[:80]
        return out
    except Exception:
        return {}


def off_barcode_fn(fetch_fn: Callable[[str], object], ttl: float = 600.0,
                   now_fn: Optional[Callable[[], float]] = None) -> Callable[[str], dict]:
    """A cached `lookup(barcode) -> product dict` bound to a fetch function.
    Keyed on the sanitized digits (an exact, ideal cache key), caching even a
    miss so a repeated glance at the same item doesn't re-hit the API."""
    import time
    now = now_fn or time.time
    cache: dict = {}

    def lookup_fn(code: str) -> dict:
        key = _BARCODE_RE.sub("", code or "")
        hit = cache.get(key)
        if hit is not None and (now() - hit[0]) < ttl:
            return hit[1]
        result = lookup_by_barcode(key, fetch_fn)
        cache[key] = (now(), result)
        return result

    return lookup_fn


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
        data = cast(dict, json.loads(raw) if isinstance(raw, (str, bytes)) else (raw or {}))
        products = data.get("products") or []
        return parse_product(products[0]) if products else {}
    except Exception:
        return {}


def off_shop_fn(fetch_fn: Callable[[str], object], ttl: float = 300.0,
                now_fn: Optional[Callable[[], float]] = None) -> Callable[[str, dict], dict]:
    """A TasteLens shop provider bound to a fetch function, with a small
    per-label TTL cache so a shelf of repeats — and repeated glances at the same
    shelf — don't re-hit the API (Open Food Facts rate-limits; this is the
    polite, fast path). Cache holds even an empty result, so a miss isn't
    retried every glance within the window."""
    import time
    now = now_fn or time.time
    cache: dict = {}
    def shop(label: str, attrs: dict) -> dict:
        key = (label or "").strip().lower()
        hit = cache.get(key)
        if hit is not None and (now() - hit[0]) < ttl:
            return hit[1]
        result = lookup(label, fetch_fn)
        cache[key] = (now(), result)
        return result
    return shop


def _default_fetch(url: str, retries: int = 2, backoff: float = 0.5) -> str:
    """The shipped network fetch: urllib with a couple of retries on transient
    failures (5xx / connection errors), since Open Food Facts 503s under load.
    A descriptive User-Agent is what OFF asks of API clients.

    Hardened egress (audit 2026-07-17) via the shared :mod:`plugins._egress`
    primitives: the read is size-capped (response-OOM) and 3xx redirects are
    refused (SSRF-via-redirect), so egress can't leave the OFF host build_query
    pins — matching the openlibrary sibling."""
    import time
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        url, headers={"User-Agent": "DreamLayer-TasteLens/0.1 (+https://dreamlayer.app)"})
    opener = no_redirect_opener()
    last: Exception = RuntimeError("no attempt")
    for attempt in range(max(1, retries + 1)):
        try:
            with opener.open(req, timeout=4) as r:   # network capability, no redirects
                return read_capped(r).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500:                      # 3xx (refused redirect) / 4xx won't improve
                raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        if attempt < retries:
            time.sleep(backoff * (2 ** attempt))  # 0.5s, 1.0s
    raise last


class OpenFoodFactsPlugin:
    """API v2 plugin (settings). register() adds the Open Food Facts shop
    provider into TasteLens exactly as v1, reading a persisted per-label cache
    TTL from ctx.settings (settings are scoped to this plugin during load), so a
    wearer can trade freshness for fewer API hits. requires=('network',); loaded
    from a package it uses urllib."""
    name = "open-food-facts"
    version = "0.1.0"
    requires = ("network",)

    def __init__(self, fetch_fn: Optional[Callable[[str], object]] = None):
        self._fetch = fetch_fn

    def register(self, ctx):
        ttl = float(ctx.settings.get("cache_ttl", 300.0))
        ctx.add_shop_provider(off_shop_fn(self._fetch or _default_fetch, ttl=ttl))


def openfoodfacts_plugin(fetch_fn: Optional[Callable[[str], object]] = None):
    """Open Food Facts connector as an API v2 plugin. requires=('network',)."""
    return OpenFoodFactsPlugin(fetch_fn=fetch_fn)
