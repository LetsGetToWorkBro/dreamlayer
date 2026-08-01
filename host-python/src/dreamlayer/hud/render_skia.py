"""hud/render_skia.py — a Skia RASTERIZER SKETCH. Not a card renderer, and not
registerable as one.

Both of those are corrections to what this file used to claim, and both were
checked rather than reasoned about:

  * IT DOES NOT FIT `CardRenderer.register`. The old docstring said it "exposes
    it behind the SAME `fn(card)->PIL.Image` shape `CardRenderer.register(
    card_type, fn)` already accepts, so it wires in with zero core edits."
    `register`'s own docstring says `fn(draw, card)` — two arguments, drawing
    onto a canvas that already exists, return value ignored — and `render()`
    calls it that way. Following the old instructions raises on the first card:

        TypeError: _render() takes 1 positional argument but 2 were given

  * IT DRAWS A STUB. `_skia_blank` clears to black and writes `card["title"]`,
    a key HUD cards do not have (they carry eyebrow / primary / detail /
    footer). Its own docstring calls itself "the safe seam demonstration". So
    even with the arity fixed, wiring it would replace every working card with
    a black square — below the floor this repo already holds an optional
    dependency to: never return less than its own fallback.

What it IS: a working demonstration that skia-python can rasterize to a PIL
image at the HUD's size, kept because the rasterizing half is real and someone
finishing this feature would start from it. `make_skia_renderer(fallback_fn)`
returns `fn(card) -> PIL.Image`, which is a fine shape for a WHOLE-CARD
rasterizer — it is simply not the shape the per-card-type dispatch wants.

Finishing it means two things this file does not do: drawing the actual card
layout, and adapting to `fn(draw, card)` (or giving `CardRenderer` a
whole-image renderer slot, which it does not have today).

skia-python is optional (extras group `platform`). When absent — or when a Skia
draw raises — the returned callable delegates straight to the supplied PIL
fallback, so nothing regresses either way.
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
    """Return a `fn(card) -> PIL.Image` whole-image rasterizer.

    NOT a `CardRenderer.register` callback — that hook is `fn(draw, card)` and
    passing this to it raises TypeError on the first card. See the module
    docstring; this signature is deliberate and the mismatch is the finding.

    Uses Skia when available, else (or on any Skia error) delegates to
    `fallback_fn` — normally the host's existing PIL `CardRenderer.render`. The
    HUD output is unchanged in the fallback path.
    """
    sz = size or _DEFAULT_SIZE

    def _render(card: dict):
        if _HAS_SKIA:
            try:
                return _skia_blank(card, sz)
            except Exception as exc:
                log.warning("[render_skia] skia draw failed: %s; PIL fallback", exc)
        return fallback_fn(card)

    return _render
