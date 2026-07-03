"""demo/plate.py — a tasteful stand-in for first-person footage.

The demo composites the *real* HUD over a background "plate." In production that
plate is your actual POV video; for a self-contained preview (and so the export
tool has something to render against in tests) this synthesizes a calm, dark
scene — a soft light band like a window across a dim room, a vignette, and faint
grain — so the emissive HUD reads as light on a world rather than on a void.

Deterministic given a seed, so previews are reproducible.
"""
from __future__ import annotations

import numpy as np
from PIL import Image


def synth_plate(size, seed: int = 7) -> Image.Image:
    """A dim, cinematic POV stand-in at `size` = (w, h)."""
    w, h = int(size[0]), int(size[1])
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

    # base: cool near-black, warming slightly toward the lower third (a floor)
    base = np.zeros((h, w, 3), dtype=np.float32)
    depth = yy / max(1, h - 1)
    base[..., 0] = 14 + depth * 10          # R
    base[..., 1] = 18 + depth * 12          # G
    base[..., 2] = 24 + depth * 14          # B  (a touch of teal in the dark)

    # a soft horizontal light band ~40% down — a window / far light source
    band = np.exp(-((depth - 0.38) ** 2) / (2 * 0.03 ** 2))
    base += band[..., None] * np.array([26, 30, 34], dtype=np.float32)

    # vignette toward the corners
    cx, cy = w / 2.0, h / 2.0
    rad = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2)
    vig = np.clip(1.0 - 0.55 * np.power(rad, 2.2), 0.25, 1.0)
    base *= vig[..., None]

    # faint film grain
    base += rng.normal(0, 2.4, (h, w, 3)).astype(np.float32)

    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB")
