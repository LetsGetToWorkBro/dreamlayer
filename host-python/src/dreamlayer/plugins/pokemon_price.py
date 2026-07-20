"""plugins/pokemon_price.py — Pokémon Price (object-lens + network).

Hold up a Pokémon card and the panel names it and tells you what it's worth:
set, number, rarity, and the current market price with a low–high band, inline
on the look-at-a-thing panel. A vision/OCR upstream reads the card and tags a
sighting with a `name` (and, when it can, a `number`/`set`); this provider
resolves it against the **Pokémon TCG API** (pokemontcg.io) and folds the price
facts into the panel.

Concept credit: **WatsonMLDev's pokemon-cost-scraper**
(https://github.com/WatsonMLDev/pokemon-cost-scraper) — the idea of pricing a
card straight from the Halo, and the card-show vendor's workflow this connector
is built around: a vendor eyeballs a card's **condition**, then checks recent
sales to gauge the price *right now*. So this connector:

  * adjusts the market figure for **condition** (NM/LP/MP/HP/DMG — per-card via
    the sighting, or a default you set once), the way a grader knocks a raw
    card's value down off Near-Mint;
  * shows the TCGplayer **low–high band** (the "recent sales" spread) and the
    **as-of date**, so the number is anchored to a moment, not a vibe;
  * flags a **grail** when a card clears your threshold — the panel lights up;
  * keeps a running **haul tally** for the session, so a table of singles adds
    up as you scan it.

The collector's sibling of Vinyl Oracle — an object-lens `PanelProvider` + the
`network` capability, with an optional pokemontcg.io API key persisted in
`ctx.settings` so the wearer authenticates once (the key rides an `X-Api-Key`
header, so it never lands in a URL or a log). The HTTP call is a seam
(`fetch_fn`) so the logic tests fully offline; the shipped plugin uses urllib —
which is why it declares `requires=("object_lens", "network")` and the
validation gate lets the import through *because* those capabilities are
declared.

Honest about its reach: a live demo needs a classifier good enough to read a
card's name off the art — the mock/heuristic classifiers won't, so this rides
whatever real vision backend is wired (YOLO→moondream→CLIP). The pure logic
below, and every test, run with no network and no key. Prices are TCGplayer
market figures (USD, `$`); when a card has none, it falls back to Cardmarket's
trend (EUR, `€`). The condition multipliers are rough raw-card estimates, shown
as `≈`, not a grading appraisal. Nothing about the card's owner ever leaves —
only its printed name.
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Callable, Optional, cast

from dreamlayer.sdk import PanelProvider, PanelRow

from ._egress import no_redirect_opener, read_capped

CARDS_URL = "https://api.pokemontcg.io/v2/cards"

# TCGplayer price variants, most-collectible first; the first present variant
# with a usable figure is the one we surface.
_VARIANTS = ("holofoil", "reverseHolofoil", "1stEditionHolofoil",
             "unlimitedHolofoil", "1stEditionNormal", "normal")

# Rough raw-card condition multipliers off the Near-Mint market price. These
# approximate how vendors discount a played card; they are estimates (shown as
# `≈`), never a grading appraisal. Aliases fold into these five buckets.
CONDITION_MULT = {"nm": 1.0, "lp": 0.85, "mp": 0.70, "hp": 0.55, "dmg": 0.40}
CONDITION_LABEL = {"nm": "NM", "lp": "LP", "mp": "MP", "hp": "HP", "dmg": "DMG"}
_CONDITION_ALIAS = {
    "near mint": "nm", "near_mint": "nm", "mint": "nm", "m": "nm", "nm/m": "nm",
    "lightly played": "lp", "light played": "lp", "lightly_played": "lp",
    "moderately played": "mp", "moderately_played": "mp", "played": "mp",
    "heavily played": "hp", "heavily_played": "hp",
    "damaged": "dmg", "poor": "dmg",
}

# Default "this card is a keeper" threshold, in the price's own currency.
DEFAULT_GRAIL = 100.0


def normalize_condition(condition: Optional[str]) -> str:
    """Fold a free-text/abbreviated condition into one of nm/lp/mp/hp/dmg.
    Unknown or empty → 'nm' (assume Near-Mint, the price-guide baseline)."""
    c = str(condition or "").strip().lower()
    if c in CONDITION_MULT:
        return c
    return _CONDITION_ALIAS.get(c, "nm")


def adjust_for_condition(market: float, condition: str) -> float:
    """Discount a Near-Mint market price for `condition`."""
    return float(market) * CONDITION_MULT.get(normalize_condition(condition), 1.0)


def _lucene(v: str) -> str:
    """Neutralise a value for a quoted Lucene phrase term: drop the double-quote
    and backslash so an OCR read (or a doctored card) containing a `"` can't
    break out of the phrase and steer which card the query resolves. Newlines
    collapse to spaces so the term stays one clause."""
    return v.replace("\\", "").replace('"', "").replace("\n", " ").replace("\r", " ").strip()


def build_query(name: str, number: Optional[str] = None,
                set_id: Optional[str] = None) -> str:
    """A pokemontcg.io card search for `name` (plus `number`/`set_id` when the
    vision read supplies them, which pins the exact printing). We ask for a
    single, newest-first result; the key is never a query param — it rides a
    header — so nothing sensitive lands in the URL. Each term value is
    quote-neutralised so it can't break out of its Lucene phrase clause."""
    terms = []
    nm = _lucene((name or "").strip())
    if nm:
        terms.append(f'name:"{nm}"')
    num = _lucene(("" if number is None else str(number)).strip())
    if num:
        terms.append(f'number:"{num}"')
    sid = _lucene((set_id or "").strip())
    if sid:
        terms.append(f'set.id:"{sid}"')
    params = {"q": " ".join(terms), "pageSize": 1,
              "orderBy": "-set.releaseDate"}
    return f"{CARDS_URL}?{urllib.parse.urlencode(params)}"


