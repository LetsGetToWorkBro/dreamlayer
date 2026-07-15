"""plugins/vinyl_oracle.py — Vinyl Oracle (object-lens + network).

Hold up a record and the crate speaks: press year, label, country, and how
sought-after the pressing is — inline on the look-at-a-thing panel. A
vision/OCR upstream reads the sleeve and tags a sighting with an `artist` and a
`title`; this provider resolves it against **Discogs** (discogs.com), the
community vinyl database, and folds the release facts into the panel.

The showcase of a *collector's lens* built on the marketplace: an object-lens
`PanelProvider` + the `network` capability, with a Discogs token persisted in
`ctx.settings` (API v2) so the wearer authenticates once. The HTTP call is a
seam (`fetch_fn`) so the logic tests fully offline; the shipped plugin uses
urllib — which is why it declares `requires=("object_lens", "network")` and the
validation gate lets the import through *because* those capabilities are
declared.

Honest about its reach: a live demo needs (1) a classifier good enough to read
artist+title off a sleeve — the mock/heuristic classifiers won't, so this rides
whatever real vision backend is wired (YOLO→moondream→CLIP) — and (2) a Discogs
personal-access token for anything past the anonymous rate limit. The pure
logic below, and every test, run with neither.
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Callable, Optional, cast

from dreamlayer.sdk import PanelProvider, PanelRow

SEARCH_URL = "https://api.discogs.com/database/search"

# Discogs pressing formats we surface a short badge for; anything else passes
# through verbatim.
_FORMAT_HINT = {"Vinyl": "vinyl", "LP": "LP", "7\"": "7″", "12\"": "12″",
                "CD": "CD", "Cassette": "tape"}


def build_query(artist: str, title: str, token: Optional[str] = None) -> str:
    """A Discogs release search for `artist`/`title`. A token, when present,
    lifts the anonymous rate limit; it's a query param, never logged by us."""
    params = {
        "artist": (artist or "").strip(),
        "release_title": (title or "").strip(),
        "type": "release",
        "per_page": 1,
    }
    if token:
        params["token"] = token
    return f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"


def _sought_after(community: dict) -> Optional[str]:
    """want/have as a one-word collectibility read — the crate-digger's signal.
    Returns None unless there's enough of a community to mean anything."""
    want = int((community or {}).get("want", 0) or 0)
    have = int((community or {}).get("have", 0) or 0)
    if have < 5:
        return None
    ratio = want / have
    if ratio >= 1.0:
        return "grail"          # more want it than have it
    if ratio >= 0.4:
        return "sought-after"
    return "common"


def parse_release(result: dict) -> dict:
    """Map one Discogs search result to a panel dict. Only fields that are
    present are returned (a missing year never fakes a date)."""
    out: dict = {}
    r = result or {}
    title = r.get("title")
    if title:
        out["title"] = str(title)
    year = r.get("year")
    if year:
        out["year"] = str(year)
    labels = [str(x) for x in (r.get("label") or []) if x]
    if labels:
        out["label"] = labels[0]                       # the pressing's label
    country = r.get("country")
    if country:
        out["country"] = str(country)
    fmts = [str(x) for x in (r.get("format") or []) if x]
    if fmts:
        out["format"] = [_FORMAT_HINT.get(f, f) for f in fmts]
    tag = _sought_after(r.get("community") or {})
    if tag:
        out["collectibility"] = tag
    return out


def lookup(artist: str, title: str, fetch_fn: Callable[[str], object],
           token: Optional[str] = None) -> dict:
    """Resolve `artist`/`title` against Discogs and return a release dict.
    `fetch_fn` takes a URL and returns the JSON body (str or parsed dict). Any
    failure yields {} — a connector never breaks a panel."""
    if not (artist or title):
        return {}
    try:
        raw = fetch_fn(build_query(artist, title, token=token))
        data = cast(dict, json.loads(raw) if isinstance(raw, (str, bytes)) else (raw or {}))
        results = data.get("results") or []
        return parse_release(results[0]) if results else {}
    except Exception:
        return {}


def _default_fetch(url: str, retries: int = 2, backoff: float = 0.5) -> str:
    """The shipped network fetch: urllib with a couple of retries on transient
    failures (5xx / connection errors). Discogs *requires* a descriptive
    User-Agent and 429s aggressive clients, so this backs off politely."""
    import time
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        url, headers={"User-Agent": "DreamLayer-VinylOracle/0.1 (+https://dreamlayer.app)"})
    last: Exception = RuntimeError("no attempt")
    for attempt in range(max(1, retries + 1)):
        try:
            with urllib.request.urlopen(req, timeout=4) as r:   # network capability
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500 and e.code != 429:    # 4xx won't get better on retry
                raise                             # (429 is worth a backoff)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        if attempt < retries:
            time.sleep(backoff * (2 ** attempt))  # 0.5s, 1.0s
    raise last


