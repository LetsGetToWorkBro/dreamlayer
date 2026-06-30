"""lie_lens — 9-stage multimodal deception analysis for Brilliant Labs Halo.

Public API
----------
    from memoscape.lie_lens import LieLens

    ll = LieLens()
    ll.feed_frame(camera_frame)              # each camera frame
    ll.feed_audio(mic_fft, mic_amplitude)    # each audio frame
    ll.feed_transcript(text)                 # each utterance from STT
    result = ll.tick()                       # each display tick
    if result:
        card = result.to_hud_card()          # send to HUD renderer

Pipeline stages
---------------
1. Face detection + 512-d embedding
2. Facial Action Unit detection (17 AUs)
3. Voice prosody (pitch, jitter, shimmer, hesitation)
4. Linguistic markers (hedging, pronoun use, complexity)
5. Fusion engine (z-score + CredibilityVector)
6. Sub-perceptual HUD renderer
7. Narrative memory (per-contact baseline + anomaly log)

Design
------
- All processing on-device / on-phone — nothing leaves the device
- Privacy gate respected at every stage
- Passive: runs silently in Dream Mode, never prompts user
- Stranger mode: conservative thresholds, no storage
"""
from .analyzer import LieLens
from .schema import (
    LieLensResult, CredibilityVector, ContactBaseline,
    AUFrame, ProsodyFrame, LinguisticFrame,
)

__all__ = [
    "LieLens",
    "LieLensResult",
    "CredibilityVector",
    "ContactBaseline",
    "AUFrame",
    "ProsodyFrame",
    "LinguisticFrame",
]