def _num(v: object) -> Optional[float]:
    """A price cell → float, or None. The API sends numbers, but a null/blank
    or a stray string must never blow up a panel."""
    try:
        if v is None or v == "":
            return None
        return float(cast(float, v))
    except (TypeError, ValueError):
        return None


def best_price(card: dict) -> dict:
    """The card's headline price. Prefers TCGplayer (USD) — the most-collectible
    variant present, its `market` (falling back to `mid`) plus a `low`/`high`
    band — and falls back to Cardmarket's trend (EUR) when TCGplayer has none.
    Returns {} when there's no usable figure anywhere (never fakes a price)."""
    tcg = ((card or {}).get("tcgplayer") or {}).get("prices") or {}
    for variant in _VARIANTS:
        cell = tcg.get(variant) or {}
        market = _num(cell.get("market"))
        if market is None:
            market = _num(cell.get("mid"))
        if market is None:
            continue
        out: dict = {"market": market, "sym": "$", "variant": variant}
        low, high = _num(cell.get("low")), _num(cell.get("high"))
        if low is not None:
            out["low"] = low
        if high is not None:
            out["high"] = high
        return out
    cm = ((card or {}).get("cardmarket") or {}).get("prices") or {}
    trend = _num(cm.get("trendPrice"))
    if trend is None:
        trend = _num(cm.get("averageSellPrice"))
    if trend is not None:
        return {"market": trend, "sym": "€", "source": "cardmarket"}
    return {}


def parse_card(result: dict) -> dict:
    """Map one pokemontcg.io card to a panel dict. Only fields that are present
    are returned (a missing rarity never fakes one)."""
    out: dict = {}
    r = result or {}
    name = r.get("name")
    if name:
        out["name"] = str(name)
    number = r.get("number")
    if number:
        out["number"] = str(number)
    set_name = (r.get("set") or {}).get("name")
    if set_name:
        out["set"] = str(set_name)
    rarity = r.get("rarity")
    if rarity:
        out["rarity"] = str(rarity)
    updated = (r.get("tcgplayer") or {}).get("updatedAt")
    if updated:
        out["updated"] = str(updated)
    price = best_price(r)
    if price:
        out["price"] = price
    return out


def lookup(name: str, fetch_fn: Callable[[str], object],
           number: Optional[str] = None, set_id: Optional[str] = None) -> dict:
    """Resolve `name` (+ optional `number`/`set_id`) against pokemontcg.io and
    return a card dict. `fetch_fn` takes a URL and returns the JSON body (str or
    parsed dict). Any failure yields {} — a connector never breaks a panel."""
    if not name:
        return {}
    try:
        raw = fetch_fn(build_query(name, number=number, set_id=set_id))
        data = cast(dict, json.loads(raw) if isinstance(raw, (str, bytes)) else (raw or {}))
        results = data.get("data") or []
        return parse_card(results[0]) if results else {}
    except Exception:
        return {}


def _money(value: float, sym: str = "$") -> str:
    """A price as money: `$310`, `$4.75`. Whole numbers drop the cents so the
    panel row stays short; fractional prices keep two places."""
    if float(value).is_integer():
        return f"{sym}{int(value):,}"
    return f"{sym}{value:,.2f}"


