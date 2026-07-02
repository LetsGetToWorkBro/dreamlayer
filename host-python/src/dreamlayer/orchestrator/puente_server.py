"""orchestrator/puente_server.py

PuenteCaptionServer — WebSocket ingress for the Puente translation app.

Puente (the React Native earbud-translation app) streams live transcript
and translation events over a LAN WebSocket. This server receives those
events, feeds them through PuenteBridge, and the resulting
LiveCaptionCard dicts flow to whatever card sink the caller registered
(normally ``bridge.send_card`` → BLE → glasses).

Architecture
------------
    Puente app ──ws──▶ PuenteCaptionServer ──▶ PuenteBridge ──▶ on_card cb
                                                                  │
                                                        BLE card frame → Halo

Wire protocol (v1) — JSON text frames, client → server:

    {"v":1,"type":"hello","client":"puente"}
    {"v":1,"type":"partial","text":"Hola mun…","srcLang":"es","speaker":"Maria"}
    {"v":1,"type":"translation","original":"Hola mundo",
     "translation":"Hello world","srcLang":"es","targetLang":"en",
     "confidence":0.93,"speaker":"Maria","turnId":"t-42"}
    {"v":1,"type":"ping"}

Server → client replies:

    {"type":"hello_ack","server":"dreamlayer","v":1}
    {"type":"ack","turnId":"t-42"}          (per translation frame)
    {"type":"pong"}
    {"type":"error","reason":"..."}

``caption`` is accepted as an alias of ``partial`` for third-party feeds.

Partial frames are throttled (default 300 ms) so a word-by-word reveal
cannot flood the BLE link; translation frames always pass.

The ``websockets`` package is imported lazily inside ``start()`` so this
module (and its message-handling logic) stays importable and testable
without the optional dependency (``pip install dreamlayer[puente]``).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Awaitable, Callable, Optional

from .puente_bridge import PuenteBridge

log = logging.getLogger("dreamlayer.puente_server")

PROTOCOL_VERSION = 1
DEFAULT_PORT = 8765

# Client message types → required string fields.
_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "hello": (),
    "ping": (),
    "partial": ("text",),
    "caption": ("text",),          # alias of partial
    "translation": ("original", "translation"),
}

# Bound inbound text so a misbehaving client cannot bloat BLE frames.
MAX_TEXT_LEN = 512


class PuenteProtocolError(ValueError):
    """Raised when an inbound frame violates the v1 protocol."""


def parse_puente_message(raw: str | bytes) -> dict:
    """Validate and normalise one inbound frame.

    Returns the parsed dict with ``type`` guaranteed present and valid,
    string fields stripped/bounded, and ``confidence`` clamped to [0, 1].
    Raises PuenteProtocolError on any violation.
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PuenteProtocolError("frame is not valid UTF-8") from exc

    try:
        msg = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PuenteProtocolError("frame is not valid JSON") from exc

    if not isinstance(msg, dict):
        raise PuenteProtocolError("frame must be a JSON object")

    mtype = msg.get("type")
    if mtype not in _REQUIRED_FIELDS:
        raise PuenteProtocolError(f"unknown message type: {mtype!r}")

    for field in _REQUIRED_FIELDS[mtype]:
        value = msg.get(field)
        if not isinstance(value, str) or not value.strip():
            raise PuenteProtocolError(f"{mtype!r} requires non-empty string {field!r}")
        msg[field] = value.strip()[:MAX_TEXT_LEN]

    # Optional string metadata — drop silently when malformed.
    for field in ("srcLang", "targetLang", "speaker", "turnId", "client"):
        value = msg.get(field)
        if value is not None and not isinstance(value, str):
            msg.pop(field, None)

    confidence = msg.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            msg.pop("confidence", None)
        else:
            msg["confidence"] = max(0.0, min(1.0, float(confidence)))

    return msg


class PuenteCaptionServer:
    """LAN WebSocket server that feeds Puente caption events to a PuenteBridge.

    Usage
    -----
        bridge = PuenteBridge()
        bridge.on_card(ble.send_card)

        server = PuenteCaptionServer(bridge, port=8765)
        await server.start()
        ...
        await server.stop()
    """

    def __init__(
        self,
        bridge: PuenteBridge,
        host: str = "0.0.0.0",
        port: int = DEFAULT_PORT,
        partial_min_interval_ms: int = 300,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._bridge = bridge
        self.host = host
        self.port = port
        self._partial_min_interval_s = partial_min_interval_ms / 1000.0
        self._clock = clock
        self._last_partial_at: float = float("-inf")
        self._server = None  # websockets server handle
        self._clients: set = set()

    # ------------------------------------------------------------------
    # Message handling (transport-independent, unit-testable)
    # ------------------------------------------------------------------

    async def handle_message(
        self,
        raw: str | bytes,
        send: Callable[[str], Awaitable[None]],
    ) -> Optional[dict]:
        """Process one inbound frame; reply via ``send``.

        Returns the card dict produced by the bridge (empty dict when the
        bridge rejected the text, None for non-caption frames), so callers
        and tests can observe the outcome.
        """
        try:
            msg = parse_puente_message(raw)
        except PuenteProtocolError as exc:
            await send(json.dumps({"type": "error", "reason": str(exc)}))
            return None

        mtype = msg["type"]

        if mtype == "hello":
            log.info("puente client hello: %s", msg.get("client", "?"))
            await send(json.dumps(
                {"type": "hello_ack", "server": "dreamlayer", "v": PROTOCOL_VERSION}
            ))
            return None

        if mtype == "ping":
            await send(json.dumps({"type": "pong"}))
            return None

        if mtype in ("partial", "caption"):
            now = self._clock()
            if now - self._last_partial_at < self._partial_min_interval_s:
                return None
            self._last_partial_at = now
            return self._bridge.on_caption(
                text=msg["text"],
                confidence=msg.get("confidence", 1.0),
                speaker=msg.get("speaker"),
                src_lang=msg.get("srcLang"),
            )

        # mtype == "translation"
        card = self._bridge.on_translation(
            original=msg["original"],
            translation=msg["translation"],
            confidence=msg.get("confidence", 1.0),
            speaker=msg.get("speaker"),
            src_lang=msg.get("srcLang"),
        )
        ack: dict = {"type": "ack"}
        if "turnId" in msg:
            ack["turnId"] = msg["turnId"]
        await send(json.dumps(ack))
        return card

    # ------------------------------------------------------------------
    # WebSocket transport
    # ------------------------------------------------------------------

    async def _handler(self, websocket) -> None:
        peer = getattr(websocket, "remote_address", None)
        log.info("puente client connected: %s", peer)
        self._clients.add(websocket)
        try:
            async for raw in websocket:
                await self.handle_message(raw, websocket.send)
        except Exception as exc:  # connection torn down mid-frame etc.
            log.debug("puente client %s dropped: %s", peer, exc)
        finally:
            self._clients.discard(websocket)
            log.info("puente client disconnected: %s", peer)

    async def start(self) -> None:
        """Bind the WebSocket server. Requires the ``websockets`` package."""
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError(
                "PuenteCaptionServer requires the 'websockets' package — "
                "install with: pip install 'dreamlayer[puente]'"
            ) from exc

        self._server = await websockets.serve(self._handler, self.host, self.port)
        log.info("PuenteCaptionServer listening on ws://%s:%d", self.host, self.port)

    async def stop(self) -> None:
        """Close all client connections and unbind."""
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def serve_forever(self) -> None:
        """Convenience: start (if needed) and block until cancelled."""
        if self._server is None:
            await self.start()
        await asyncio.Future()
