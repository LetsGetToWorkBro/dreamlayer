"""dream/engine.py — DreamEngine: ambient loop coordinator.

Runs as an asyncio background task alongside the normal Orchestrator.
The Orchestrator starts/stops it via enter_dream() / exit_dream().

Architecture
------------
  DreamEngine._loop()  (infinite async loop, 2 Hz)
    ├── MicReactor.tick(ctx)     → palette shift BLE frame
    ├── ImuReactor.tick(ctx)     → geometry distortion BLE frame
    ├── GhostLayer.tick(ctx)     → WorldAnchorCard if place match
    └── SceneDescriber.tick(ctx) → SynesthesiaCard every ~4s (camera gated)

All sub-systems receive a RecallContext built from the latest sensor data.
They return either a card dict (dispatched via bridge.send_card) or a raw
BLE command dict (dispatched via bridge.send_raw).

Test-safety note
----------------
start() is deliberately safe to call outside a running event loop.
When called synchronously in pytest (no loop), _task is left None and
_running is set True.  The loop picks up when the caller later runs an
async fixture or asyncio.run().  This means sync unit tests can call
enter_dream() / exit_dream() without a RuntimeError.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from ..recall_context import RecallContext
from .mic_reactor import MicReactor
from .imu_reactor import ImuReactor
from .ghost_layer import GhostLayer
from .place_reactor import PlaceReactor
from .scene_describer import SceneDescriber
from .sprite_bridge import SpriteBridge, render_gesture

log = logging.getLogger(__name__)

AMBIENT_HZ       = 2.0
SCENE_INTERVAL_S = 4.0


class DreamEngine:
    """Coordinates all Dream Mode sub-systems."""

    def __init__(self, bridge, db=None, privacy=None) -> None:
        self.bridge   = bridge
        self.db       = db
        self.privacy  = privacy
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_scene_t: float = 0.0
        self._ctx: RecallContext = RecallContext()

        self.mic       = MicReactor()
        self.imu       = ImuReactor()
        self.ghost     = GhostLayer(db=db, privacy=privacy)
        self.place     = PlaceReactor()
        self.describer = SceneDescriber()
        self.sprites   = SpriteBridge(bridge)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the ambient loop.

        Safe to call from synchronous code (e.g. a BLE callback or a
        sync pytest test).  When a running event loop exists the task is
        scheduled immediately; when there is no loop, _task stays None
        and _running is set so that callers that later enter an async
        context can call _ensure_task() to start the loop.
        """
        if self._running:
            return
        self._running = True
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._loop(), name="dream-engine")
        except RuntimeError:
            # No running event loop — test / sync context.
            # _loop() will be started the first time _ensure_task() is
            # called from within an async context, or when the caller
            # uses asyncio.run() / an async fixture.
            self._task = None
        log.info("DreamEngine started (task=%s)", self._task)

    def stop(self) -> None:
        """Stop the ambient loop gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        log.info("DreamEngine stopped")

    def _ensure_task(self) -> None:
        """Schedule _loop() if we're now inside a running event loop but
        start() was called outside one (sync → async transition)."""
        if self._running and self._task is None:
            try:
                loop = asyncio.get_running_loop()
                self._task = loop.create_task(self._loop(), name="dream-engine")
            except RuntimeError:
                pass

    @property
    def running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Sensor feed  (called by Orchestrator on every sensor event)
    # ------------------------------------------------------------------

    def feed_mic(self, fft: list[float], amplitude: float) -> None:
        self._ctx.mic_fft = fft
        self._ctx.mic_amplitude = amplitude

    def feed_imu(self, pose: dict, delta: dict) -> None:
        self._ctx.imu_pose = pose
        self._ctx.imu_delta = delta

    def feed_camera(self, jpeg_bytes: bytes) -> None:
        self._ctx.camera_frame = jpeg_bytes

    def feed_place(self, signature: str, anchors: list[dict]) -> None:
        self._ctx.place_signature = signature
        self._ctx.world_anchors = anchors

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        interval = 1.0 / AMBIENT_HZ
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("DreamEngine tick error: %s", exc)
            await asyncio.sleep(interval)

    async def _tick(self) -> None:
        ctx = self._ctx

        palette_cmd = self.mic.tick(ctx)
        if palette_cmd:
            self.bridge.send_raw(palette_cmd)

        # PlaceReactor runs after MicReactor by contract: while a place bias
        # is ramping, the ambient trust signal wins the drift_b slot.
        place_cmd = self.place.tick(ctx)
        if place_cmd:
            self.bridge.send_raw(place_cmd)

        geo_cmd = self.imu.tick(ctx)
        if geo_cmd:
            self.bridge.send_raw(geo_cmd)

        field_cmd = self.imu.line_field(ctx)
        if field_cmd:
            self.bridge.send_raw(field_cmd)

        ghost_card = self.ghost.tick(ctx)
        if ghost_card:
            self.bridge.send_card(ghost_card, event="dream_ghost")

        now = time.monotonic()
        if ctx.has_camera() and (now - self._last_scene_t) >= SCENE_INTERVAL_S:
            self._last_scene_t = now
            scene_card = await self.describer.tick(ctx)
            if scene_card:
                self.bridge.send_card(scene_card, event="dream_scene")
                # Stream the gestural sprite for the card's bottom half
                gesture = self.describer.last_sprite
                if gesture is not None:
                    img = render_gesture(gesture)
                    if img is not None:
                        self.sprites.queue_image(img, x=64, y=128)
                await self.sprites.flush_pending()
