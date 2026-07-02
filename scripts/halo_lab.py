#!/usr/bin/env python3
"""
scripts/halo_lab.py
DreamLayer Lab — run scripted emulator scenarios, capture frames, export GIF + contact sheet.

Usage:
    cd ~/dreamlayer
    uv run python scripts/halo_lab.py scripts/scenarios/mindblow_demo.json
    uv run python scripts/halo_lab.py scripts/scenarios/  # run all scenarios
    uv run python scripts/halo_lab.py --list
    uv run python scripts/halo_lab.py --validate scripts/scenarios/mindblow_demo.json

Outputs per scenario in out/<scenario_name>/:
    00_step_label.png    one PNG per step
    contact_sheet.png    all steps tiled
    timeline.gif         animated walkthrough
    report.json          pass/fail + lit pixels + timing

Requirements:
    uv sync  (Pillow already in pyproject.toml)
    halo_emulator on PYTHONPATH (from brilliant_sdk) -- only needed for run_scenario()
"""

import argparse
import json
import struct
import sys
import time
import io
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("ERROR: Pillow not found. Run: uv sync")
    sys.exit(1)

# NOTE: halo_emulator is intentionally NOT imported at module level.
# It is only imported inside run_scenario() so that all pure functions
# (validate_scenario, make_gif, make_contact_sheet, etc.) remain importable
# and fully testable without the emulator installed.

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
LUA_SRC   = REPO_ROOT / "halo-lua"
OUT_ROOT  = REPO_ROOT / "out"
SCENARIOS = REPO_ROOT / "scripts" / "scenarios"

# ---------------------------------------------------------------------------
# BLE framing
# ---------------------------------------------------------------------------
def ble_frame(msg: dict) -> bytes:
    raw = json.dumps(msg).encode()
    return struct.pack(">I", len(raw) + 4) + raw

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
CARD_REQUIRED: dict[str, list[str]] = {
    "ObjectRecallCard":     ["object", "place", "last_seen", "confidence"],
    "CommitmentRecallCard": ["person", "task", "due", "confidence"],
    "ProactiveMemoryCard":  ["summary"],
    "PersonContextCard":    ["person", "headline"],
    "SavedMemoryCard":      ["primary"],
    "ErrorCard":            ["primary"],
    "LiveCaptionCard":      ["translation"],
    "LowConfidenceCard":    ["primary"],
    "QueryListeningCard":   [],
    "PrivacyVeilCard":    [],
    "LoadingCard":          [],
}

VALID_ACTIONS  = {"card", "command", "button", "imu_tap", "connect", "disconnect", "wait"}
BUTTON_VALUES  = {"single", "double", "long"}
COMMAND_VALUES = {"ask", "pause", "loading", "resume"}


def validate_scenario(scenario: dict) -> list[str]:
    errors: list[str] = []
    if "name" not in scenario:
        errors.append("missing 'name'")
    if "steps" not in scenario or not isinstance(scenario["steps"], list):
        errors.append("missing or invalid 'steps'")
        return errors
    for i, step in enumerate(scenario["steps"]):
        p = f"step[{i}]"
        if "action" not in step:
            errors.append(f"{p}: missing 'action'")
            continue
        action = step["action"]
        if action not in VALID_ACTIONS:
            errors.append(f"{p}: unknown action '{action}'")
            continue
        if action == "card":
            ct = step.get("card_type")
            if ct is None:
                errors.append(f"{p}: 'card' action missing 'card_type'")
            elif ct not in CARD_REQUIRED:
                errors.append(f"{p}: unknown card_type '{ct}'")
            else:
                for req in CARD_REQUIRED[ct]:
                    if req not in step.get("payload", {}):
                        errors.append(f"{p}: {ct} missing required payload field '{req}'")
        elif action == "button":
            if step.get("kind") not in BUTTON_VALUES:
                errors.append(f"{p}: button 'kind' must be one of {sorted(BUTTON_VALUES)}")
        elif action == "command":
            if step.get("kind") not in COMMAND_VALUES:
                errors.append(f"{p}: command 'kind' must be one of {sorted(COMMAND_VALUES)}")
    return errors


