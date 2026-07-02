"""dream/sprite_bridge.py — 16-color PNG → TxSprite → BLE bitmap stream.

Wraps the brilliant-msg TxSprite pipeline to send generated 4-bit indexed
PNG frames to the glasses display.

Pipeline
--------
    16-color PIL Image
      → quantize to 4bpp indexed PNG  (Pillow)
      → TxSprite.from_indexed_png_bytes()
      → sprite.pack()  (brilliant-msg framing)
      → bridge.send_raw({"t": "sprite", "data": ...})
      → Lua: host_comm receives, calls frame.display.bitmap()

Fallback
--------
If brilliant-msg is not installed, SpriteBridge degrades silently —
all sprite sends become no-ops and a warning is logged once.

Usage
-----
    sb = SpriteBridge(bridge)
    sb.queue_image(pil_image)           # non-blocking, stores pending frame
    await sb.flush_pending()            # sends if a pending frame exists
"""
from __future__ import annotations

import io
import logging
import struct
from typing import Optional

log = logging.getLogger(__name__)

# Try to import brilliant-msg; degrade gracefully if absent
try:
    from brilliant_msg import TxSprite  # type: ignore
    _HAS_BRILLIANT_MSG = True
except ImportError:
    _HAS_BRILLIANT_MSG = False
    log.warning(
        "brilliant-msg not installed — SpriteBridge will no-op. "
        "pip install brilliant-msg to enable bitmap streaming."
    )

# Try Pillow
try:
    from PIL import Image  # type: ignore
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


MAX_SPRITE_W = 256
MAX_SPRITE_H = 256
N_COLORS     = 16


class SpriteBridge:
    """Converts PIL Images to TxSprite payloads and sends them over BLE."""

    def __init__(self, bridge) -> None:
        self._bridge = bridge
        # (packed TxSprite bytes, msg type, x, y) or None
        self._pending: Optional[tuple] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def queue_image(self, image: "Image.Image", x: int = 1, y: int = 1,
                    msg_type: str = "sprite") -> bool:
        """Quantize image to 4bpp and queue for next flush_pending().

        x/y anchor the sprite on the display (SynesthesiaCard v2 sends
        y=128 for its bottom-half gesture; avatars send their placement).
        Returns True if queued, False if degraded (no brilliant-msg / PIL).
        """
        if not _HAS_PIL or not _HAS_BRILLIANT_MSG:
            return False

        try:
            png_bytes = _to_4bpp_png(image)
            sprite    = TxSprite.from_indexed_png_bytes(png_bytes)
            self._pending = (sprite.pack(), msg_type, x, y)
            return True
        except Exception as exc:
            log.warning("SpriteBridge.queue_image error: %s", exc)
            return False

    async def flush_pending(self) -> bool:
        """Send the pending sprite frame if one exists. Fire-and-forget."""
        if self._pending is None:
            return False
        data, msg_type, x, y = self._pending
        self._pending = None
        try:
            self._bridge.send_raw({"t": msg_type, "data": data, "x": x, "y": y})
            return True
        except Exception as exc:
            log.warning("SpriteBridge.flush_pending error: %s", exc)
            return False

    def queue_from_bytes(self, png_bytes: bytes, x: int = 1, y: int = 1,
                         msg_type: str = "sprite") -> bool:
        """Queue a pre-encoded 4bpp indexed PNG directly."""
        if not _HAS_BRILLIANT_MSG:
            return False
        try:
            sprite = TxSprite.from_indexed_png_bytes(png_bytes)
            self._pending = (sprite.pack(), msg_type, x, y)
            return True
        except Exception as exc:
            log.warning("SpriteBridge.queue_from_bytes error: %s", exc)
            return False

    @property
    def has_pending(self) -> bool:
        return self._pending is not None


# ---------------------------------------------------------------------------
# Gestural sprite rendering (SynesthesiaCard v2, Halo Cinema v1)
# ---------------------------------------------------------------------------

GESTURE_SIZE = 128    # 128×128 @ 4bpp ≈ 4KB packed — well under 8KB budget


def render_gesture(sprite) -> Optional["Image.Image"]:
    """Render a GesturalSprite (dominant color + 3 abstract shapes) to a
    128×128 image for the bottom half of SynesthesiaCard v2.

    Shapes draw as outlines in the dominant color with one dim echo each,
    matching the Air-tier material rules (never solid fills).
    """
    if not _HAS_PIL:
        return None
    from PIL import ImageDraw

    img = Image.new("RGB", (GESTURE_SIZE, GESTURE_SIZE), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    dom = sprite.dominant
    color = ((dom >> 16) & 0xFF, (dom >> 8) & 0xFF, dom & 0xFF)
    dim   = tuple(c // 3 for c in color)

    for s in sprite.shapes[:3]:
        kind, x, y, size = s["kind"], s["x"], s["y"], s["size"]
        half = size // 2
        if kind == "circle":
            draw.ellipse([x - half, y - half, x + half, y + half], outline=color, width=2)
            draw.ellipse([x - half - 4, y - half - 4, x + half + 4, y + half + 4],
                         outline=dim, width=1)
        elif kind == "line":
            draw.line([x - half, y, x + half, y], fill=color, width=2)
            draw.line([x - half, y + 4, x + half, y + 4], fill=dim, width=1)
        elif kind == "rect":
            draw.rectangle([x - half, y - half // 2, x + half, y + half // 2],
                           outline=color, width=2)
        else:  # triangle
            pts = [(x, y - half), (x + half, y + half), (x - half, y + half)]
            draw.polygon(pts, outline=color)
            draw.polygon([(px, py + 3) for px, py in pts], outline=dim)
    return img


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_4bpp_png(image: "Image.Image") -> bytes:
    """Quantize a PIL Image to 16 colors and encode as indexed PNG."""
    img = image.convert("RGB")
    # Resize to fit display if needed (preserve aspect)
    if img.width > MAX_SPRITE_W or img.height > MAX_SPRITE_H:
        img.thumbnail((MAX_SPRITE_W, MAX_SPRITE_H), Image.LANCZOS)
    # Quantize to exactly 16 colors
    quantized = img.quantize(colors=N_COLORS, method=Image.Quantize.MEDIANCUT)
    buf = io.BytesIO()
    quantized.save(buf, format="PNG")
    return buf.getvalue()
