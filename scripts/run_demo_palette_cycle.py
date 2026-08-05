#!/usr/bin/env python3
"""scripts/run_demo_palette_cycle.py — motion by recolouring, not redrawing.

Drives the real display/palette_cycle.lua primitive over an aurora ramp and
renders a filmstrip: each row is one frame, the columns are a band painted
once with the four sky slots. Nothing in the band is ever redrawn — only the
four palette slots are reassigned per frame — yet the colour visibly flows.
That is the whole trick: rich continuous motion on a 4bpp panel at the cost
of four assign_color_ycbcr calls per frame and zero geometry.

Run:  python scripts/run_demo_palette_cycle.py
Writes out/palette_cycle/flow.png (needs lupa + Pillow; prints hex otherwise).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LUA_ROOT = REPO_ROOT / "halo-lua"
OUT = REPO_ROOT / "out" / "palette_cycle"

# an aurora ramp: deep teal -> mint -> cyan -> violet, cycled around the ring
RAMP = [0x0E3B32, 0x2CC79A, 0x59E0D6, 0x7A6BE0]
SLOTS = 4
FRAMES = 48
BAND_REPEAT = 16          # how many times the 4-slot band tiles across the width
CELL = 6                  # px per slot cell
ROW_H = 6                 # px per frame row


def ycbcr_to_rgb(y: float, cb: float, cr: float) -> tuple[int, int, int]:
    # invert palette.lua hex_to_ycbcr (BT.601 full-range, 0-1023 = x4)
    y, cb, cr = y / 4.0, cb / 4.0, cr / 4.0
    r = y + 1.402 * (cr - 128)
    g = y - 0.344136 * (cb - 128) - 0.714136 * (cr - 128)
    b = y + 1.772 * (cb - 128)
    return tuple(max(0, min(255, round(v))) for v in (r, g, b))


def main() -> int:
    try:
        from lupa import lua53
    except ImportError:
        print("lupa not installed — skipping (the primitive itself is tested "
              "in test_palette_cycle.py).")
        return 0

    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;" .. package.path')
    rt.execute("""
    _pal = {}
    frame = { display = {
      assign_color_ycbcr = function(slot, y, cb, cr) _pal[slot] = { y, cb, cr } end,
    }}
    _p  = require("display/palette")
    _pc = require("display/palette_cycle")
    """)
    for i in range(1, SLOTS + 1):
        rt.execute(f'_p.reserve_dynamic("s{i}", 0x000000, {i})')
    ramp_lua = ", ".join(str(c) for c in RAMP)
    rt.execute(f"_cy = _pc.new({{'s1','s2','s3','s4'}}, {{ {ramp_lua} }}, "
               f"{{ period_ms = 4000, smooth = true }})")

    rows: list[list[tuple[int, int, int]]] = []
    for f in range(FRAMES):
        rt.execute(f"_pal = {{}}; _cy:tick({round(f / FRAMES * 4000)})")
        slot_rgb = []
        for i in range(1, SLOTS + 1):
            y, cb, cr = (int(v) for v in rt.eval(f"_pal[{i}]").values())
            slot_rgb.append(ycbcr_to_rgb(y, cb, cr))
        rows.append(slot_rgb * BAND_REPEAT)

    print(f"Palette cycling — {FRAMES} frames, {SLOTS} slots, band never redrawn.")
    print("frame 0 slots:", [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in rows[0][:4]])
    mid = FRAMES // 2
    print(f"frame {mid} slots:", [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in rows[mid][:4]])
    assert rows[0][:4] != rows[mid][:4], "the palette should have flowed"

    try:
        from PIL import Image
    except ImportError:
        print("Pillow not installed — filmstrip skipped, values above prove the flow.")
        return 0

    width = SLOTS * BAND_REPEAT * CELL
    img = Image.new("RGB", (width, FRAMES * ROW_H), (0, 0, 0))
    px = img.load()
    for fy, row in enumerate(rows):
        for cx, rgb in enumerate(row):
            for dx in range(CELL):
                for dy in range(ROW_H):
                    px[cx * CELL + dx, fy * ROW_H + dy] = rgb
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / "flow.png")
    print(f"wrote {OUT / 'flow.png'} — read top-to-bottom, the band scrolls "
          "without a single pixel being redrawn.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
