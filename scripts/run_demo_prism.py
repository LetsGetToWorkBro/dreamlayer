#!/usr/bin/env python3
"""scripts/run_demo_prism.py — render the Prism Lens kaleidoscope.

Drives the real display/prism.lua over a few frames and rasterises them to
out/prism/kaleidoscope.png, resolving each arm's colour from the live
palette-cycled slots. Read left-to-right: the geometry turns while the
colours flow through the arms.

Run:  python scripts/run_demo_prism.py   (needs lupa + Pillow)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LUA_ROOT = REPO_ROOT / "halo-lua"
OUT = REPO_ROOT / "out" / "prism"

FRAMES = [0, 900, 1800]      # ms — three moments of the cycle
SIZE = 256


def ycbcr_to_rgb(y, cb, cr):
    y, cb, cr = y / 4.0, cb / 4.0, cr / 4.0
    r = y + 1.402 * (cr - 128)
    g = y - 0.344136 * (cb - 128) - 0.714136 * (cr - 128)
    b = y + 1.772 * (cb - 128)
    return tuple(max(0, min(255, round(v))) for v in (r, g, b))


def main() -> int:
    try:
        from lupa import lua53
    except ImportError:
        print("lupa not installed — skipping (renderer is tested in test_prism.py).")
        return 0
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Pillow not installed — skipping the image.")
        return 0

    rt = lua53.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{LUA_ROOT}/?.lua;" .. package.path')
    rt.execute("""
    _calls = {}
    frame = { display = {
      line = function(...) _calls[#_calls+1] = {"line", ...} end,
      circle = function(...) _calls[#_calls+1] = {"circle", ...} end,
      assign_color_ycbcr = function(...) _calls[#_calls+1] = {"pal", ...} end,
      clear = function() end, show = function() end,
    }}
    require("display/dream_renderer")
    _pr = require("display/prism")
    _pr.reset()
    _pr.on_prism({ active = 1, intensity = 80, symmetry = 8 })
    """)

    strip = Image.new("RGB", (SIZE * len(FRAMES), SIZE), (0, 0, 0))
    for i, now in enumerate(FRAMES):
        rt.execute(f"_calls = {{}}; _pr.draw({now})")
        calls = rt.eval("_calls")
        pal = {}
        img = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        for c in calls.values():
            kind = c[1]
            if kind == "pal":
                pal[int(c[2])] = ycbcr_to_rgb(int(c[3]), int(c[4]), int(c[5]))
            elif kind == "line":
                col = pal.get(int(c[6]), (200, 200, 200))
                draw.line([int(c[2]), int(c[3]), int(c[4]), int(c[5])],
                          fill=col, width=2)
            elif kind == "circle":
                col = pal.get(int(c[5]), (255, 255, 255))
                x, y, r = int(c[2]), int(c[3]), int(c[4])
                draw.ellipse([x - r, y - r, x + r, y + r], fill=col)
        strip.paste(img, (i * SIZE, 0))

    OUT.mkdir(parents=True, exist_ok=True)
    strip.save(OUT / "kaleidoscope.png")
    print(f"wrote {OUT / 'kaleidoscope.png'} — three moments of the Prism Lens; "
          "the arms turn while the palette flows through them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
