#!/usr/bin/env python3
"""
scripts/puente_live.py
Puente → DreamLayer live translation captions on a real Halo over BLE.

Runs a LAN WebSocket server that the Puente phone app connects to
(Settings → DreamLayer Glasses). Each translation the app produces is
converted to a LiveCaptionCard by PuenteBridge and pushed to the glasses
as a standard DreamLayer card frame.

    Puente app ──ws://<this-host>:8765──▶ PuenteCaptionServer
                                              │ PuenteBridge
                                              ▼
                                    {"t":"card", payload: LiveCaptionCard}
                                              │ BLE (Nordic UART)
                                              ▼
                                        Halo glasses

Usage:
    uv run python scripts/puente_live.py                     # auto-discover Halo
    uv run python scripts/puente_live.py --device AA:BB:...  # explicit device
    uv run python scripts/puente_live.py --dry-run           # no BLE, print cards
    uv run python scripts/puente_live.py --port 9000

Requirements:
    uv sync --extra puente     (websockets; bleak ships with the base deps)
"""

import argparse
import asyncio
import json
import logging
import socket
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The engine package (host-python/src/dreamlayer) shares its name with the
# lightweight top-level package (dreamlayer/). Put the engine first on the
# path so `dreamlayer.orchestrator.*` resolves — same trick as other scripts.
sys.path.insert(0, str(REPO_ROOT / "host-python" / "src"))
sys.path.insert(1, str(Path(__file__).resolve().parent))

from dreamlayer.orchestrator.puente_bridge import PuenteBridge          # noqa: E402
from dreamlayer.orchestrator.puente_server import (                     # noqa: E402
    DEFAULT_PORT,
    PuenteCaptionServer,
)
from halo_lab import ble_frame                                          # noqa: E402
from halo_bridge import (                                               # noqa: E402
    HALO_TX_CHAR_UUID,
    MTU,
    scan_devices,
)

log = logging.getLogger("puente_live")


def lan_ip() -> str:
    """Best-effort LAN IP for the connect hint printed at startup."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


class CardSink:
    """Serialises cards into BLE card frames and writes them to the device.

    Cards are funneled through a queue so a slow BLE link back-pressures
    into dropped intermediate captions (only the newest pending card is
    kept) instead of an ever-growing backlog.
    """

    def __init__(self, client=None, dry_run: bool = False) -> None:
        self.client = client
        self.dry_run = dry_run
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self.sent = 0

    def push(self, card: dict) -> None:
        """Bridge callback — never blocks; newest card wins."""
        if not card:
            return
        while True:
            try:
                self.queue.put_nowait(card)
                return
            except asyncio.QueueFull:
                try:
                    self.queue.get_nowait()   # drop the stale pending card
                except asyncio.QueueEmpty:
                    pass

    async def run(self) -> None:
        while True:
            card = await self.queue.get()
            frame = ble_frame({"t": "card", "payload": card})
            if self.dry_run:
                text = f"{card.get('eyebrow', '')} | {card.get('primary', '')}"
                print(f"  [card {self.sent:03d}] {len(frame)}B  {text}")
            else:
                try:
                    for i in range(0, len(frame), MTU):
                        await self.client.write_gatt_char(
                            HALO_TX_CHAR_UUID, frame[i:i + MTU], response=False
                        )
                        await asyncio.sleep(0.01)
                except Exception as exc:
                    log.warning("BLE write failed (%s) — card dropped", exc)
            self.sent += 1


async def run_server(sink: CardSink, host: str, port: int) -> None:
    bridge = PuenteBridge()
    bridge.on_card(sink.push)

    server = PuenteCaptionServer(bridge, host=host, port=port)
    await server.start()
    print(f"\nPuente caption server listening on ws://{lan_ip()}:{port}")
    print("In the Puente app: Settings → DreamLayer Glasses → enter that URL.\n")

    await asyncio.gather(sink.run())


async def async_main() -> None:
    parser = argparse.ArgumentParser(
        description="Puente → DreamLayer live captions on Halo glasses"
    )
    parser.add_argument("--device", metavar="ADDR",
                        help="BLE address of target Halo (skip auto-select)")
    parser.add_argument("--host", default="0.0.0.0",
                        help="WebSocket bind address (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"WebSocket port (default {DEFAULT_PORT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="No BLE — print cards that would be sent")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.dry_run:
        print("DRY RUN — cards are printed, no glasses required.")
        sink = CardSink(dry_run=True)
        await run_server(sink, args.host, args.port)
        return

    try:
        from bleak import BleakClient
    except ImportError:
        print("ERROR: bleak not installed. Run: uv sync")
        sys.exit(1)

    device_address = args.device
    if not device_address:
        devices = await scan_devices(timeout=6.0)
        if not devices:
            print("\nERROR: No Halo devices found. Use --device ADDR or --dry-run.")
            sys.exit(1)
        device_address = devices[0]["address"]
        print(f"Auto-selected: {device_address} ({devices[0]['name']})")

    print(f"Connecting to {device_address}...")
    async with BleakClient(device_address) as client:
        if not client.is_connected:
            print(f"ERROR: failed to connect to {device_address}")
            sys.exit(1)
        print("Connected to Halo.")
        sink = CardSink(client=client)
        await run_server(sink, args.host, args.port)


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
