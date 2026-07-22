#!/usr/bin/env python3
"""make_dock_icon.py — the macOS Dock-tile variant of the app icon.

Why this exists (separate from the full-bleed app_icon.png):

The shipped icon (packaging/icon.png → app_icon.png) is deliberately FULL-BLEED
— edge-to-edge art, no transparent margin — because the app *bundle* icon is
masked by macOS itself: Finder and the at-rest Dock apply their own squircle, so
a full square reads as a clean rounded icon there (see test_app_icon.py).

But one runtime path does NOT get that system mask: while the panel window is
open the app becomes a REGULAR app and stamps its Dock tile via
`NSApp().setApplicationIconImage_()`. That API shows the bitmap you hand it AS
IS — no squircle, no safe-area inset — so the full-bleed square renders
edge-to-edge and visibly larger than every neighbouring Dock icon (the "icon
goes big when you open it" report). The fix is to hand THAT call an image that
already has the macOS shape baked in: a squircle body inset inside a transparent
safe area, sized like a real app icon.

This script bakes exactly that from the same source art, so the two stay in
sync. Run it whenever packaging/icon.png changes:

    python packaging/make_dock_icon.py

Output: src/dreamlayer/ai_brain/server/assets/app_icon_dock.png (1024x1024,
transparent corners, ~80% squircle body — the Apple app-icon grid).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

# The Apple app-icon grid (Big Sur+): on a 1024 canvas the rounded body is
# ~824 wide (≈100 px transparent margin each side) with continuous ("squircle")
# corners. We approximate the squircle with a superellipse of exponent 5 — at
# Dock size it is visually indistinguishable from Apple's and trivially exact.
CANVAS = 1024
MARGIN = 100                       # transparent safe area each side
SS = 4                             # supersample for a clean anti-aliased edge
SQUIRCLE_N = 5.0                   # superellipse exponent (≈ Apple's squircle)


def _squircle_mask(size: int, margin: int, n: float) -> Image.Image:
    """An 'L' alpha mask: opaque inside the centred superellipse body, fully
    transparent outside (and in the safe-area margin). Supersampled + resized
    down so the curved edge is smooth."""
    big = size * SS
    m = margin * SS
    a = (big - 2 * m) / 2.0                     # body half-extent
    cx = cy = big / 2.0
    ys, xs = np.mgrid[0:big, 0:big]
    # |x/a|^n + |y/a|^n <= 1  → inside the squircle
    d = (np.abs((xs - cx) / a) ** n) + (np.abs((ys - cy) / a) ** n)
    mask = (d <= 1.0).astype(np.uint8) * 255
    return Image.fromarray(mask, "L").resize((size, size), Image.LANCZOS)


def build(src: Path, dst: Path) -> None:
    art = Image.open(src).convert("RGBA")
    if art.size != (CANVAS, CANVAS):
        art = art.resize((CANVAS, CANVAS), Image.LANCZOS)
    body = CANVAS - 2 * MARGIN
    inner = art.resize((body, body), Image.LANCZOS)          # inset the art
    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    canvas.paste(inner, (MARGIN, MARGIN), inner)
    # clip the inset art to the squircle, so the corners are transparent
    mask = _squircle_mask(CANVAS, MARGIN, SQUIRCLE_N)
    r, g, b, a = canvas.split()
    a = Image.composite(a, Image.new("L", (CANVAS, CANVAS), 0), mask)
    Image.merge("RGBA", (r, g, b, a)).save(dst)
    print(f"wrote {dst} ({CANVAS}x{CANVAS}, squircle body {body}px, margin {MARGIN}px)")


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    src = here / "icon.png"
    dst = (here.parent / "src" / "dreamlayer" / "ai_brain" / "server"
           / "assets" / "app_icon_dock.png")
    build(src, dst)
