"""dream_mode/mic_reactor.py — Audio → palette shift BLE frame."""
from __future__ import annotations
from typing import Optional
import math

SILENCE_THRESHOLD = 0.02
BASSCAP = 0.90

# RGB565 palette bands: silence → whisper → speech → loud → peak
PALETTE = [
    0x0000,  # silence  — black
    0x001F,  # whisper  — deep blue
    0x07FF,  # speech   — cyan
    0xFFE0,  # loud     — yellow
    0xF800,  # peak     — red
]


class MicReactor:
    """Converts microphone amplitude into a palette-shift BLE command."""

    def __init__(self):
        self._smoothed: float = 0.0

    def tick(self, ctx) -> Optional[dict]:
        amp = ctx.mic_amplitude or 0.0
        self._smoothed = 0.6 * self._smoothed + 0.4 * amp
        if self._smoothed < SILENCE_THRESHOLD:
            return None
        level = min(self._smoothed / BASSCAP, 1.0)
        band = int(level * (len(PALETTE) - 1))
        band = max(0, min(band, len(PALETTE) - 1))
        color = PALETTE[band]
        brightness = round(0.3 + level * 0.7, 2)
        return {
            "cmd": "palette_shift",
            "color": color,
            "brightness": brightness,
            "duration_ms": 400,
        }
