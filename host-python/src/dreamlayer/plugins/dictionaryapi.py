"""plugins/dictionaryapi.py — a keyless definition connector for Lexicon.

Mirrors `plugins/openlibrary.py` structure/error-handling/declaration style: a
thin connector over ONE pinned public API host — **dictionaryapi.dev**
(api.dictionaryapi.dev, free, no key) — whose HTTP call is a seam (`fetch_fn`)
so the logic tests run fully offline, and whose shipped fetch uses the hardened
egress primitives from :mod:`plugins._egress` (`no_redirect_opener`,
`read_capped`) rather than a bare `urllib.request.urlopen`.

Shape: `define_fn(fetch_fn)` returns `define(word) -> {word, sense,
part_of_speech}` with a small per-word TTL cache, the same shape `ol_shop_fn`
gives TasteLens. Any failure — offline, 404 "No Definitions Found", malformed
JSON, a hostile body — yields `{}`: a connector never breaks its caller.

WHAT MAY BE SENT, ENFORCED HERE AND NOT ONLY AT THE CALLER
----------------------------------------------------------
The Lexicon contract is "ship ONLY the single word, never the utterance", and
:func:`build_query` is where that becomes a guarantee rather than a convention.
It refuses anything that is not a single lowercase alphabetic token — no
spaces, no digits, no punctuation — so no code path through this module can
put a transcribed sentence, a phone number or a name-with-initials on the wire,
however its caller is later rewired. The caller (`ai_brain/server/lexicon_live.py`)
also only ever passes a word it took from the PII-redacted text; this refusal
is the second lock on the same door, because the egress mistake this feature
could make is the one it must never make.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from typing import Callable, Optional, cast

from ._egress import no_redirect_opener, read_capped

ENTRIES_URL = "https://api.dictionaryapi.dev/api/v2/entries/en"

#: The ONLY thing this connector will put on the wire: one lowercase alphabetic
#: word. See the module docstring — this is an egress guarantee, not a tidiness
#: check, so it is enforced in `build_query` rather than trusted to callers.
_WORD_RE = re.compile(r"\A[a-z]{2,40}\Z")

# A single dictionaryapi.dev entry is a few KB; cap the read so a hostile or
# MITM'd reply can't stream an unbounded body into memory (response-OOM). Kept
# as a module global (not the _egress default) so tests can monkeypatch it, the
# same way `openlibrary._MAX_RESPONSE_BYTES` is.
_MAX_RESPONSE_BYTES = 256 * 1024


def build_query(word: str) -> str:
    """The entries URL for one word, or raise ``ValueError``.

    ``word`` is quoted into the PATH (that is the endpoint's shape), and quoting
    alone would not be enough: percent-encoding a whole utterance still SENDS
    the whole utterance. So the shape is refused outright instead.
    """
    w = (word or "").strip().lower()
    if not _WORD_RE.match(w):
        raise ValueError("dictionaryapi: only a single alphabetic word may be sent")
    return f"{ENTRIES_URL}/{urllib.parse.quote(w, safe='')}"


def parse_entry(data) -> dict:
    """Map a dictionaryapi.dev reply to `{word, sense, part_of_speech}`.

    The reply is a LIST of entries, each with `meanings`, each with
    `definitions`. Only the first definition that is a non-empty string is
    taken — a one-line card has room for one sense, and picking the first is
    the same "most common first" ordering the API already returns.

    Everything is treated as untrusted: the payload comes off the network, so a
    non-list, a missing key, a nested null or a number where a string belongs
    yields `{}` rather than an exception or a card built out of `None`.
    """
    if not isinstance(data, list):
        return {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        word = entry.get("word")
        for meaning in entry.get("meanings") or []:
            if not isinstance(meaning, dict):
                continue
            pos = meaning.get("partOfSpeech")
            for definition in meaning.get("definitions") or []:
                if not isinstance(definition, dict):
                    continue
                sense = definition.get("definition")
                if isinstance(sense, str) and sense.strip():
                    return {
                        "word": str(word).strip() if isinstance(word, str) else "",
                        "sense": " ".join(sense.split()),
                        "part_of_speech": (str(pos).strip()
                                           if isinstance(pos, str) else ""),
                    }
    return {}


def lookup(word: str, fetch_fn: Callable[[str], object]) -> dict:
    """Define `word` and return `{word, sense, part_of_speech}`, or `{}`.

    `fetch_fn` takes a URL and returns the JSON body (str/bytes, or an
    already-parsed object). Any failure — a refused shape, offline, a 404 "No
    Definitions Found", malformed JSON, no usable sense — yields `{}`. A
    missing definition is not an event: see the caller's fail-quiet contract.
    """
    if not word:
        return {}
    try:
        raw = fetch_fn(build_query(word))
        data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        return parse_entry(cast(object, data))
    except Exception:                                # noqa: BLE001 — never raise
        return {}


def define_fn(fetch_fn: Callable[[str], object], ttl: float = 3600.0,
              now_fn: Optional[Callable[[], float]] = None) -> Callable[[str], dict]:
    """A `define(word) -> dict` bound to a fetch function, with a per-word TTL
    cache so a word repeated across a conversation costs one request (the API
    is free and asks clients to be polite). Like `ol_shop_fn`, the cache holds
    even an EMPTY result, so a word with no entry is not re-requested every
    time it comes up — which is also what keeps a proper noun that slipped the
    rarity gate from being sent more than once.
    """
    import time
    now = now_fn or time.time
    cache: dict = {}

    def define(word: str) -> dict:
        key = (word or "").strip().lower()
        hit = cache.get(key)
        if hit is not None and (now() - hit[0]) < ttl:
            return hit[1]
        result = lookup(key, fetch_fn)
        cache[key] = (now(), result)
        return result

    return define


def _default_fetch(url: str, retries: int = 1, backoff: float = 0.5) -> str:
    """The shipped network fetch: urllib with one retry on a transient failure.

    Hardened egress, identical to the openlibrary/openfoodfacts siblings: the
    read is size-capped at ``_MAX_RESPONSE_BYTES`` (response-OOM) and 3xx
    redirects are refused (SSRF-via-redirect) through :mod:`plugins._egress`, so
    egress can never leave the api.dictionaryapi.dev host :func:`build_query`
    pins.

    ONE retry rather than openlibrary's two, and no retry at all on a 4xx: the
    dominant non-2xx here is the 404 the API returns for "No Definitions Found",
    which is a normal outcome for a rare word and will never improve by asking
    again. A word nobody can define must cost one request, not three.
    """
    import time
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url, headers={"User-Agent": "DreamLayer-Lexicon/0.1 (+https://dreamlayer.app)"})
    opener = no_redirect_opener()
    last: Exception = RuntimeError("no attempt")
    for attempt in range(max(1, retries + 1)):
        try:
            with opener.open(req, timeout=4) as r:   # network capability, no redirects
                return read_capped(r, _MAX_RESPONSE_BYTES).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500:              # 3xx (refused redirect) / 404 won't improve
                raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        if attempt < retries:
            time.sleep(backoff * (2 ** attempt))
    raise last
