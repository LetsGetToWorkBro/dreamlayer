#!/usr/bin/env python3
"""
scripts/halo_bridge.py
Memoscape Bridge — play a Lab scenario on a real connected Halo device over BLE.

Usage:
    uv run python scripts/halo_bridge.py --list-devices
    uv run python scripts/halo_bridge.py scripts/scenarios/mindblow_demo.json
    uv run python scripts/halo_bridge.py scripts/scenarios/mindblow_demo.json --device AA:BB:CC:DD:EE:FF
    uv run python scripts/halo_bridge.py scripts/scenarios/mindblow_demo.json --dry-run

Requirements:
    uv sync
    pip install -e ~/brilliant_sdk/python/packages/halo_emulator  (for BLE transport)
    pip install bleak  (BLE scanning)

The bridge reuses the same scenario JSON format as halo_lab.py.
Each step's BLE frame is sent to the device; timing follows the 'at' field
or --settle ms fallback between steps.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

# halo_lab pure helpers — safe to import without emulator
sys.path.insert(0, str(Path(__file__).resolve().parent))
from halo_lab import ble_frame, validate_scenario, step_label, VALID_ACTIONS

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = REPO_ROOT / "scripts" / "scenarios"

HALO_SERVICE_UUID  = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"   # Nordic UART
HALO_TX_CHAR_UUID  = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # write (host → device)
HALO_RX_CHAR_UUID  = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # notify (device → host)

HALO_NAME_PREFIX   = "Frame"
MTU                = 240   # safe BLE MTU for Halo


# ---------------------------------------------------------------------------
# BLE helpers
# ---------------------------------------------------------------------------

async def scan_devices(timeout: float = 5.0) -> list[dict]:
    """Return list of {address, name, rssi} for nearby Halo devices."""
    try:
        import bleak
        from bleak import BleakScanner
    except ImportError:
        print("ERROR: bleak not installed. Run: pip install bleak")
        sys.exit(1)

    print(f"Scanning for Halo devices ({timeout:.0f}s)...")
    devices = await BleakScanner.discover(timeout=timeout)
    halos = [
        {"address": d.address, "name": d.name or "?", "rssi": d.rssi}
        for d in devices
        if d.name and d.name.startswith(HALO_NAME_PREFIX)
    ]
    return sorted(halos, key=lambda x: x["rssi"], reverse=True)


async def send_frame(client, frame: bytes) -> None:
    """Send a BLE frame in MTU-sized chunks."""
    for i in range(0, len(frame), MTU):
        await client.write_gatt_char(HALO_TX_CHAR_UUID, frame[i:i + MTU], response=False)
        await asyncio.sleep(0.01)


# ---------------------------------------------------------------------------
# Step timing
# ---------------------------------------------------------------------------

def step_delay(steps: list[dict], i: int, settle_ms: int) -> float:
    """Return seconds to wait BEFORE executing step i."""
    if i == 0:
        return 0.0
    prev_at = steps[i - 1].get("at")
    curr_at = steps[i].get("at")
    if prev_at is not None and curr_at is not None:
        return max(0.0, float(curr_at) - float(prev_at))
    return settle_ms / 1000.0


# ---------------------------------------------------------------------------
# Dry-run frame renderer (no BLE, prints what would be sent)
# ---------------------------------------------------------------------------

def dry_run_scenario(scenario: dict, settle_ms: int = 800) -> list[dict]:
    steps   = scenario["steps"]
    results = []
    print(f"\nDRY RUN — {scenario['name']} ({len(steps)} steps)")
    print("(no device required — shows frames that would be sent)\n")
    for i, step in enumerate(steps):
        delay  = step_delay(steps, i, settle_ms)
        label  = step_label(i, step)
        action = step["action"]

        if action in ("wait",):
            frame_bytes = b""
            frame_desc  = "(wait)"
        else:
            frame_bytes = ble_frame(_step_to_msg(step))
            frame_desc  = frame_bytes[4:].decode(errors="replace")

        print(f"  [{i:02d}] +{delay:.2f}s  {label}")
        print(f"        {len(frame_bytes)}B → {frame_desc[:80]}")
        results.append({"step": i, "label": label, "delay_s": delay,
                        "frame_bytes": len(frame_bytes)})
    return results


def _step_to_msg(step: dict) -> dict:
    """Convert a scenario step to a BLE message dict."""
    action = step["action"]
    if action in ("connect", "disconnect"):
        return {"t": action}
    if action == "card":
        return {"t": "card", "payload": {**step.get("payload", {}), "type": step["card_type"]}}
    if action == "command":
        return {"t": "command", "kind": step["kind"]}
    if action == "button":
        return {"t": "button", "kind": step["kind"]}
    if action == "imu_tap":
        return {"t": "imu_tap"}
    return {"t": action}


# ---------------------------------------------------------------------------
# Live BLE playback
# ---------------------------------------------------------------------------

async def play_scenario(scenario: dict, device_address: str,
                        settle_ms: int = 800, verbose: bool = True) -> dict:
    try:
        from bleak import BleakClient
    except ImportError:
        print("ERROR: bleak not installed. Run: pip install bleak")
        sys.exit(1)

    steps   = scenario["steps"]
    results = []

    print(f"\nConnecting to {device_address}...")
    async with BleakClient(device_address) as client:
        if not client.is_connected:
            print(f"ERROR: failed to connect to {device_address}")
            sys.exit(1)
        print(f"Connected. Playing {len(steps)} steps...\n")

        for i, step in enumerate(steps):
            delay = step_delay(steps, i, settle_ms)
            if delay > 0:
                await asyncio.sleep(delay)

            label  = step_label(i, step)
            action = step["action"]
            t0     = time.perf_counter()

            if action == "wait":
                pass
            else:
                frame = ble_frame(_step_to_msg(step))
                await send_frame(client, frame)

            elapsed_ms = round((time.perf_counter() - t0) * 1000)
            results.append({"step": i, "label": label,
                            "action": action, "elapsed_ms": elapsed_ms})
            if verbose:
                print(f"  [✓] {label}  ({elapsed_ms}ms)")

    return {
        "scenario":    scenario["name"],
        "device":      device_address,
        "total_steps": len(results),
        "steps":       results,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def async_main() -> None:
    parser = argparse.ArgumentParser(description="Memoscape Bridge — real Halo BLE playback")
    parser.add_argument("scenario", nargs="?", help="Path to .json scenario file")
    parser.add_argument("--list-devices", action="store_true",
                        help="Scan for nearby Halo devices and exit")
    parser.add_argument("--device", metavar="ADDR",
                        help="BLE address of target Halo (skip auto-select)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print frames without connecting to a device")
    parser.add_argument("--settle", type=int, default=800, metavar="MS",
                        help="Fallback ms between steps when 'at' not set (default 800)")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args()

    if args.list_devices:
        devices = await scan_devices()
        if not devices:
            print("No Halo devices found nearby.")
        else:
            print(f"Found {len(devices)} Halo device(s):")
            for d in devices:
                print(f"  {d['address']}  {d['name']:20s}  RSSI {d['rssi']} dBm")
        return

    if not args.scenario:
        parser.print_help()
        sys.exit(1)

    path     = Path(args.scenario)
    scenario = json.loads(path.read_text())
    errors   = validate_scenario(scenario)
    if errors:
        print(f"INVALID scenario {path.name}:")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"Scenario: {scenario['name']}")
    if scenario.get("description"):
        print(f"  {scenario['description']}")
    print(f"  {len(scenario['steps'])} steps")

    if args.dry_run:
        dry_run_scenario(scenario, settle_ms=args.settle)
        return

    # Auto-discover device if not specified
    device_address = args.device
    if not device_address:
        devices = await scan_devices(timeout=6.0)
        if not devices:
            print("\nERROR: No Halo devices found. Use --device ADDR or --dry-run.")
            sys.exit(1)
        device_address = devices[0]["address"]
        print(f"Auto-selected: {device_address} ({devices[0]['name']})")

    report = await play_scenario(scenario, device_address,
                                 settle_ms=args.settle, verbose=not args.quiet)
    print(f"\nDone: {report['total_steps']}/{report['total_steps']} steps played on {device_address}")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
