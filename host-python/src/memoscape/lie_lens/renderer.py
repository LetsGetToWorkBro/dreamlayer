"""lie_lens/renderer.py — HUD card renderer for Lie Lens.

Converts a LieLensResult into a LieLensCard dict suitable for the
existing Halo HUD rendering pipeline.

Also defines the sub-perceptual cue parameters:
- Chromatic aberration strength (voice stress → RGB fringe)
- Particle color + density (confidence level)
- Audio delay line (hesitation → bone conduction delay)
"""
from __future__ import annotations

from typing import Optional

from .schema import LieLensResult, CredibilityVector

# Sub-perceptual cue constants
CHROMATIC_BASE_STRENGTH = 0.008
PARTICLE_DENSITY_SCALE = 0.5
MAX_AUDIO_DELAY_MS = 15.0
CARD_DISMISS_MS = 5000


def render_lie_lens_card(result: LieLensResult) -> dict:
    """Produce a full HUD card dict from a LieLensResult."""
    c = result.credibility
    name = result.contact_name or ("Stranger" if c.is_stranger else "Unknown")

    # Sub-perceptual cue parameters (consumed by Lua renderer on device)
    chromatic_strength = 0.0
    particle_color = 0x07E0  # green default
    particle_density = 0.0
    audio_delay_ms = 0.0

    if c.should_alert:
        chromatic_strength = c.voice_stress_z * CHROMATIC_BASE_STRENGTH
        particle_density = c.confidence * PARTICLE_DENSITY_SCALE
        particle_color = 0xF800 if c.deception_prob > 0.90 else 0xFD20
        if result.prosody_frame:
            audio_delay_ms = min(
                result.prosody_frame.hesitation_rate * MAX_AUDIO_DELAY_MS,
                MAX_AUDIO_DELAY_MS,
            )

    return {
        "type": "LieLensCard",
        "dismiss_ms": CARD_DISMISS_MS,
        # Core display
        "eyebrow": "LIE LENS",
        "name": name,
        "label": c.label,
        "deception_prob": round(c.deception_prob, 2),
        "confidence": round(c.confidence, 2),
        "dominant_signal": c.dominant_signal,
        "color": c.hud_color,
        "should_alert": c.should_alert,
        "is_stranger": c.is_stranger,
        "opacity": 0.9 if c.confidence >= 0.6 else 0.5,
        # Text lines for display
        "lines": [
            "LIE LENS",
            name,
            c.label,
            f"{round(c.deception_prob * 100)}%  conf {round(c.confidence * 100)}%",
        ],
        # Layout positions
        "layout": {
            "eyebrow": {"x": 128, "y": 196, "size": "sm",
                        "color": c.hud_color, "tracking": 3},
            "primary": {"x": 128, "y": 214, "size": "sm", "color": c.hud_color},
            "name":    {"x": 128, "y": 230, "size": "sm", "color": 0xFFFF},
            "detail":  {"x": 128, "y": 246, "size": "sm", "color": 0x5EF7},
        },
        # Sub-perceptual cue parameters
        "fx": {
            "chromatic_aberration": round(chromatic_strength, 4),
            "particle_color": particle_color,
            "particle_density": round(particle_density, 2),
            "audio_delay_ms": round(audio_delay_ms, 1),
        },
        # Z-scores for debug overlay
        "z_scores": {
            "micro_exp": round(c.micro_exp_z, 2),
            "voice_stress": round(c.voice_stress_z, 2),
            "linguistic": round(c.linguistic_z, 2),
        },
    }
