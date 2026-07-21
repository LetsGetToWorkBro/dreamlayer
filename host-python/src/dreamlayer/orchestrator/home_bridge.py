"""orchestrator/home_bridge.py — the glasses become a HUD for your house.

Home Assistant is local-first and lives on exactly the machines our users run a
Brain on. This bridge reads entity states over its REST API and turns the ones
worth interrupting for into the SAME attention Alerts the rest of the glasses
use: leave home and "the garage is still open" taps you; the doorbell rings and
a card lands on the glass.

Split like sound_events: `HomeBridge.states()` is the transport (LAN-gated,
token header, fetch seam); `home_alerts(states)` is the PURE policy — which
household facts deserve glass — testable with no server. LAN-only structurally:
a public base URL disables the bridge at construction.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Callable, List, Optional

from .attention import Alert

log = logging.getLogger("dreamlayer.home")

_MAX_BODY = 4 * 1024 * 1024

# device_class / domain → (fact worth saying when "on"/"open", level)
_OPEN_WORDS = {"on", "open", "unlocked"}


def _default_fetch(url: str, headers: dict,
                   timeout: float = 4.0) -> Optional[bytes]:
    try:
        req = urllib.request.Request(url, headers=dict(headers or {}))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as r:
            return r.read(_MAX_BODY)
    except Exception as exc:                       # noqa: BLE001
        log.debug("[home] fetch failed: %s", exc)
        return None


def _name(ent: dict) -> str:
    attrs = ent.get("attributes") or {}
    return str(attrs.get("friendly_name")
               or ent.get("entity_id", "")).replace("_", " ").strip()


def home_alerts(states) -> List[Alert]:
    """PURE: the household facts worth glass, from a Home Assistant states list.
    Deliberately narrow — doors/garage/locks left open and smoke/CO/water
    alarms — because a HUD that relays every light toggle teaches you to ignore
    it. Malformed entities are skipped, never raised."""
    out: List[Alert] = []
    for ent in (states or []):
        try:
            eid = str(ent.get("entity_id", "") or "")
            state = str(ent.get("state", "") or "").lower()
            attrs = ent.get("attributes") or {}
            dclass = str(attrs.get("device_class", "") or "").lower()
            domain = eid.split(".", 1)[0]
            name = _name(ent)
            if not eid or not name:
                continue
            # time-critical safety first
            if dclass in ("smoke", "carbon_monoxide", "gas", "moisture") \
                    and state == "on":
                what = {"smoke": "Smoke", "carbon_monoxide": "CO",
                        "gas": "Gas", "moisture": "Water"}[dclass]
                out.append(Alert("watchout", f"{what} alarm at home", name,
                                 f"home:alarm:{eid}"))
            # things left open/unlocked. A bare `cover` domain would nag about
            # blinds and shades that are open all day (refute 2026-07-21) — a
            # cover only alerts when its device_class is an OPENING to the
            # outside (HA covers use "garage", sensors "garage_door" — both kept).
            elif ((domain == "cover" and dclass in ("door", "garage",
                                                    "garage_door", "gate",
                                                    "window"))
                  or (domain != "cover" and dclass in ("door", "garage_door",
                                                       "window", "opening"))) \
                    and state in _OPEN_WORDS:
                out.append(Alert("listen", f"{name} is still open", "at home",
                                 f"home:open:{eid}"))
            elif domain == "lock" and state == "unlocked":
                out.append(Alert("listen", f"{name} is unlocked", "at home",
                                 f"home:open:{eid}"))
        except Exception:                          # noqa: BLE001 — one entity, not the sweep
            continue
    out.sort(key=lambda a: 0 if a.level == "watchout" else 1)
    return out


class HomeBridge:
    """Read a LAN Home Assistant. A non-local base disables the bridge."""

    def __init__(self, base_url: str, token: str = "",
                 fetch_fn: Optional[Callable[..., Optional[bytes]]] = None):
        from ..ai_brain.server.backends import is_local_endpoint
        base = (base_url or "").strip().rstrip("/")
        self.base = base if is_local_endpoint(base) else ""
        self._token = (token or "").strip()
        self._fetch = fetch_fn or _default_fetch

    @property
    def available(self) -> bool:
        return bool(self.base)

    def states(self) -> List[dict]:
        """The raw entity list, or []. Token rides as the standard Bearer."""
        if not self.base:
            return []
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        raw = self._fetch(f"{self.base}/api/states", headers)
        if raw is None:
            return []
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
            return data if isinstance(data, list) else []
        except ValueError:
            return []

    def alerts(self) -> List[Alert]:
        """states → the ranked household Alerts (the hark path applies its own
        Veil/Focus gating + per-key cooldown, same as every other alert)."""
        return home_alerts(self.states())


def default_home_bridge(base_url: str = "", token: str = "") -> Optional[HomeBridge]:
    b = HomeBridge(base_url, token)
    return b if b.available else None
