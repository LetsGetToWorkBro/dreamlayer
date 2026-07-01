"""dream_mode/sprite_bridge.py — Sprite animation dispatcher."""
from __future__ import annotations
from typing import Optional
import asyncio


class SpriteBridge:
    """Queues and flushes sprite animation commands over the BLE bridge."""

    def __init__(self, bridge):
        self._bridge = bridge
        self._pending: list[dict] = []

    def queue(self, sprite_cmd: dict) -> None:
        self._pending.append(sprite_cmd)

    async def flush_pending(self) -> None:
        while self._pending:
            cmd = self._pending.pop(0)
            try:
                self._bridge.send_raw(cmd)
            except Exception:
                pass
            await asyncio.sleep(0)

    def clear(self) -> None:
        self._pending.clear()
