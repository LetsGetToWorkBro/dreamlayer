"""demo/emissive.py — make a rendered HUD card look like real waveguide light.

The HUD renderer draws ink on black, masked to a disc. A Halo waveguide is an
*additive* display: lit pixels emit light, black emits nothing (it's see-through).
So to composite a card over first-person footage truthfully — the way it actually
looks through the glasses — we key the black to transparent and set each pixel's
alpha to its own brightness, then add an optional bloom for the glow. The result
drops onto a plate with a Screen/Add blend and reads as light on the world, not a
black card floating in front of it.

Pure image math over the *real* rendered card, so the demo never fakes the UI.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter


def emissive(img: Image.Image, gamma: float = 0.82, boost: float = 1.18) -> Image.Image:
    """Turn a rendered card (ink on black) into an emissive RGBA overlay: alpha
    becomes per-pixel luminance, so black → transparent and lit ink → opaque.
    `gamma` < 1 lifts the mid-tones (the waveguide's soft falloff); `boost`
    brightens the ink a touch."""
    rgba = np.asarray(img.convert("RGBA"), dtype=np.float32)
    r, g, b = rgba[..., 0], rgba[..., 1], rgba[..., 2]
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    alpha = np.clip(np.power(lum, gamma) * boost, 0.0, 1.0)
    out = rgba.copy()
    out[..., 3] = alpha * 255.0
    return Image.fromarray(out.astype(np.uint8), "RGBA")


def glow(img: Image.Image, radius: float = 7.0, strength: float = 0.55) -> Image.Image:
    """Add a soft bloom halo under the crisp ink — the emissive spill of a bright
    HUD element. `img` is an emissive RGBA overlay from `emissive()`."""
    blurred = np.asarray(img.filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32)
    blurred[..., 3] *= strength
    halo = Image.fromarray(np.clip(blurred, 0, 255).astype(np.uint8), "RGBA")
    return Image.alpha_composite(halo, img)     # bloom underneath, ink on top


def add_over(base: np.ndarray, overlay: Image.Image, center_xy, gain: float = 1.0) -> np.ndarray:
    """Additively composite an emissive RGBA `overlay` onto an RGB float array
    `base` (H,W,3), centered at pixel `center_xy`, scaled by `gain` (0-1 for a
    fade). Additive = the Screen/Add look of light on the world; clips softly."""
    ov = np.asarray(overlay.convert("RGBA"), dtype=np.float32)
    oh, ow = ov.shape[:2]
    cx, cy = int(center_xy[0]), int(center_xy[1])
    x0, y0 = cx - ow // 2, cy - oh // 2
    bh, bw = base.shape[:2]
    # clip to the base bounds
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    dx1, dy1 = min(bw, x0 + ow), min(bh, y0 + oh)
    if dx1 <= dx0 or dy1 <= dy0:
        return base
    ow_c, oh_c = dx1 - dx0, dy1 - dy0
    ink = ov[sy0:sy0 + oh_c, sx0:sx0 + ow_c, :3]
    a = (ov[sy0:sy0 + oh_c, sx0:sx0 + ow_c, 3:4] / 255.0) * float(gain)
    base[dy0:dy1, dx0:dx1, :] += ink * a
    return base