class VinylOracleProvider(PanelProvider):
    """Adds a pressing-facts row when you look at a record whose sleeve a vision
    upstream read into `artist`/`title`. A per-key TTL cache keeps repeated
    glances at the same crate from re-hitting Discogs."""
    name = "vinyl-oracle"
    facet = "ai"                     # a computed/enriched row, not the wearer's data

    def __init__(self, fetch_fn: Optional[Callable[[str], object]] = None,
                 token: Optional[str] = None, ttl: float = 300.0,
                 now_fn: Optional[Callable[[], float]] = None):
        self._fetch = fetch_fn or _default_fetch
        self.token = token
        self._ttl = ttl
        import time
        self._now = now_fn or time.time
        self._cache: dict = {}

    def matches(self, sighting) -> bool:
        a = sighting.attributes or {}
        # a record needs at least a title; artist alone is too broad to press
        return bool(a.get("title")) and str(a.get("kind", "record")).lower() in (
            "record", "vinyl", "album", "lp", "record", "")

    def _resolve(self, artist: str, title: str) -> dict:
        key = (artist.strip().lower(), title.strip().lower())
        hit = self._cache.get(key)
        if hit is not None and (self._now() - hit[0]) < self._ttl:
            return hit[1]
        rel = lookup(artist, title, self._fetch, token=self.token)
        self._cache[key] = (self._now(), rel)
        return rel

    def build(self, sighting, now=None) -> list:
        a = sighting.attributes
        artist = str(a.get("artist", ""))
        title = str(a.get("title", ""))
        rel = self._resolve(artist, title)
        if not rel:
            return [PanelRow(label="Vinyl Oracle",
                             detail="no pressing found — check your connection or the sleeve read",
                             kind="info", source="vinyl-oracle")]
        # headline: what pressing this is
        head_bits = [b for b in (rel.get("year"), rel.get("label"),
                                 rel.get("country")) if b]
        detail_bits = []
        if rel.get("format"):
            detail_bits.append(" · ".join(rel["format"]))
        if rel.get("collectibility"):
            detail_bits.append(rel["collectibility"])
        return [PanelRow(
            label=rel.get("title") or f"{artist} — {title}".strip(" —"),
            detail=" · ".join(head_bits + detail_bits) or "release found",
            kind="stat", source="vinyl-oracle")]


class VinylOraclePlugin:
    """API v2 plugin (lifecycle + settings). register() wires the object
    provider; start() restores the wearer's Discogs token from ctx.settings,
    and set_token() persists a new one — so the crate follows you across
    sessions. requires=('object_lens','network')."""
    name = "vinyl-oracle"
    version = "0.1.0"
    requires = ("object_lens", "network")

    def __init__(self, fetch_fn: Optional[Callable[[str], object]] = None,
                 token: Optional[str] = None):
        self._fetch = fetch_fn
        self._default_token = token
        self.provider: Optional[VinylOracleProvider] = None
        self._settings = None            # name-bound settings (captured in register)

    def register(self, ctx):
        # capture the bound settings handle so setters called later (outside a
        # lifecycle callback) still write to *this* plugin's bucket.
        self._settings = ctx.settings
        ttl = float(ctx.settings.get("cache_ttl", 300.0))
        self.provider = VinylOracleProvider(
            fetch_fn=self._fetch, token=self._default_token, ttl=ttl)
        ctx.add_object_provider(self.provider)

    def start(self, ctx):
        # restore the wearer's saved token (falls back to the constructor's)
        token = self._get("discogs_token", self._default_token)
        if self.provider is not None and token:
            self.provider.token = str(token)

    def _get(self, key, default):
        return self._settings.get(key, default) if self._settings else default

    def set_token(self, token: str) -> None:
        """Set (and persist) the Discogs personal-access token."""
        if self.provider is not None:
            self.provider.token = str(token)
        if self._settings is not None:
            self._settings.set("discogs_token", str(token))


def vinyl_oracle_plugin(fetch_fn: Optional[Callable[[str], object]] = None,
                        token: Optional[str] = None):
    """The Vinyl Oracle as an API v2 plugin (lifecycle + settings).
    requires=('object_lens','network')."""
    return VinylOraclePlugin(fetch_fn=fetch_fn, token=token)
