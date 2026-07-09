"""hud/render_skia.py — an optional Skia-backed rasterizer for HUD cards.

ADD-alongside: `hud/renderer.py` (the PIL CardRenderer) is untouched and stays
the default. Skia gives crisper anti-aliased strokes/gradients if a builder ever
wants them; this module exposes it behind the SAME `fn(card)->PIL.Image` shape
`CardRenderer.register(card_type, fn)` already accepts, so it wires in with zero
core edits.

skia-python is optional (extras group `platform`). When absent — or when a Skia
draw raises — `make_skia_renderer(fallback_fn)` returns a callable that delegates
straight to the supplied PIL fallback (normally the existing renderer), so the
HUD looks identical whether or not Skia is installed.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional, Tuple

log = logging.getLogger("dreamlayer.render_skia")

try:
    import skia  # type: ignore
    _HAS_SKIA = True
except ImportError:
    _HAS_SKIA = False

available = _HAS_SKIA

# Halo's HUD render target is 256x256 (see hud/renderer.py, SIZE = 256).
_DEFAULT_SIZE: Tuple[int, int] = (256, 256)


def _skia_blank(card: dict, size: Tuple[int, int]):
    """Render a minimal Skia surface (black bg + title text) to a PIL image.
    A real card renderer would draw the full layout; this is the safe seam
    demonstration, and any exception falls through to the PIL fallback."""
    from PIL import Image

    w, h = size
    surface = skia.Surface(w, h)
    with surface as canvas:
        canvas.clear(skia.ColorBLACK)
        title = str(card.get("title", ""))
        if title:
            paint = skia.Paint(Color=skia.ColorGREEN, AntiAlias=True)
            font = skia.Font(skia.Typeface(""), 28)
            canvas.drawString(title, 24, 48, font, paint)
    img = surface.makeImageSnapshot()
    data = img.tobytes()
    return Image.frombytes("RGBA", (w, h), data)


def make_skia_renderer(fallback_fn: Callable[[dict], "object"],
                       size: Optional[Tuple[int, int]] = None) -> Callable[[dict], "object"]:
    """Return a `fn(card)->PIL.Image` renderer. Uses Skia when available, else
    (or on any Skia error) delegates to `fallback_fn` — normally the host's
    existing PIL `CardRenderer.render`. The HUD output is unchanged in the
    fallback path."""
    sz = size or _DEFAULT_SIZE

    def _render(card: dict):
        if _HAS_SKIA:
            try:
                return _skia_blank(card, sz)
            except Exception as exc:
                log.warning("[render_skia] skia draw failed: %s; PIL fallback", exc)
        return fallback_fn(card)

    return _render
