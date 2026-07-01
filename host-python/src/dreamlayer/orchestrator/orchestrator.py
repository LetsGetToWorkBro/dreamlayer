"""orchestrator/orchestrator.py — DreamLayer central coordinator."""
from __future__ import annotations
import logging
from typing import Optional

from .state import AppState
from .intents import Intent
from .recall_context import RecallContext
from dreamlayer.dream_mode import DreamEngine
from dreamlayer.truth_lens import TruthLens
from dreamlayer.social_lens import SocialLens
from dreamlayer.lucid_recall import LucidRecall

log = logging.getLogger(__name__)


class Orchestrator:
    """Top-level DreamLayer coordinator.

    Owns state machine, routes sensor events, dispatches HUD cards.
    """

    def __init__(self, bridge, db=None, privacy=None,
                 contact_registry=None, memory_index=None):
        self._bridge   = bridge
        self._db       = db
        self._privacy  = privacy
        self._state    = AppState.IDLE
        self._ctx      = RecallContext()

        self.dream_engine = DreamEngine(bridge=bridge, db=db, privacy=privacy)
        self.truth_lens   = TruthLens(
            contact_registry=contact_registry or {},
            privacy=privacy,
        )
        self.social_lens  = SocialLens(
            contacts=contact_registry,
            privacy=privacy,
        )
        social = self.social_lens
        self.lucid_recall = LucidRecall(
            social_lens=social,
            memory_index=memory_index,
        )

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def state(self) -> AppState:
        return self._state

    def enter_dream(self) -> None:
        self._state = AppState.DREAM_MODE
        self.dream_engine.start()
        log.info("Entered Dream Mode")

    def exit_dream(self) -> None:
        self.dream_engine.stop()
        self._state = AppState.IDLE
        log.info("Exited Dream Mode")

    # ------------------------------------------------------------------
    # Sensor feed
    # ------------------------------------------------------------------

    def on_mic(self, fft, amplitude) -> None:
        self._ctx.mic_fft = fft
        self._ctx.mic_amplitude = amplitude
        if self._state == AppState.DREAM_MODE:
            self.dream_engine.feed_mic(fft, amplitude)
        self.truth_lens.feed_audio(fft, amplitude)

    def on_imu(self, pose, delta) -> None:
        self._ctx.imu_pose = pose
        self._ctx.imu_delta = delta
        if self._state == AppState.DREAM_MODE:
            self.dream_engine.feed_imu(pose, delta)

    def on_camera(self, frame) -> None:
        self._ctx.camera_frame = frame
        if self._state == AppState.DREAM_MODE:
            self.dream_engine.feed_camera(frame)
        self.truth_lens.feed_frame(frame)

    def on_transcript(self, text: str) -> None:
        self._ctx.transcript = text
        self.truth_lens.feed_transcript(text)

    def on_place(self, signature: str, anchors: list) -> None:
        self._ctx.place_signature = signature
        self._ctx.world_anchors = anchors
        if self._state == AppState.DREAM_MODE:
            self.dream_engine.feed_place(signature, anchors)

    # ------------------------------------------------------------------
    # Intent handling
    # ------------------------------------------------------------------

    def on_intent(self, intent: Intent, **kwargs) -> Optional[dict]:
        if intent == Intent.DOUBLE_TAP:
            if self._state == AppState.IDLE:
                self.enter_dream()
            elif self._state == AppState.DREAM_MODE:
                result = self.social_lens.identify(self._ctx.camera_frame)
                card = result.to_hud_card()
                self._bridge.send_card(card, event="social_lens")
                return card
        elif intent == Intent.VOICE_QUERY:
            text = kwargs.get("text", "")
            result = self.lucid_recall.query(text, self._ctx.camera_frame)
            card = result.to_hud_card()
            self._bridge.send_card(card, event="lucid_recall")
            return card
        elif intent == Intent.SINGLE_TAP:
            if self._state == AppState.DREAM_MODE:
                self.exit_dream()
        return None

    def tick(self) -> Optional[dict]:
        """Called periodically — runs TruthLens analysis cycle."""
        result = self.truth_lens.tick()
        if result:
            card = result.to_hud_card()
            self._bridge.send_card(card, event="truth_lens")
            return card
        return None
