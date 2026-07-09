"""confluence/relay_transport.py — the hosted mesh relay's client half.

GhostMode's `MeshTransport` seam (mesh.py) was designed so nothing above it
knows the radio: BLE Coded PHY in a crowd, an in-memory bus in tests — and,
with DreamLayer Cloud (docs/CLOUD.md), a blind relay room on
api.dreamlayer.app so a circle keeps working beyond Bluetooth range (the
Beacon across a city, weather between friends in different places).

The relay can be blind because the security never left the packet: every
MeshPacket is HMAC'd with the circle's group key, and MeshManager.receive()
drops forged/replayed/stranger traffic no matter what carried it. The server
stores and forwards opaque wire dicts; it cannot read, forge, or join.
The Veil needs no handling here — a veiled wearer's mesh.emit() returns None,
so a silenced side simply has nothing to send.

Transport is poll-based v1 (POST to send, GET to drain), matching the Worker
in registry-api/. HTTP is injectable for tests and self-hosters; when the
relay is unreachable, sends buffer locally and flush on the next success, so
a flaky link degrades to "late", never to "lost" (within the buffer bound).
"""
from __future__ import annotations

import json
import logging
from collections import deque
from typing import Callable, Deque, List, Optional

log = logging.getLogger("dreamlayer.relay_transport")

DEFAULT_RELAY_BASE = "https://api.dreamlayer.app/api/relay"


def _urllib_json(method: str, url: str, payload: Optional[dict],
                 token: str, timeout: float) -> dict:
    import urllib.request
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Content-Type": "application/json",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    })
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


class CloudRelayTransport:
    """A `MeshTransport` (send/recv) over the hosted relay.

    `room` is the circle's relay room id — derived client-side from the group
    code so the server never learns the group key. `member` de-duplicates a
    sender's own echo server-side (the mesh drops self-echo anyway; this just
    saves bytes). `http` is an injectable `fn(method, url, payload) -> dict`
    for tests, self-hosted relays, and future websocket upgrades."""

    def __init__(self, room: str, member: str, base_url: str = DEFAULT_RELAY_BASE,
                 token: str = "", http: Optional[Callable] = None,
                 timeout: float = 6.0, max_buffer: int = 256):
        self.room = room
        self.member = member
        self.base = base_url.rstrip("/")
        self._http = http or (lambda m, u, p: _urllib_json(m, u, p, token, timeout))
        self._pending: Deque[dict] = deque(maxlen=max_buffer)
        self._cursor = 0                     # server-side position we've drained to
        self.online = True                   # last-known reachability (observability)

    # -- MeshTransport surface -------------------------------------------------

    def send(self, wire: dict) -> None:
        """Queue-and-flush: buffered locally first, so an unreachable relay
        degrades to late delivery instead of dropped packets."""
        self._pending.append(dict(wire))
        self._flush()

    def recv(self) -> List[dict]:
        """Drain new wire dicts from the room since our cursor. Also retries
        any locally buffered sends first (a recv proves the link is back)."""
        self._flush()
        try:
            out = self._http("GET",
                             f"{self.base}/{self.room}/recv"
                             f"?since={self._cursor}&member={self.member}", None) or {}
            self.online = True
        except Exception as exc:
            log.debug("[relay] recv failed: %s", exc)
            self.online = False
            return []
        self._cursor = int(out.get("cursor", self._cursor))
        return list(out.get("packets", []))

    # -- internals ---------------------------------------------------------------

    def _flush(self) -> None:
        while self._pending:
            wire = self._pending[0]
            try:
                self._http("POST", f"{self.base}/{self.room}/send",
                           {"member": self.member, "wire": wire})
                self._pending.popleft()
                self.online = True
            except Exception as exc:
                log.debug("[relay] send buffered (%d queued): %s",
                          len(self._pending), exc)
                self.online = False
                return
