"""
memoscape/app.py
Memoscape Application Layer.

Wires together:
  - MemoscapeFSM          (pure state machine)
  - BLE client (bleak)    (connect / reconnect / frame I/O)
  - Hardware events       (button, IMU) decoded from BLE RX notifications
  - AI callback hook      (pluggable on_loading coroutine)
  - Display sender        (send MemoryCard frames to the device TX char)

Usage
-----
    from memoscape.app import MemoscapeApp, AppConfig
    import asyncio

    async def my_ai_handler(app: MemoscapeApp) -> None:
        # called when FSM enters LOADING
        card = MemoryCard(card_type="ObjectRecallCard",
                          payload={"object": "KEYS", "place": "KITCHEN",
                                   "last_seen": "2h ago", "confidence": 0.91},
                          source="ai", confidence=0.91)
        await app.show_card(card)

    cfg = AppConfig(device_address="AA:BB:CC:DD:EE:FF")
    app = MemoscapeApp(config=cfg, on_loading=my_ai_handler)
    asyncio.run(app.run())

The app auto-reconnects with exponential backoff (1s → 2s → 4s … capped at 30s).
Stop cleanly with app.stop() or Ctrl-C.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from memoscape.fsm import (
    Event, MemoryCard, MemoscapeFSM, State,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BLE UUIDs (Nordic UART)
# ---------------------------------------------------------------------------
HALO_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
HALO_TX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # host → device
HALO_RX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # device → host (notify)

HALO_NAME_PREFIX  = "Frame"
MTU               = 240

# BLE message type tags sent by the device
_BUTTON_MAP = {
    "single": Event.BUTTON_SINGLE,
    "double": Event.BUTTON_DOUBLE,
    "long":   Event.BUTTON_LONG,
}

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class AppConfig:
    device_address:  Optional[str] = None   # None = auto-discover
    scan_timeout:    float         = 6.0    # seconds to scan for device
    loading_timeout: float         = 10.0   # seconds before TIMEOUT event
    reconnect_base:  float         = 1.0    # initial backoff seconds
    reconnect_max:   float         = 30.0   # cap backoff seconds
    reconnect_tries: int           = 0      # 0 = infinite
    log_level:       str           = "INFO"


# AI callback type: async fn that receives the app and produces a card
LoadingCallback = Callable[["MemoscapeApp"], Awaitable[None]]


# ---------------------------------------------------------------------------
# BLE frame helpers
# ---------------------------------------------------------------------------

def _encode_frame(msg: dict) -> bytes:
    raw = json.dumps(msg).encode()
    return struct.pack(">I", len(raw) + 4) + raw


def _decode_frame(data: bytes) -> Optional[dict]:
    try:
        if len(data) < 4:
            return None
        payload = data[4:]
        return json.loads(payload)
    except Exception:
        return None


async def _scan_for_halo(timeout: float) -> Optional[str]:
    try:
        from bleak import BleakScanner
    except ImportError:
        raise RuntimeError("bleak not installed. Run: pip install bleak")
    devices = await BleakScanner.discover(timeout=timeout)
    halos   = sorted(
        [d for d in devices if d.name and d.name.startswith(HALO_NAME_PREFIX)],
        key=lambda d: d.rssi, reverse=True,
    )
    return halos[0].address if halos else None


async def _send_frame(client: Any, frame: bytes) -> None:
    for i in range(0, len(frame), MTU):
        await client.write_gatt_char(HALO_TX_CHAR_UUID, frame[i:i + MTU], response=False)
        await asyncio.sleep(0.01)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class MemoscapeApp:
    """
    Top-level application object.
    Call await app.run() to start the event loop.
    Call app.stop() to request a clean shutdown.
    """

    def __init__(
        self,
        config:     Optional[AppConfig]      = None,
        on_loading: Optional[LoadingCallback] = None,
    ) -> None:
        self.config     = config or AppConfig()
        self._fsm       = MemoscapeFSM(on_transition=self._on_transition)
        self._on_loading: Optional[LoadingCallback] = on_loading
        self._client: Any = None          # BleakClient when connected
        self._running   = False
        self._stop_event: Optional[asyncio.Event] = None
        self._loading_task: Optional[asyncio.Task] = None
        self._reconnect_delay = self.config.reconnect_base
        self._connect_attempts = 0
        logging.basicConfig(level=getattr(logging, self.config.log_level))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> State:
        return self._fsm.state

    @property
    def fsm(self) -> MemoscapeFSM:
        return self._fsm

    def stop(self) -> None:
        """Request a clean shutdown."""
        self._running = False
        if self._stop_event:
            self._stop_event.set()

    async def show_card(self, card: MemoryCard) -> None:
        """
        Push a MemoryCard to the device display and advance the FSM.
        Safe to call from the on_loading callback.
        """
        self._fsm.send(Event.RESULT_READY, payload=card)
        if self._client and self._client.is_connected:
            frame = _encode_frame({
                "t": "card",
                "payload": {**card.payload, "type": card.card_type},
            })
            await _send_frame(self._client, frame)
            log.info("show_card: %s", card.card_type)

    async def send_command(self, kind: str) -> None:
        """Send a command frame (ask, pause, loading, resume)."""
        if self._client and self._client.is_connected:
            frame = _encode_frame({"t": "command", "kind": kind})
            await _send_frame(self._client, frame)

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main entry point. Runs until stop() is called."""
        self._running    = True
        self._stop_event = asyncio.Event()
        attempt = 0

        while self._running:
            address = self.config.device_address
            if not address:
                log.info("Scanning for Halo (%.1fs)...", self.config.scan_timeout)
                address = await _scan_for_halo(self.config.scan_timeout)
                if not address:
                    log.warning("No Halo found — retrying in %.1fs", self._reconnect_delay)
                    await self._backoff_sleep()
                    continue
                log.info("Found: %s", address)

            attempt += 1
            self._connect_attempts = attempt
            if self.config.reconnect_tries and attempt > self.config.reconnect_tries:
                log.error("Max reconnect attempts reached (%d)", self.config.reconnect_tries)
                break

            try:
                await self._connect_and_run(address)
            except Exception as exc:
                log.warning("Connection lost: %s", exc)
            finally:
                self._fsm.send(Event.BLE_DISCONNECT)

            if not self._running:
                break

            log.info("Reconnecting in %.1fs...", self._reconnect_delay)
            await self._backoff_sleep()

        log.info("MemoscapeApp stopped.")

    # ------------------------------------------------------------------
    # Internal: connect + notification loop
    # ------------------------------------------------------------------

    async def _connect_and_run(self, address: str) -> None:
        try:
            from bleak import BleakClient
        except ImportError:
            raise RuntimeError("bleak not installed. Run: pip install bleak")

        log.info("Connecting to %s...", address)
        async with BleakClient(address) as client:
            self._client = client
            self._reconnect_delay = self.config.reconnect_base   # reset backoff
            self._fsm.send(Event.BLE_CONNECT)
            log.info("Connected to %s", address)

            await client.start_notify(HALO_RX_CHAR_UUID, self._on_rx)

            # Wait until disconnected or stop requested
            await self._stop_event.wait() if not self._running else None
            disconnect_event = asyncio.Event()

            def _on_disconnect(c: Any) -> None:
                disconnect_event.set()

            client.set_disconnected_callback(_on_disconnect)

            stop_task       = asyncio.create_task(self._stop_event.wait())
            disconnect_task = asyncio.create_task(disconnect_event.wait())
            await asyncio.wait(
                [stop_task, disconnect_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            stop_task.cancel()
            disconnect_task.cancel()

        self._client = None

    # ------------------------------------------------------------------
    # Internal: RX notification handler
    # ------------------------------------------------------------------

    def _on_rx(self, _sender: Any, data: bytes) -> None:
        msg = _decode_frame(data)
        if not msg:
            log.debug("RX: unparseable frame (%d bytes)", len(data))
            return

        t = msg.get("t", "")
        log.debug("RX: %s", msg)

        if t == "button":
            kind  = msg.get("kind", "")
            event = _BUTTON_MAP.get(kind)
            if event:
                self._fsm.send(event)

        elif t == "imu_tap":
            self._fsm.send(Event.IMU_TAP)

        elif t == "card":
            payload   = msg.get("payload", {})
            card_type = payload.pop("type", "UnknownCard")
            card      = MemoryCard(card_type=card_type, payload=payload, source="ble")
            self._fsm.send(Event.CARD_RECEIVED, payload=card)

        elif t == "privacy_toggle":
            self._fsm.send(Event.PRIVACY_TOGGLE)

    # ------------------------------------------------------------------
    # Internal: FSM transition hook
    # ------------------------------------------------------------------

    def _on_transition(
        self, prev: State, event: Event, nxt: State
    ) -> None:
        log.info("FSM: %s --%s--> %s", prev.name, event.name, nxt.name)

        if nxt == State.LISTENING:
            # Fire LOADING_START to move FSM to LOADING, then call AI
            self._fsm.send(Event.LOADING_START)
            if self._on_loading:
                self._loading_task = asyncio.get_event_loop().create_task(
                    self._run_loading()
                )

    async def _run_loading(self) -> None:
        try:
            async with asyncio.timeout(self.config.loading_timeout):
                if self._on_loading:
                    await self._on_loading(self)
        except asyncio.TimeoutError:
            log.warning("Loading timeout after %.1fs", self.config.loading_timeout)
            self._fsm.send(Event.TIMEOUT)
        except Exception as exc:
            log.error("Loading callback error: %s", exc)
            self._fsm.send(Event.TIMEOUT)

    # ------------------------------------------------------------------
    # Internal: backoff
    # ------------------------------------------------------------------

    async def _backoff_sleep(self) -> None:
        await asyncio.sleep(self._reconnect_delay)
        self._reconnect_delay = min(
            self._reconnect_delay * 2, self.config.reconnect_max
        )
