"""truth_lens/analyzer.py — TruthLens main orchestrator.

The single entry point for the Lie Lens pipeline.
The Dream Engine or orchestrator calls:
  ll.feed_frame(camera_frame)            # every camera frame
  ll.feed_audio(mic_fft, amplitude)      # every mic frame
  ll.feed_transcript(text)              # every ASR utterance
  result = ll.tick()                    # every display tick

Internally orchestrates all 9 stages:
  1  face_embed      → AUFrame (face detection + embedding)
  2  au_detector     → refined AUFrame
  3  prosody         → ProsodyFrame (per window)
  4  linguistic      → LinguisticFrame (per utterance)
  5  narrative_store → ContactBaseline lookup
  6  fusion          → CredibilityVector
  7  renderer        → TruthLensCard dict
  8  narrative_store → baseline update + anomaly log
  9  fact_check      → stub (async cloud, disabled by default)
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np

from .face_embed import FaceEmbedder, cosine_similarity
from .au_detector import AUDetector
from .prosody import ProsodyAnalyzer
from .linguistic import LinguisticAnalyzer
from .fusion import FusionEngine
from .renderer import TruthLensRenderer
from .narrative_store import NarrativeStore
from .schema import (
    AUFrame, ProsodyFrame, LinguisticFrame, TruthLensResult,
)

EMIT_COOLDOWN_S = 3.0
FACE_MATCH_THRESHOLD = 0.65


class _AlwaysOn:
    def allow_capture(self) -> bool:
        return True


class TruthLens:
    """9-stage multimodal deception analysis orchestrator.

    Parameters
    ----------
    contact_registry : dict, optional
        {contact_id: {"name": str, "embedding": list[float]}}
        Your personal contacts with face embeddings.
    cooldown_s : float
        Minimum seconds between HUD emissions.
    privacy : object
        Optional privacy controller with allow_capture() -> bool.
    memory_backend : object, optional
        Narrative memory backend (get/set/push). Uses in-memory default.
    """

    def __init__(
        self,
        contact_registry: Optional[dict] = None,
        cooldown_s: float = EMIT_COOLDOWN_S,
        privacy=None,
        memory_backend=None,
    ):
        self._contacts = contact_registry or {}
        self._cooldown_s = cooldown_s
        self._privacy = privacy or _AlwaysOn()

        # Stage instances
        self._embedder = FaceEmbedder()
        self._au_detector = AUDetector()
        self._prosody = ProsodyAnalyzer()
        self._linguistic = LinguisticAnalyzer()
        self._fusion = FusionEngine()
        self._renderer = TruthLensRenderer()
        self._store = NarrativeStore(memory_backend)

        # Rolling state
        self._current_au: Optional[AUFrame] = None
        self._current_prosody: Optional[ProsodyFrame] = None
        self._current_linguistic: Optional[LinguisticFrame] = None
        self._current_contact_id: Optional[str] = None
        self._current_contact_name: Optional[str] = None
        self._last_emit: float = 0.0

    # ------------------------------------------------------------------
    # Feed methods (called each frame by the dream engine)
    # ------------------------------------------------------------------

    def feed_frame(self, camera_frame: Optional[np.ndarray]) -> None:
        """Stage 1+2: face detection, embedding, AU extraction."""
        if not self._privacy.allow_capture():
            return
        au = self._embedder.process_frame(camera_frame)
        if au is None:
            return
        au = self._au_detector.process(au)
        self._current_au = au

        # Contact matching (if embedding available)
        if au.embedding and self._contacts:
            cid, score = self._match_contact(au.embedding)
            if cid and score >= FACE_MATCH_THRESHOLD:
                self._current_contact_id = cid
                self._current_contact_name = (
                    self._contacts[cid].get("name") if cid else None
                )

    def feed_audio(self, mic_fft: Optional[np.ndarray],
                   amplitude: Optional[float]) -> None:
        """Stage 3: prosody analysis."""
        if not self._privacy.allow_capture():
            return
        prosody = self._prosody.feed(mic_fft, amplitude)
        if prosody is not None:
            self._current_prosody = prosody

    def feed_transcript(self, text: Optional[str]) -> None:
        """Stage 4: linguistic analysis."""
        if not self._privacy.allow_capture():
            return
        ling = self._linguistic.analyse(text)
        if ling is not None:
            self._current_linguistic = ling

    # ------------------------------------------------------------------
    # Tick (called each display update)
    # ------------------------------------------------------------------

    def tick(self) -> Optional[TruthLensResult]:
        """Run fusion + render. Return TruthLensResult if ready to emit."""
        if not self._privacy.allow_capture():
            return None
        now = time.monotonic()
        if now - self._last_emit < self._cooldown_s:
            return None
        if self._current_au is None and self._current_prosody is None:
            return None

        # Stage 5: baseline lookup
        baseline = None
        if self._current_contact_id:
            baseline = self._store.get_baseline(self._current_contact_id)

        # Stage 6: fusion
        credibility = self._fusion.fuse(
            self._current_au,
            self._current_prosody,
            self._current_linguistic,
            baseline,
        )

        if credibility.confidence < 0.1 and credibility.deception_prob < 0.5:
            return None

        # Stage 7: renderer
        result = TruthLensResult(
            credibility=credibility,
            contact_id=self._current_contact_id,
            contact_name=self._current_contact_name,
            au_frame=self._current_au,
            prosody_frame=self._current_prosody,
            linguistic_frame=self._current_linguistic,
        )

        card = self._renderer.render(result)
        if card is None:
            return None

        # Stage 8: update baseline + log
        if self._current_contact_id:
            self._store.update_baseline(
                self._current_contact_id,
                self._current_au,
                self._current_prosody,
                self._current_linguistic,
            )
            if credibility.deception_prob > 0.65:
                self._store.log_anomaly(
                    self._current_contact_id,
                    credibility.deception_prob,
                    credibility.dominant_channel,
                )

        self._last_emit = now
        return result

    def assess(self):
        """Fuse the current channels into a CredibilityVector *without* the HUD's
        display gating — for callers (Discernment) that want the read even when
        it's reassuring, since "credible delivery" is exactly what turns a wrong
        claim into an honest mistake rather than a lie. Also advances the
        per-contact baseline, like `tick`. Returns None only with no signal."""
        if not self._privacy.allow_capture():
            return None
        if (self._current_au is None and self._current_prosody is None
                and self._current_linguistic is None):
            return None
        baseline = None
        if self._current_contact_id:
            baseline = self._store.get_baseline(self._current_contact_id)
        credibility = self._fusion.fuse(
            self._current_au, self._current_prosody,
            self._current_linguistic, baseline)
        if self._current_contact_id:
            self._store.update_baseline(
                self._current_contact_id, self._current_au,
                self._current_prosody, self._current_linguistic)
        return credibility

    def set_contact(self, contact_id: Optional[str],
                    name: Optional[str] = None) -> None:
        """Set the current speaker directly, when identity comes from speaker
        diarization or the Social Lens rather than a face match — so per-contact
        baselines still apply. Passing None clears it (stranger mode)."""
        self._current_contact_id = contact_id or None
        self._current_contact_name = name

    def reset(self) -> None:
        """Clear session state (call when conversation ends)."""
        self._current_au = None
        self._current_prosody = None
        self._current_linguistic = None
        self._current_contact_id = None
        self._current_contact_name = None
        self._last_emit = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _match_contact(self, embedding: list[float]) -> tuple:
        best_id, best_score = None, 0.0
        for cid, info in self._contacts.items():
            emb = info.get("embedding")
            if emb:
                score = cosine_similarity(embedding, emb)
                if score > best_score:
                    best_score, best_id = score, cid
        return best_id, best_score
