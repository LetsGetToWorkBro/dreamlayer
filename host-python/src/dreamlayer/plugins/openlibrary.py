"""plugins/openlibrary.py — a TasteLens connector for books.

Mirrors `plugins/openfoodfacts.py` structure/error-handling/declaration style
(#199): a *shop provider* plugin that scores books by their community rating
from **Open Library** (openlibrary.org/developers/api), a free, keyless
catalog run by the Internet Archive. Look at a bookshelf and TasteLens ranks
each spine by its Open Library rating — same lens, different shelf.

Shape: it registers a `shop_fn(label, attrs) -> {rating, author,
first_publish_year, editions}` through the plugin API. `label` is either a
title or an ISBN — Open Library's search endpoint auto-detects either, so one
query shape covers both (verified against the live API: `q=<isbn>` and
`q=<title>` both resolve through the same `/search.json` doc list). The HTTP
call is a seam (`fetch_fn`) so the logic tests fully offline; the shipped
plugin uses urllib, which is why it declares `requires=("network",)` — same as
Open Food Facts (`add_shop_provider` grants on `shop` OR `network`; declaring
the actual egress channel is what the OFF precedent does).
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Callable, Optional, cast

SEARCH_URL = "https://openlibrary.org/search.json"
FIELDS = "title,author_name,first_publish_year,edition_count,ratings_average,ratings_count"


def build_query(label: str) -> str:
    q = urllib.parse.urlencode({"q": label or "", "limit": 1, "fields": FIELDS})
    return f"{SEARCH_URL}?{q}"


def parse_book(doc: dict) -> dict:
    """Map one Open Library search doc to a shop_fn result. Only fields that
    are present (and a rating backed by at least one vote) are returned, so a
    book nobody rated never fakes a score."""
    doc = doc or {}
    out: dict = {}
    avg = doc.get("ratings_average")
    count = doc.get("ratings_count") or 0
    if avg is not None and count:
        out["rating"] = round(float(avg), 2)
    authors = doc.get("author_name") or []
    if authors:
        out["author"] = str(authors[0])
    year = doc.get("first_publish_year")
    if year:
        out["first_publish_year"] = int(year)
    editions = doc.get("edition_count")
    if editions:
        out["editions"] = int(editions)
    return out


def lookup(label: str, fetch_fn: Callable[[str], object]) -> dict:
    """Query Open Library for `label` (title or ISBN) and return a shop_fn
    dict. `fetch_fn` takes a URL and returns the JSON body (str or
    already-parsed dict). Any failure — offline, malformed JSON, no match —
    yields {}: a connector never breaks a ranking."""
    if not label:
        return {}
    try:
        raw = fetch_fn(build_query(label))
        data = cast(dict, json.loads(raw) if isinstance(raw, (str, bytes)) else (raw or {}))
        docs = data.get("docs") or []
        return parse_book(docs[0]) if docs else {}
    except Exception:
        return {}


def ol_shop_fn(fetch_fn: Callable[[str], object], ttl: float = 300.0,
               now_fn: Optional[Callable[[], float]] = None) -> Callable[[str, dict], dict]:
    """A TasteLens shop provider bound to a fetch function, with a small
    per-label TTL cache so a shelf of repeats doesn't re-hit the API (Open
    Library asks API clients to be polite). Cache holds even an empty result,
    so a miss isn't retried every glance within the window."""
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
    failures (5xx / connection errors). A descriptive User-Agent is what Open
    Library asks of API clients."""
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


class OpenLibraryPlugin:
    """API v2 plugin (settings). register() adds the Open Library shop
    provider into TasteLens exactly as v1, reading a persisted per-label cache
    TTL from ctx.settings (settings are scoped to this plugin during load).
    requires=('network',); loaded from a package it uses urllib."""
    name = "open-library"
    version = "0.1.0"
    requires = ("network",)

    def __init__(self, fetch_fn: Optional[Callable[[str], object]] = None):
        self._fetch = fetch_fn

    def register(self, ctx):
        ttl = float(ctx.settings.get("cache_ttl", 300.0))
        ctx.add_shop_provider(ol_shop_fn(self._fetch or _default_fetch, ttl=ttl))


def openlibrary_plugin(fetch_fn: Optional[Callable[[str], object]] = None):
    """Open Library connector as an API v2 plugin. requires=('network',)."""
    return OpenLibraryPlugin(fetch_fn=fetch_fn)
