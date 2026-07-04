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
    A descriptive User-Agent is what OFF asks of API clients."""
    import time
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        url, headers={"User-Agent": "DreamLayer-TasteLens/0.1 (+https://dreamlayer.app)"})
    last: Exception = RuntimeError("no attempt")
    for attempt in range(max(1, retries + 1)):
        try:
            with urllib.request.urlopen(req, timeout=4) as r:   # network capability
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500:                      # 4xx won't get better on retry
                raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        if attempt < retries:
            time.sleep(backoff * (2 ** attempt))  # 0.5s, 1.0s
    raise last


def openfoodfacts_plugin(fetch_fn: Optional[Callable[[str], object]] = None):
    """The plugin. Registers the Open Food Facts shop provider into TasteLens.
    Declares requires=('network',); loaded from a package, it uses urllib."""
    def register(ctx):
        ctx.add_shop_provider(off_shop_fn(fetch_fn or _default_fetch))
    return make_plugin("open-food-facts", register, requires=("network",),
                       version="0.1.0")