# ---------------------------------------------------------------------------
# Step execution
# ---------------------------------------------------------------------------
def step_label(i: int, step: dict) -> str:
    action = step["action"]
    if action == "card":
        ct = step.get("card_type", "?")
        p  = step.get("payload", {})
        detail = (p.get("object") or p.get("person") or p.get("summary")
                  or p.get("primary") or ct)
        return f"{i:02d}_{ct.replace('Card','').lower()}_{detail.lower().replace(' ','_')[:20]}"
    if action == "button":
        return f"{i:02d}_btn_{step.get('kind','?')}"
    if action == "command":
        return f"{i:02d}_cmd_{step.get('kind','?')}"
    return f"{i:02d}_{action}"


def execute_step(emu, step: dict) -> None:
    action = step["action"]
    if action in ("connect", "disconnect"):
        emu.inject_bluetooth_data(ble_frame({"t": action}))
    elif action == "card":
        payload = {**step.get("payload", {}), "type": step["card_type"]}
        emu.inject_bluetooth_data(ble_frame({"t": "card", "payload": payload}))
    elif action == "command":
        emu.inject_bluetooth_data(ble_frame({"t": "command", "kind": step["kind"]}))
    elif action == "button":
        kind = step["kind"]
        if kind == "single":
            emu.inject_button_single()
        elif kind == "double":
            emu.inject_button_double()
        elif kind == "long":
            emu.inject_button_long()
    elif action == "imu_tap":
        emu.inject_imu_tap()
    # "wait" timing handled externally by settle_ms


# ---------------------------------------------------------------------------
# Contact sheet
# ---------------------------------------------------------------------------
def make_contact_sheet(frames, scenario_name: str, cols: int = 4):
    if not frames:
        return Image.new("RGB", (256, 256), (10, 10, 10))
    tw, th  = 256, 256
    label_h = 24
    pad     = 8
    rows    = (len(frames) + cols - 1) // cols
    W = cols * (tw + pad) + pad
    H = rows * (th + label_h + pad) + pad + 36
    sheet = Image.new("RGB", (W, H), (12, 12, 12))
    draw  = ImageDraw.Draw(sheet)
    draw.text((pad, 8), f"DreamLayer Lab \u2014 {scenario_name}", fill=(160, 160, 160))
    for idx, (label, img) in enumerate(frames):
        col = idx % cols
        row = idx // cols
        x = pad + col * (tw + pad)
        y = 36 + pad + row * (th + label_h + pad)
        draw.rectangle([x-1, y-1, x+tw, y+th], outline=(35, 35, 35))
        sheet.paste(img.convert("RGB").resize((tw, th)), (x, y))
        draw.text((x, y + th + 4), label[3:40], fill=(100, 100, 100))
    return sheet


# ---------------------------------------------------------------------------
# GIF export
# ---------------------------------------------------------------------------
def make_gif(frames, step_ms: int = 1200, hold_ms: int = 2500) -> bytes:
    if not frames:
        return b""
    gframes, durations = [], []
    for i, (_, img) in enumerate(frames):
        p = img.convert("RGB").resize((256, 256)).quantize(
            colors=64, method=Image.Quantize.MEDIANCUT)
        gframes.append(p)
        durations.append(hold_ms if i == len(frames) - 1 else step_ms)
    buf = io.BytesIO()
    gframes[0].save(buf, format="GIF", save_all=True, append_images=gframes[1:],
                    duration=durations, loop=0, optimize=False)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Run one scenario  (halo_emulator imported HERE, not at module level)
