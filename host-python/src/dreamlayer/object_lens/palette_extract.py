"""palette_extract.py — steal color from the world (Thread Lens, INNOVATION_SESSION
4.1). Reduce a deliberate snapshot to a small palette of dominant swatches, most
common first. Pure Pillow (already a dependency); the image itself is never kept —
only the palette. Device-side, `display/palette.lua: hex_to_ycbcr` paints these
into the dynamic palette bank."""
from __future__ import annotations

from io import BytesIO


def extract_palette(image: bytes, k: int = 6) -> list[str]:
    """Return up to ``k`` dominant colors as ``#rrggbb`` hex, most frequent first.
    Empty list on unreadable input."""
    try:
        from PIL import Image
        img = Image.open(BytesIO(image)).convert("RGB")
    except Exception:
        return []
    # small enough to be fast, large enough to be representative
    img = img.resize((64, 64))
    pal_img = img.convert("P", palette=Image.ADAPTIVE, colors=max(1, k))
    palette = pal_img.getpalette() or []
    counts = pal_img.getcolors() or []          # [(count, index), …]
    counts.sort(reverse=True)                    # most frequent first
    out: list[str] = []
    for _, idx in counts[:k]:
        base = idx * 3
        if base + 2 < len(palette):
            r, g, b = palette[base], palette[base + 1], palette[base + 2]
            out.append(f"#{r:02x}{g:02x}{b:02x}")
    return out
