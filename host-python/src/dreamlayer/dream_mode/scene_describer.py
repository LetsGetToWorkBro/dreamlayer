"""dream_mode/scene_describer.py — Camera → SynesthesiaCard every ~4s."""
from __future__ import annotations
from typing import Optional
import asyncio


class SceneDescriber:
    """Produces ambient scene description cards from camera frames."""

    def __init__(self, llm_client=None):
        self._llm = llm_client

    async def tick(self, ctx) -> Optional[dict]:
        if not ctx.has_camera():
            return None
        description = await self._describe(ctx.camera_frame)
        if not description:
            return None
        return {
            "type": "SynesthesiaCard",
            "dismiss_ms": 4000,
            "eyebrow": "DREAM MODE",
            "primary": description,
            "detail": "",
            "footer": "",
            "color": 0x07FF,
            "opacity": 0.75,
            "lines": ["DREAM MODE", description],
            "layout": {
                "eyebrow": {"x": 128, "y": 200, "size": "sm",
                            "color": 0x07FF, "tracking": 3},
                "primary": {"x": 128, "y": 218, "size": "sm",
                            "color": 0xFFFF},
            },
        }

    async def _describe(self, frame_bytes: bytes) -> Optional[str]:
        if self._llm is None:
            return None
        try:
            return await asyncio.wait_for(
                self._llm.describe_scene(frame_bytes), timeout=2.0
            )
        except Exception:
            return None