def _default_fetch(url: str, api_key: Optional[str] = None,
                   retries: int = 2, backoff: float = 0.5) -> str:
    """The shipped network fetch: urllib with a couple of retries on transient
    failures (5xx / connection errors). The optional pokemontcg.io key rides an
    ``X-Api-Key`` header (lifts the anonymous rate limit) — never a query param,
    so it stays out of URLs and logs.

    Hardened egress (matching the vinyl-oracle/openlibrary siblings) via the
    shared :mod:`plugins._egress` primitives: the read is size-capped
    (response-OOM) and 3xx redirects are refused (SSRF-via-redirect), so egress
    can't leave the pokemontcg.io host ``build_query`` pins."""
    import time
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={
        "User-Agent": "DreamLayer-PokemonPrice/0.1 (+https://dreamlayer.app)",
        "Accept": "application/json"})
    if api_key:
        req.add_header("X-Api-Key", api_key)
    opener = no_redirect_opener()
    last: Exception = RuntimeError("no attempt")
    for attempt in range(max(1, retries + 1)):
        try:
            with opener.open(req, timeout=4) as r:   # network capability, no redirects
                return read_capped(r).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500 and e.code != 429:    # 3xx (refused redirect) / 4xx won't improve
                raise                             # (429 is worth a backoff)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        if attempt < retries:
            time.sleep(backoff * (2 ** attempt))  # 0.5s, 1.0s
    raise last


class PokemonPriceProvider(PanelProvider):
    """Adds a price row when you look at a trading card whose name a vision
    upstream read into `name` (with `number`/`set`/`condition` when it can). A
    per-key TTL cache keeps repeated glances at the same card from re-hitting the
    API, and a session `haul` tally sums the table as you scan it."""
    name = "pokemon-price"
    facet = "ai"                     # a computed/enriched row, not the wearer's data

    # sighting kinds we treat as a Pokémon card; "" (unknown) is allowed so a
    # bare name still resolves.
    _KINDS = frozenset({"", "card", "trading_card", "trading card", "tcg",
                        "pokemon", "pokemon_card", "pokémon"})

    def __init__(self, fetch_fn: Optional[Callable[[str], object]] = None,
                 api_key: Optional[str] = None, ttl: float = 300.0,
                 now_fn: Optional[Callable[[], float]] = None,
                 condition: str = "nm", grail_threshold: float = DEFAULT_GRAIL):
        self.api_key = api_key
        self._fetch = fetch_fn or self._fetch_url
        self._ttl = ttl
        import time
        self._now = now_fn or time.time
        self._cache: dict = {}
        self.condition = normalize_condition(condition)
        self.grail_threshold = float(grail_threshold)
        self._haul: dict = {}        # card key -> counted $ value (dedup by card)

    def _fetch_url(self, url: str) -> str:
        # bound default so a key set later via the plugin is picked up on the
        # next glance (the seam stays injectable for offline tests).
        return _default_fetch(url, api_key=self.api_key)

    def matches(self, sighting) -> bool:
        a = sighting.attributes or {}
        kind = str(a.get("kind", "")).strip().lower()
        return bool(a.get("name")) and kind in self._KINDS

    def _resolve(self, name: str, number: str, set_id: str) -> dict:
        key = (name.strip().lower(), (number or "").strip().lower(),
               (set_id or "").strip().lower())
        hit = self._cache.get(key)
        if hit is not None and (self._now() - hit[0]) < self._ttl:
            return hit[1]
        card = lookup(name, self._fetch, number=number or None,
                      set_id=set_id or None)
        self._cache[key] = (self._now(), card)
        return card

    def session_total(self) -> tuple:
        """(count, summed value) of distinct priced cards seen this session."""
        return (len(self._haul), sum(self._haul.values()))

    def _tally(self, card: dict, value: float, sym: str) -> None:
        # only USD (TCGplayer) figures roll into the haul, so we never sum
        # across currencies; each distinct card counts once at its shown value.
        if sym != "$":
            return
        key = (card.get("name", ""), card.get("number", ""))
        self._haul[key] = value

    def build(self, sighting, now=None) -> list:
        a = sighting.attributes
        name = str(a.get("name", ""))
        number = str(a.get("number", "") or "")
        set_id = str(a.get("set_id", a.get("set", "")) or "")
        card = self._resolve(name, number, set_id)
        if not card:
            return [PanelRow(
                label="Pokémon Price",
                detail="no card found — check your connection or the card read",
                kind="info", source="pokemon-price")]

        # which printing this is
        ctx_bits = []
        if card.get("set"):
            ctx_bits.append(card["set"])
        if card.get("number"):
            ctx_bits.append(f"#{card['number']}")
        if card.get("rarity"):
            ctx_bits.append(card["rarity"])

        price = card.get("price") or {}
        market = price.get("market")
        if market is None:
            detail = " · ".join(ctx_bits + ["price unavailable"]) or "no price"
            return [PanelRow(label=card.get("name") or name, detail=detail,
                             kind="info", source="pokemon-price")]

        sym = price.get("sym", "$")
        condition = normalize_condition(a.get("condition") or self.condition)
        shown = adjust_for_condition(market, condition)

        price_bits = []
        if condition == "nm":
            price_bits.append(f"{_money(market, sym)} market")
        else:                                        # discounted for wear
            price_bits.append(f"≈{_money(shown, sym)} {CONDITION_LABEL[condition]}")
            price_bits.append(f"NM {_money(market, sym)}")
        low, high = price.get("low"), price.get("high")
        if low is not None and high is not None:
            price_bits.append(f"{_money(low, sym)}–{_money(high, sym)}")
        if price.get("variant"):
            price_bits.append(str(price["variant"]))
        if card.get("updated"):
            price_bits.append(f"as of {card['updated']}")

        label = card.get("name") or name
        grail = shown >= self.grail_threshold
        if grail:                                    # the panel lights up
            label = f"🔥 {label}"
            ctx_bits = ["GRAIL"] + ctx_bits

        rows = [PanelRow(label=label, detail=" · ".join(price_bits + ctx_bits),
                         kind="stat", source="pokemon-price")]

        # running haul: once you've scanned a couple, sum the table
        self._tally(card, shown, sym)
        count, total = self.session_total()
        if count >= 2:
            rows.append(PanelRow(
                label="haul", value=_money(total, "$"),
                detail=f"{count} cards this session", kind="stat",
                source="pokemon-price"))
        return rows


