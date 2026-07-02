"""dream/scene_describer.py — Camera frame → phrase + gestural sprite.

Halo Cinema v1 (docs/HALO_CINEMA_V1.md Phase 3 addendum).

Every SCENE_INTERVAL seconds (controlled by DreamEngine), a compressed
JPEG thumbnail from the glasses camera is sent to the phone's vision
pipeline. Two calls are made:

  (a) PHRASE — a 6-word poetic description (as before)
  (b) SPRITE — a *3-shape gestural sprite* spec: dominant color + three
      abstract shapes representing the scene's compositional weight
      (e.g. cafe → warm circle + horizontal line + small triangle)

Both compose into a SynesthesiaCard v2: sprite bottom-half (streamed as a
128×128 4bpp TxSprite, ~4KB — well under the 8KB budget), phrase top-half
at ghost opacity.

VLM prompts
-----------
PHRASE: "Describe this scene in exactly 6 evocative words. No punctuation."
SPRITE: JSON spec request (see _SPRITE_PROMPT).

Fallback
--------
With no vision model (offline / no API key), the phrase cycles mood lines
and the sprite spec is derived *deterministically from the phrase hash* —
same phrase, same gesture, so goldens stay stable.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from ..recall_context import RecallContext
from ...hud import cards as C

log = logging.getLogger(__name__)

_FALLBACK_MOODS = [
    "soft light, still breathing, here",
    "familiar geometry, patient silence",
    "edges dissolving into ambient warmth",
    "motion arrested, memory accumulating",
    "ordinary miracle, unremarkable and vast",
]
_POETIC_PROMPT = (
    "Describe this scene in exactly 6 evocative words. "
    "Be poetic, not literal. No punctuation."
)
_SPRITE_PROMPT = (
    "Reduce this scene to a gestural composition. Reply with JSON only: "
    '{"dominant": "#RRGGBB", "shapes": [{"kind": "circle|line|triangle|rect", '
    '"x": 0-127, "y": 0-127, "size": 8-56}, x3]} — three shapes that carry '
    "the scene's compositional weight."
)

_SHAPE_KINDS = ("circle", "line", "triangle", "rect")

# Warm/cool dominant palette for the deterministic fallback
_FALLBACK_DOMINANTS = (0x2CC79A, 0xE06B52, 0x8FA8B2, 0xFFAA00, 0xA8B8C0)


@dataclass
class GesturalSprite:
    """3-shape compositional gesture for SynesthesiaCard v2."""
    dominant: int                       # 0xRRGGBB
    shapes: list[dict] = field(default_factory=list)   # {kind,x,y,size} x3


class SceneDescriber:
    """Async VLM scene description → SynesthesiaCard v2 + gestural sprite."""

    def __init__(self, vision_fn=None) -> None:
        """vision_fn: async callable(jpeg_bytes, prompt) -> str, or None."""
        self._vision_fn = vision_fn
        self._fallback_idx = 0
        self._last_description: str = ""
        self._last_sprite: Optional[GesturalSprite] = None

    def set_vision_fn(self, fn) -> None:
        """Wire in the actual VLM callable at runtime (avoids import-time deps)."""
        self._vision_fn = fn

    async def tick(self, ctx: RecallContext) -> Optional[dict]:
        """Generate a SynesthesiaCard v2 from the current camera frame.

        The gestural sprite spec is exposed as .last_sprite; DreamEngine
        renders and streams it via SpriteBridge after sending the card.
        """
        if not ctx.has_camera():
            return None

        description = await self._describe(ctx.camera_frame)
        if not description:
            return None

        sprite = await self._gesture(ctx.camera_frame, description)

        self._last_description = description
        self._last_sprite = sprite
        return C.synesthesia_card_v2(
            description=description,
            dominant_color=sprite.dominant,
            shapes=sprite.shapes,
        )

    # ------------------------------------------------------------------
    # VLM calls
    # ------------------------------------------------------------------

    async def _describe(self, jpeg_bytes: bytes) -> str:
        if self._vision_fn is not None:
            try:
                result = await asyncio.wait_for(
                    self._vision_fn(jpeg_bytes, _POETIC_PROMPT),
                    timeout=5.0,
                )
                return result.strip()[:80]   # hard cap
            except asyncio.TimeoutError:
                log.warning("SceneDescriber: VLM timeout, using fallback")
            except Exception as exc:
                log.warning("SceneDescriber: VLM error %s, using fallback", exc)

        mood = _FALLBACK_MOODS[self._fallback_idx % len(_FALLBACK_MOODS)]
        self._fallback_idx += 1
        return mood

    async def _gesture(self, jpeg_bytes: bytes, phrase: str) -> GesturalSprite:
        if self._vision_fn is not None:
            try:
                raw = await asyncio.wait_for(
                    self._vision_fn(jpeg_bytes, _SPRITE_PROMPT),
                    timeout=5.0,
                )
                spec = json.loads(raw)
                sprite = _parse_sprite_spec(spec)
                if sprite:
                    return sprite
            except Exception as exc:
                log.warning("SceneDescriber: sprite VLM error %s, fallback", exc)
        return sprite_from_phrase(phrase)

    @property
    def last_description(self) -> str:
        return self._last_description

    @property
    def last_sprite(self) -> Optional[GesturalSprite]:
        return self._last_sprite


# ---------------------------------------------------------------------------
# Sprite spec helpers
# ---------------------------------------------------------------------------

def _parse_sprite_spec(spec: dict) -> Optional[GesturalSprite]:
    try:
        dominant = int(str(spec["dominant"]).lstrip("#"), 16)
        shapes = []
        for s in list(spec["shapes"])[:3]:
            kind = s.get("kind", "circle")
            if kind not in _SHAPE_KINDS:
                kind = "circle"
            shapes.append({
                "kind": kind,
                "x":    max(0, min(127, int(s.get("x", 64)))),
                "y":    max(0, min(127, int(s.get("y", 64)))),
                "size": max(8, min(56, int(s.get("size", 24)))),
            })
        if len(shapes) != 3:
            return None
        return GesturalSprite(dominant=dominant, shapes=shapes)
    except Exception:
        return None


def sprite_from_phrase(phrase: str) -> GesturalSprite:
    """Deterministic 3-shape gesture derived from the phrase hash — offline
    fallback that keeps goldens stable (same phrase → same gesture)."""
    digest = hashlib.sha256(phrase.encode()).digest()
    dominant = _FALLBACK_DOMINANTS[digest[0] % len(_FALLBACK_DOMINANTS)]
    shapes = []
    for i in range(3):
        b = digest[1 + i * 4 : 5 + i * 4]
        shapes.append({
            "kind": _SHAPE_KINDS[b[0] % len(_SHAPE_KINDS)],
            "x":    24 + b[1] % 80,
            "y":    24 + b[2] % 80,
            "size": 12 + b[3] % 36,
        })
    return GesturalSprite(dominant=dominant, shapes=shapes)
