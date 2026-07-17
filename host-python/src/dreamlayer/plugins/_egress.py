"""plugins/_egress.py — shared hardened HTTP-fetch primitives for the keyless
TasteLens/panel connectors.

Every shipped connector (openlibrary, openfoodfacts, currency, vinyl_oracle)
talks to ONE pinned public API host over urllib. Two egress failure modes are
common to all of them, and must be closed in ONE place so the next connector
can't reintroduce them by copy-paste (audit 2026-07-17 found openlibrary hardened
but three siblings still on the old pattern — a classic sibling call-site gap):

  * response-OOM — an unbounded ``r.read()`` lets a hostile or MITM'd reply
    stream an arbitrary body into memory. :func:`read_capped` reads at most
    ``max_bytes`` (+1, to detect the overflow) and raises rather than truncating.

  * SSRF-via-redirect — ``urllib`` follows 3xx by default, so a bounce off the
    pinned host to an internal/attacker host is undeclared egress. The opener
    from :func:`no_redirect_opener` refuses every 3xx (it surfaces as the
    ``HTTPError`` the callers' retry loops already classify), so egress can never
    leave the host the connector's query builder pinned.

Connectors keep their OWN retry/backoff/error-classification loops — they differ
per API (429 politeness for Discogs, 5xx retries for OFF, no retry for the FX
rate) — so only the two egress primitives live here, not the request policy.
"""
from __future__ import annotations

import urllib.request

# Keyless catalog/search/rate replies are a few KB; cap the read so a hostile or
# MITM'd reply can't stream an unbounded body into memory. Connectors may pass a
# smaller cap; this is the shared default.
MAX_RESPONSE_BYTES = 512 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        # Returning None refuses the redirect; urllib then surfaces the 3xx as an
        # HTTPError instead of transparently following the Location header.
        return None


def no_redirect_opener() -> urllib.request.OpenerDirector:
    """An opener that refuses 3xx redirects (they surface as ``HTTPError``), so
    egress stays on the request host the caller pinned — no SSRF-via-redirect."""
    return urllib.request.build_opener(_NoRedirect)


def read_capped(resp, max_bytes: int = MAX_RESPONSE_BYTES) -> bytes:
    """Read at most ``max_bytes`` from an open response and raise ``ValueError``
    if the body exceeds it — never silently truncate. ``read(n)`` can return at
    most ``n`` bytes, so peak memory is bounded by ``max_bytes + 1`` regardless
    of the declared ``Content-Length`` or a chunked stream."""
    body = resp.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError(f"response exceeds {max_bytes} bytes")
    return body
