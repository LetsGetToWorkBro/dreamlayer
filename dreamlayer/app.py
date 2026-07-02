"""
dreamlayer/app.py
DreamLayer Application Layer.

Wires together:
  - DreamLayerFSM          (pure state machine)
  - BLE client (bleak)    (connect / reconnect / frame I/O)
  - Hardware events       (button, IMU) decoded from BLE RX notifications
  - AI callback hook      (pluggable on_loading coroutine)
  - Display sender        (send MemoryCard frames to the device TX char)

Usage
-----
    from dreamlayer.orchestrator import DreamLayerApp, AppConfig
    import asyncio

    async def my_ai_handler(app: DreamLayerApp) -> None:
        card = MemoryCard(card_type="ObjectRecallCard",
                          payload={"object": "KEYS", "place": "KITCHEN",
                                   "last_seen": "2h ago", "confidence": 0.91},
                          source="ai", confidence=0.91)
        await app.show_card(card)

    cfg = AppConfig(device_address="AA:BB:CC:DD:EE:FF")
    app = DreamLayerApp(config=cfg, on_loading=my_ai_handler)
    asyncio.run(app.run())

The app auto-reconnects with exponential backoff (1s → 2s → 4s … capped at 30s).
Stop cleanly with app.stop() or Ctrl-C.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from dreamlayer.fsm import Event, MemoryCard, DreamLayerFSM, State

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional bleak import — lifted to module level so patch() works in tests.
# If bleak is not installed the stubs raise RuntimeError at call-time.
# ---------------------------------------------------------------------------
try:
    from bleak import BleakClient, BleakScanner  # type: ignore
except ImportError:  # pragma: no cover
    class BleakScanner:  # type: ignore
        @staticmethod
        async def discover(timeout: float = 5.0):  # type: ignore
            raise RuntimeError("bleak not installed. Run: pip install bleak")

    class BleakClient:  # type: ignore
        def __init__(self, address: str) -> None: ...
        async def __aenter__(self): raise RuntimeError("bleak not installed")
        async def __aexit__(self, *_): ...

# ---------------------------------------------------------------------------
# BLE UUIDs (Nordic UART)
# ---------------------------------------------------------------------------
HALO_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
HALO_TX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # host → device
HALO_RX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # device → host (notify)

HALO_NAME_PREFIX = "Frame"
MTU = 240

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
    device_address:  Optional[str] = None
    scan_timeout:    float         = 6.0
    loading_timeout: float         = 10.0
    reconnect_base:  float         = 1.0
    reconnect_max:   float         = 30.0
    reconnect_tries: int           = 0
    log_level:       str           = "INFO"


LoadingCallback = Callable[["DreamLayerApp"], Awaitable[None]]


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
        return json.loads(data[4:])
    except Exception:
        return None


async def _scan_for_halo(timeout: float) -> Optional[str]:
    """Discover the nearest Halo (Frame-prefixed) device by RSSI."""
    devices = await BleakScanner.discover(timeout=timeout)
    halos = sorted(
        [d for d in devices if d.name and d.name.startswith(HALO_NAME_PREFIX)],
        key=lambda d: d.rssi,
        reverse=True,
    )
    return halos[0].address if halos else None


async def _send_frame(client: Any, frame: bytes) -> None:
    for i in range(0, len(frame), MTU):
        await client.write_gatt_char(HALO_TX_CHAR_UUID, frame[i:i + MTU], response=False)
        await asyncio.sleep(0.01)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class DreamLayerApp:
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
        self.config      = config or AppConfig()
        self._fsm        = DreamLayerFSM(on_transition=self._on_transition)
        self._on_loading: Optional[LoadingCallback] = on_loading
        self._client: Any                     = None
        self._running    = False
        self._stop_event: Optional[asyncio.Event] = None
        self._loading_task: Optional[asyncio.Task] = None
        self._reconnect_delay  = self.config.reconnect_base
        self._connect_attempts = 0
        logging.basicConfig(level=getattr(logging, self.config.log_level))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> State:
        return self._fsm.state

    @property
    def fsm(self) -> DreamLayerFSM:
        return self._fsm

    def stop(self) -> None:
        self._running = False
        if self._stop_event:
            self._stop_event.set()

    async def show_card(self, card: MemoryCard) -> None:
        """Advance FSM to CARD and push the card frame to the device."""
        self._fsm.send(Event.RESULT_READY, payload=card)
        if self._client and self._client.is_connected:
            frame = _encode_frame({
                "t": "card",
                "payload": {**card.payload, "type": card.card_type},
            })
            await _send_frame(self._client, frame)
            log.info("show_card: %s", card.card_type)

    async def send_command(self, kind: str) -> None:
        if self._client and self._client.is_connected:
            frame = _encode_frame({"t": "command", "kind": kind})
            await _send_frame(self._client, frame)

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
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

        log.info("DreamLayerApp stopped.")

    # ------------------------------------------------------------------
    # Internal: connect + notification loop
    # ------------------------------------------------------------------

    async def _connect_and_run(self, address: str) -> None:
        log.info("Connecting to %s...", address)
        async with BleakClient(address) as client:
            self._client = client
            self._reconnect_delay = self.config.reconnect_base
            self._fsm.send(Event.BLE_CONNECT)
            log.info("Connected to %s", address)

            await client.start_notify(HALO_RX_CHAR_UUID, self._on_rx)

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
            event = _BUTTON_MAP.get(msg.get("kind", ""))
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

    def _on_transition(self, prev: State, event: Event, nxt: State) -> None:
        log.info("FSM: %s --%s--> %s", prev.name, event.name, nxt.name)

        # Only auto-advance LISTENING → LOADING when an AI callback is wired.
        # Without on_loading the FSM parks at LISTENING (tests can assert it).
        if nxt == State.LISTENING and self._on_loading is not None:
            self._fsm.send(Event.LOADING_START)
            try:
                loop = asyncio.get_running_loop()
                self._loading_task = loop.create_task(self._run_loading())
            except RuntimeError:
                pass  # no running loop — caller advances manually

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
