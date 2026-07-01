"""truth_lens — 9-stage multimodal deception analysis for Brilliant Halo.

(Formerly: lie_lens)

Public API
----------
    from dreamlayer.truth_lens import TruthLens

    tl = TruthLens()
    tl.feed_frame(camera_frame)
    tl.feed_audio(mic_fft, mic_amplitude)
    tl.feed_transcript(utterance_text)
    result = tl.tick()         # returns TruthLensResult or None
    if result:
        card = result.to_hud_card()

Architecture
------------
  Stage 1  face_embed      — face detection + 512-d MobileFaceNet embedding
  Stage 2  au_detector     — 17 facial action units (micro-expressions)
  Stage 3  prosody         — voice stress (pitch, jitter, shimmer, hesitation)
  Stage 4  linguistic      — hedging, pronoun use, complexity scoring
  Stage 5  fusion          — z-score fusion → CredibilityVector
  Stage 6  renderer        — TruthLensCard HUD output
  Stage 7  narrative_store — per-contact baseline + anomaly logging
  Stage 8  fact_check      — optional async cloud fact-check bridge (stub)

Privacy
-------
  All stages run on-device (phone). Nothing leaves the device unless
  fact-check is explicitly enabled. No audio or video is stored.
"""
from .analyzer import TruthLens
from .schema import (
    TruthLensResult, CredibilityVector, ContactBaseline,
    AUFrame, ProsodyFrame, LinguisticFrame,
)

__all__ = [
    "TruthLens",
    "TruthLensResult",
    "CredibilityVector",
    "ContactBaseline",
    "AUFrame",
    "ProsodyFrame",
    "LinguisticFrame",
]
