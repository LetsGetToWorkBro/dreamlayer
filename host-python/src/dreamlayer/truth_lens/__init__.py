"""truth_lens — 9-stage multimodal deception analysis for Brilliant Halo.

Public API
----------
    from dreamlayer.truth_lens import TruthLens

    ll = TruthLens()

    # Feed sensor data each frame:
    ll.feed_frame(camera_frame)               # camera pipeline frame
    ll.feed_audio(mic_fft, mic_amplitude)     # mic pipeline frame
    ll.feed_transcript(utterance_text)        # ASR transcript chunk

    # Each display tick:
    result = ll.tick()                        # returns TruthLensResult or None
    if result:
        card = result.to_hud_card()           # send to HUD renderer

Architecture (mirrors Halo Lua spec)
-------------------------------------
  Stage 1  face_embed     — face detection + 512-d MobileFaceNet embedding
  Stage 2  au_detector    — 17 facial action units (micro-expressions)
  Stage 3  prosody        — voice stress (pitch, jitter, shimmer, hesitation)
  Stage 4  linguistic     — hedging, pronoun use, complexity scoring
  Stage 5  fusion         — z-score fusion → CredibilityVector
  Stage 6  renderer       — TruthLensCard HUD output
  Stage 7  narrative_store— per-contact baseline + anomaly logging
  Stage 8  fact_check     — optional async cloud fact-check bridge (stub)

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