# ---------------------------------------------------------------------------
def run_scenario(scenario: dict, lua_src: Path, out_dir: Path,
                 settle_ms: int = 600, verbose: bool = True) -> dict:
    try:
        from halo_emulator import HaloEmulator
    except ImportError:
        print("ERROR: halo_emulator not found.")
        print("Clone brilliant_sdk and install: pip install -e packages/halo-emulator")
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    steps   = scenario["steps"]
    frames  = []
    results = []

    with HaloEmulator(sandbox_dir=str(lua_src)) as emu:
        emu.load_directory(str(lua_src))
        emu.start("main.lua")
        emu.wait(0.35)

        for i, step in enumerate(steps):
            t0 = time.perf_counter()
            execute_step(emu, step)
            emu.wait(settle_ms / 1000.0)
            elapsed_ms = round((time.perf_counter() - t0) * 1000)

            img   = emu.get_framebuffer()
            lit   = sum(1 for px in img.convert("RGB").getdata() if px != (0, 0, 0))
            label = step_label(i, step)

            img.save(out_dir / f"{label}.png")
            frames.append((label, img))
            results.append({
                "step":        i,
                "action":      step["action"],
                "label":       label,
                "lit_pixels":  lit,
                "duration_ms": elapsed_ms,
            })

            status = "\u2713" if lit > 0 else "BLANK"
            if verbose:
                print(f"  [{status}] {label}  ({lit} lit px, {elapsed_ms}ms)")

    sheet = make_contact_sheet(frames, scenario["name"])
    sheet.save(out_dir / "contact_sheet.png")

    gif_bytes = make_gif(frames)
    (out_dir / "timeline.gif").write_bytes(gif_bytes)

    passed = sum(1 for r in results if r["lit_pixels"] > 0)
    report = {
        "scenario":          scenario["name"],
        "description":       scenario.get("description", ""),
        "total_steps":       len(results),
        "steps_with_output": passed,
        "steps_blank":       len(results) - passed,
        "gif_frames":        len(frames),
        "gif_bytes":         len(gif_bytes),
        "steps":             results,
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2))

    if verbose:
        print(f"  Contact sheet: {sheet.size[0]}\u00d7{sheet.size[1]}px")
        print(f"  GIF: {len(gif_bytes):,} bytes, {len(frames)} frames")
        print(f"  Result: {passed}/{len(results)} steps with output")

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="DreamLayer Lab \u2014 emulator scenario runner")
    parser.add_argument("scenario", nargs="?",
                        help="Path to .json scenario file or directory")
    parser.add_argument("--list",     action="store_true", help="List available scenarios")
    parser.add_argument("--validate", metavar="FILE",
                        help="Validate a scenario file without running")
    parser.add_argument("--settle",   type=int, default=600, metavar="MS",
                        help="ms to wait after each step (default 600)")
    parser.add_argument("--lua",      default=str(LUA_SRC), metavar="DIR",
                        help="Path to halo-lua directory")
    parser.add_argument("--out",      default=str(OUT_ROOT), metavar="DIR",
                        help="Output root directory")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args()

    lua_src  = Path(args.lua)
    out_root = Path(args.out)

    if args.list:
        files = sorted(SCENARIOS.glob("*.json"))
        if not files:
            print(f"No scenarios found in {SCENARIOS}")
        else:
            print(f"Available scenarios ({SCENARIOS}):")
            for f in files:
                s    = json.loads(f.read_text())
                desc = s.get("description", "")
                print(f"  {f.stem:30s}  {desc}")
        return

    if args.validate:
        path     = Path(args.validate)
        scenario = json.loads(path.read_text())
        errors   = validate_scenario(scenario)
        if errors:
            print(f"INVALID: {path.name}")
            for e in errors:
                print(f"  {e}")
            sys.exit(1)
        else:
            print(f"OK: {path.name} \u2014 {len(scenario['steps'])} steps")
        return

    if not args.scenario:
        parser.print_help()
        sys.exit(1)

    target = Path(args.scenario)
    if target.is_dir():
        scenario_files = sorted(target.glob("*.json"))
    elif target.is_file():
        scenario_files = [target]
    else:
        print(f"ERROR: {target} not found")
        sys.exit(1)

    if not scenario_files:
        print(f"No .json files found in {target}")
        sys.exit(1)

    all_passed = True
    for sf in scenario_files:
        scenario = json.loads(sf.read_text())
        errors   = validate_scenario(scenario)
        if errors:
            print(f"\nSKIPPED {sf.name} (invalid):")
            for e in errors:
                print(f"  {e}")
            all_passed = False
            continue

        out_dir = out_root / scenario["name"]
        print(f"\n{'='*60}")
        print(f"Scenario: {scenario['name']}")
        if scenario.get("description"):
            print(f"  {scenario['description']}")
        print(f"  {len(scenario['steps'])} steps  \u2192  {out_dir}")
        print()

        report = run_scenario(scenario, lua_src, out_dir,
                              settle_ms=args.settle, verbose=not args.quiet)
        if report["steps_blank"] > 0:
            all_passed = False
            print(f"  WARNING: {report['steps_blank']} blank step(s)")

    print()
    if all_passed:
        print("All scenarios passed.")
    else:
        print("Some scenarios had issues.")
        sys.exit(1)


if __name__ == "__main__":
    main()
