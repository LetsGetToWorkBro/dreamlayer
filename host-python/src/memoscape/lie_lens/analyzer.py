"""lie_lens/analyzer.py — LieLens main orchestrator.

The LieLens class is the single entry point used by the orchestrator
or Dream Engine. It wires together all 7 pipeline stages:

    1. Face detection + embedding   (face_embed.FaceEmbedder)
    2. AU detection                  (au_detector.AUDetector)
    3. Voice prosody                 (prosody.ProsodyAnalyzer)
    4. Linguistic markers            (linguistic.extract_linguistic_features)
    5. Fusion                        (fusion.fuse)
    6. Narrative store               (narrative_store.NarrativeStore)
    7. HUD renderer                  (renderer.render_lie_lens_card)

Calling pattern
---------------
    ll = LieLens()
    ll.feed_frame(camera_frame)           # each camera frame (~30fps)
    ll.feed_audio(mic_fft, mic_amplitude) # each audio frame (~160fps)
    ll.feed_transcript(text)              # each STT utterance
    result = ll.tick()                    # each display tick (~10fps)
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np

from .au_detector import AUDetector
from .face_embed import FaceEmbedder
from .fusion import fuse
from .linguistic import extract_linguistic_features
from .narrative_store import NarrativeStore
from .prosody import ProsodyAnalyzer
from .renderer import render_lie_lens_card
from .schema import (
    AUFrame, LieLensResult, LinguisticFrame, ProsodyFrame,
)

EMIT_COOLDOWN_S = 3.0
MAX_FRAME_HISTORY = 30


class _AlwaysOn:
    def allow_capture(self) -> bool:
        return True


class LieLens:
    """9-stage multimodal deception analysis orchestrator.

    Parameters
    ----------
    store : NarrativeStore, optional
        Memory backend. Defaults to in-process dict store.
    cooldown_s : float
        Minimum seconds between HUD emissions.
    privacy : object
        Optional privacy controller with allow_capture() -> bool.
    face_npu_fn : callable, optional
        Override face NPU for testing.
    au_npu_fn : callable, optional
        Override AU NPU for testing.
    """

    def __init__(
        self,
        store: Optional[NarrativeStore] = None,
        cooldown_s: float = EMIT_COOLDOWN_S,
        privacy=None,
        face_npu_fn=None,
        au_npu_fn=None,
    ):
        self._store = store or NarrativeStore()
        self._cooldown_s = cooldown_s
        self._privacy = privacy or _AlwaysOn()
        self._embedder = FaceEmbedder(npu_fn=face_npu_fn)
        self._au = AUDetector(npu_fn=au_npu_fn)
        self._prosody = ProsodyAnalyzer()

        # Rolling frame history
        self._au_frames: list[AUFrame] = []
        self._prosody_frames: list[ProsodyFrame] = []
        self._linguistic_frames: list[LinguisticFrame] = []

        # Current session state
        self._current_contact_id: Optional[str] = None
        self._current_contact_name: Optional[str] = None
        self._last_emit: float = 0.0
        self._window_count: int = 0

    # ------------------------------------------------------------------
    # Feed methods (called by pipeline)
    # ------------------------------------------------------------------

    def feed_frame(self, frame: Optional[np.ndarray]) -> None:
        """Ingest one camera frame — runs face detection + AU detection."""
        if not self._privacy.allow_capture() or frame is None:
            return

        # Face detection + contact matching
        detection = self._embedder.detect(frame)
        if detection is not None:
            contacts = self._store.get_contact_embeddings()
            match = self._embedder.match_contacts(
                detection.embedding, contacts
            )
            if match:
                cid, _ = match
                self._current_contact_id = cid
                self._current_contact_name = self._store.get_contact_name(cid)

        # AU detection
        au = self._au.detect(frame)
        if au is not None:
            self._au_frames.append(au)
            if len(self._au_frames) > MAX_FRAME_HISTORY:
                self._au_frames = self._au_frames[-MAX_FRAME_HISTORY:]

    def feed_audio(self, mic_fft: Optional[np.ndarray],
                   mic_amplitude: Optional[float]) -> None:
        """Ingest one audio frame — runs prosody analysis."""
        frame = self._prosody.feed(mic_fft, mic_amplitude)
        if frame is not None:
            self._prosody_frames.append(frame)
            if len(self._prosody_frames) > MAX_FRAME_HISTORY:
                self._prosody_frames = self._prosody_frames[-MAX_FRAME_HISTORY:]
            self._window_count += 1

    def feed_transcript(self, text: str) -> None:
        """Ingest one STT utterance — runs linguistic analysis."""
        if not text or not text.strip():
            return
        lf = extract_linguistic_features(text)
        self._linguistic_frames.append(lf)
        if len(self._linguistic_frames) > MAX_FRAME_HISTORY:
            self._linguistic_frames = self._linguistic_frames[-MAX_FRAME_HISTORY:]

        # Update contact baseline incrementally
        if self._current_contact_id:
            self._store.update_baseline_incremental(
                self._current_contact_id,
                au_frame=self._au_frames[-1] if self._au_frames else None,
                prosody_frame=self._prosody_frames[-1] if self._prosody_frames else None,
                linguistic_frame=lf,
            )

    # ------------------------------------------------------------------
    # Tick — called each display update
    # ------------------------------------------------------------------

    def tick(self) -> Optional[LieLensResult]:
        """Return LieLensResult if ready to emit, else None."""
        if not self._privacy.allow_capture():
            return None
        now = time.monotonic()
        if now - self._last_emit < self._cooldown_s:
            return None
        if self._window_count < 2:
            return None

        baseline = (
            self._store.get_baseline(self._current_contact_id)
            if self._current_contact_id else None
        )

        credibility = fuse(
            au_frames=self._au_frames,
            prosody_frames=self._prosody_frames,
            linguistic_frames=self._linguistic_frames,
            baseline=baseline,
            window_count=self._window_count,
        )

        if credibility.confidence < 0.15:
            return None

        # Log anomaly if alert-worthy
        if credibility.should_alert and self._current_contact_id:
            self._store.log_anomaly(
                self._current_contact_id,
                credibility.deception_prob,
                credibility.dominant_signal,
            )

        self._last_emit = now

        latest_prosody = self._prosody_frames[-1] if self._prosody_frames else None
        latest_au = self._au_frames[-1] if self._au_frames else None
        latest_ling = self._linguistic_frames[-1] if self._linguistic_frames else None

        return LieLensResult(
            credibility=credibility,
            contact_id=self._current_contact_id,
            contact_name=self._current_contact_name,
            au_frame=latest_au,
            prosody_frame=latest_prosody,
            linguistic_frame=latest_ling,
        )

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all session state — call when conversation ends."""
        self._au_frames.clear()
        self._prosody_frames.clear()
        self._linguistic_frames.clear()
        self._current_contact_id = None
        self._current_contact_name = None
        self._last_emit = 0.0
        self._window_count = 0
        self._prosody.clear()

    def register_contact(self, contact_id: str, name: str,
                          embedding: np.ndarray) -> None:
        """Register a contact's face embedding for matching."""
        self._store.register_contact(contact_id, name, embedding)

    def label_last_anomaly(self, contact_id: str, label: str) -> None:
        """Apply a user label ('confirmed'/'false_positive') to the latest anomaly."""
        anomalies = self._store.get_anomalies(contact_id)
        if anomalies:
            anomalies[-1].user_label = label