class PokemonPricePlugin:
    """API v2 plugin (lifecycle + settings). register() wires the object
    provider; start() restores the wearer's pokemontcg.io key, default
    condition, and grail threshold from ctx.settings, and the setters persist
    new ones — so the price desk follows you across sessions.
    requires=('object_lens','network')."""
    name = "pokemon-price"
    version = "0.1.0"
    requires = ("object_lens", "network")

    def __init__(self, fetch_fn: Optional[Callable[[str], object]] = None,
                 api_key: Optional[str] = None):
        self._fetch = fetch_fn
        self._default_key = api_key
        self.provider: Optional[PokemonPriceProvider] = None
        self._settings = None            # name-bound settings (captured in register)

    def register(self, ctx):
        self._settings = ctx.settings
        ttl = float(ctx.settings.get("cache_ttl", 300.0))
        condition = str(ctx.settings.get("condition", "nm"))
        grail = float(ctx.settings.get("grail_threshold", DEFAULT_GRAIL))
        self.provider = PokemonPriceProvider(
            fetch_fn=self._fetch, api_key=self._default_key, ttl=ttl,
            condition=condition, grail_threshold=grail)
        ctx.add_object_provider(self.provider)

    def start(self, ctx):
        if self.provider is None:
            return
        key = self._get("pokemontcg_api_key", self._default_key)
        if key:
            self.provider.api_key = str(key)
        self.provider.condition = normalize_condition(
            self._get("condition", self.provider.condition))
        self.provider.grail_threshold = float(
            self._get("grail_threshold", self.provider.grail_threshold))

    def _get(self, key, default):
        return self._settings.get(key, default) if self._settings else default

    def set_api_key(self, api_key: str) -> None:
        """Set (and persist) the pokemontcg.io API key."""
        if self.provider is not None:
            self.provider.api_key = str(api_key)
        if self._settings is not None:
            self._settings.set("pokemontcg_api_key", str(api_key))

    def set_condition(self, condition: str) -> None:
        """Set (and persist) the default card condition (nm/lp/mp/hp/dmg)."""
        c = normalize_condition(condition)
        if self.provider is not None:
            self.provider.condition = c
        if self._settings is not None:
            self._settings.set("condition", c)

    def set_grail_threshold(self, amount: float) -> None:
        """Set (and persist) the value at which a card is flagged a grail."""
        v = float(amount)
        if self.provider is not None:
            self.provider.grail_threshold = v
        if self._settings is not None:
            self._settings.set("grail_threshold", v)


def pokemon_price_plugin(fetch_fn: Optional[Callable[[str], object]] = None,
                         api_key: Optional[str] = None):
    """The Pokémon Price desk as an API v2 plugin (lifecycle + settings).
    requires=('object_lens','network')."""
    return PokemonPricePlugin(fetch_fn=fetch_fn, api_key=api_key)
