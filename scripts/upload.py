#!/usr/bin/env python3
"""
scripts/upload.py
Deploy halo-lua/ to a paired Brilliant Labs Halo over BLE.

Usage:
    cd ~/dreamlayer
    uv run --extra hardware python scripts/upload.py            # auto-detect device
    uv run --extra hardware python scripts/upload.py --run      # upload + run main.lua
    uv run --extra hardware python scripts/upload.py --verify   # checksum verify after upload
    uv run --extra hardware python scripts/upload.py --ls       # list files on device
    uv run --extra hardware python scripts/upload.py --wipe     # wipe /dreamlayer/ on device first

Requirements:
    uv sync --extra hardware   (installs brilliant-ble, brilliant-msg)
"""

import argparse
import asyncio
import hashlib
import struct
import sys
import time
from pathlib import Path

try:
    import frame_sdk
    from frame_sdk import Frame
except ImportError:
    print("ERROR: frame_sdk not found.")
    print("Run: uv sync --extra hardware")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT  = Path(__file__).resolve().parent.parent
LUA_SRC    = REPO_ROOT / "halo-lua"
DEVICE_DIR = "/dreamlayer"          # root path on the Halo filesystem
MAIN_FILE  = "main.lua"            # entry point
EXCLUDE    = {".git", "__pycache__", ".DS_Store", "*.pyc", "*.swp"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def collect_files(src: Path) -> list[tuple[Path, str]]:
    """Return list of (local_path, device_path) for every .lua file under src."""
    results = []
    for f in sorted(src.rglob("*.lua")):
        rel = f.relative_to(src)
        # skip excluded patterns
        if any(part in EXCLUDE for part in rel.parts):
            continue
        device_path = f"{DEVICE_DIR}/{rel.as_posix()}"
        results.append((f, device_path))
    return results

def file_hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()

def human_size(n: int) -> str:
    return f"{n}B" if n < 1024 else f"{n/1024:.1f}KB"

# ---------------------------------------------------------------------------
# Core upload
# ---------------------------------------------------------------------------
async def upload(frame: Frame, files: list[tuple[Path, str]], wipe: bool, verify: bool):
    if wipe:
        print(f"Wiping {DEVICE_DIR}/ on device...")
        try:
            await frame.files.delete_directory(DEVICE_DIR)
        except Exception as e:
            print(f"  (wipe error, continuing): {e}")

    total = len(files)
    uploaded = 0
    failed = []

    for i, (local, device) in enumerate(files, 1):
        content = local.read_bytes()
        size_str = human_size(len(content))
        print(f"  [{i:2d}/{total}] {device}  ({size_str})", end="", flush=True)
        try:
            # Ensure parent directory exists
            parent = str(Path(device).parent)
            if parent != DEVICE_DIR:
                try:
                    await frame.files.make_directory(parent)
                except Exception:
                    pass  # already exists

            await frame.files.write_file(device, content)

            if verify:
                remote = await frame.files.read_file(device)
                local_md5  = hashlib.md5(content).hexdigest()
                remote_md5 = hashlib.md5(remote).hexdigest()
                if local_md5 != remote_md5:
                    print(f"  CHECKSUM MISMATCH: {device}")
                    failed.append(device)
                    continue

            uploaded += 1
            print(" ✓")
        except Exception as e:
            print(f" FAILED: {e}")
            failed.append(device)

    print()
    print(f"Uploaded {uploaded}/{total} files", end="")
    if failed:
        print(f"  ({len(failed)} failed)")
        for f in failed:
            print(f"    - {f}")
        return False
    else:
        print(" — all OK")
        return True

async def ls(frame: Frame):
    print(f"Files on device under {DEVICE_DIR}/:")
    try:
        entries = await frame.files.list_directory(DEVICE_DIR)
        for e in sorted(entries):
            print(f"  {e}")
    except Exception as e:
        print(f"  (error listing: {e})")

async def run_main(frame: Frame):
    entry = f"{DEVICE_DIR}/{MAIN_FILE}"
    print(f"Running {entry} on device...")
    try:
        # Execute main.lua and stream print() output for 5 seconds
        result = await asyncio.wait_for(
            frame.run_lua(f'require("{DEVICE_DIR.strip("/")}.main")', checked=True),
            timeout=5.0
        )
        if result:
            print("Device output:", result)
    except asyncio.TimeoutError:
        print("(running — no output within 5s, this is normal for the event loop)")
    except Exception as e:
        print(f"Run error: {e}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main():
    parser = argparse.ArgumentParser(description="Upload halo-lua/ to Halo glasses")
    parser.add_argument("--run",    action="store_true", help="Run main.lua after upload")
    parser.add_argument("--verify", action="store_true", help="Checksum verify after each file upload")
    parser.add_argument("--ls",     action="store_true", help="List files on device (no upload)")
    parser.add_argument("--wipe",   action="store_true", help="Delete /dreamlayer/ on device before upload")
    parser.add_argument("--dry-run",action="store_true", help="Show files that would be uploaded, then exit")
    args = parser.parse_args()

    files = collect_files(LUA_SRC)
    total_bytes = sum(f.stat().st_size for f, _ in files)

    if args.dry_run:
        print(f"Would upload {len(files)} files ({human_size(total_bytes)}) to {DEVICE_DIR}/")
        for local, device in files:
            print(f"  {device}  ({human_size(local.stat().st_size)})")
        return

    print(f"Connecting to Halo...")
    try:
        async with Frame() as frame:
            print(f"Connected: {await frame.get_battery_level()}% battery")
            print()

            if args.ls:
                await ls(frame)
                return

            print(f"Uploading {len(files)} files ({human_size(total_bytes)}) -> {DEVICE_DIR}/")
            if args.wipe:
                print("(--wipe enabled: clearing device directory first)")
            if args.verify:
                print("(--verify enabled: checksumming each file after upload)")
            print()

            ok = await upload(frame, files, wipe=args.wipe, verify=args.verify)

            if not ok:
                print("Upload had errors — not running.")
                sys.exit(1)

            if args.run:
                await run_main(frame)
            else:
                print(f"Done. To run on device:")
                print(f"  uv run --extra hardware python scripts/upload.py --run")

    except Exception as e:
        print(f"Connection failed: {e}")
        print()
        print("Checklist:")
        print("  1. Halo is charged and powered on")
        print("  2. Bluetooth is enabled on your Mac")
        print("  3. Halo is paired (System Settings > Bluetooth)")
        print("  4. No other app is connected to Halo")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
