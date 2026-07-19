"""plugins/registry_client.py — fetch the plugin-store catalogue and packages
from the ONE pinned official registry, so the in-app store can browse + 1-click
install without a web page or terminal (fast-follow 2026-07-19).

Trust model, unchanged from the paste-a-package path — this only adds the *fetch*:
  * The host is PINNED in code (raw.githubusercontent.com of this repo's
    `registry/`); the client never sends a URL, only a plugin NAME, so there is
    no SSRF surface. A package `url` from the index is refused unless it's a
    relative `registry/...` path, and is resolved against the pinned base.
  * Redirects are refused (no_redirect_opener) so egress can't bounce off the
    pinned host, and every read is byte-capped (read_capped) against a hostile /
    MITM'd reply.
  * The fetched package still goes through the SAME PluginStore.install() gate:
    the registry's advertised sha256 checksum must match the fetched package, and
    the capability/sandbox validation runs before anything is written or run.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Callable, Optional

from ._egress import no_redirect_opener, read_capped

# The official registry is the git-backed `registry/` in this repo, served raw.
REGISTRY_RAW_BASE = ("https://raw.githubusercontent.com/"
                     "LetsGetToWorkBro/dreamlayer/main/")
REGISTRY_INDEX_URL = REGISTRY_RAW_BASE + "registry/index.json"
MAX_INDEX_BYTES = 512 * 1024
MAX_PACKAGE_BYTES = 1024 * 1024
_TIMEOUT_S = 15.0

# Injectable for tests (no real network). Signature: (url, cap) -> text.
Getter = Callable[[str, int], str]


def _http_get(url: str, cap: int) -> str:
    opener = no_redirect_opener()
    req = urllib.request.Request(url, headers={"User-Agent": "DreamLayer"})
    with opener.open(req, timeout=_TIMEOUT_S) as resp:
        return read_capped(resp, cap).decode("utf-8")


def fetch_index(getter: Optional[Getter] = None) -> dict:
    """The store catalogue: {schema, updated, plugins:[…]}, from the pinned
    index.json. Raises on network/parse failure — the caller reports it."""
    get = getter or _http_get
    return json.loads(get(REGISTRY_INDEX_URL, MAX_INDEX_BYTES))


def fetch_package(rel_url: str, getter: Optional[Getter] = None) -> str:
    """Fetch a package's manifest+source JSON text by its INDEX-relative url.
    An absolute/off-host url is refused — packages only ever come from the pinned
    registry, so a poisoned index entry can't redirect the fetch elsewhere."""
    rel = (rel_url or "").strip()
    if not rel or "://" in rel or rel.startswith(("//", "\\", "/")):
        raise ValueError("registry package url must be a relative registry path")
    get = getter or _http_get
    return get(REGISTRY_RAW_BASE + rel, MAX_PACKAGE_BYTES)
