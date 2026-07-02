"""dream_mode/prism.py — Prism Lens: the reactive psychedelic overlay.

The host controller for the kaleidoscope drawn by halo-lua/display/prism.lua.
It owns the on/off state and turns ambient sound and motion into the
overlay's intensity and hue speed, so the world's colours breathe with the
room. It emits only what the device needs to draw:

    {t="prism", active=0|1, intensity=0..100, symmetry=n, hue_rate=n}

Intensity and hue_rate are eased (no jitter) and re-emitted only when they
move past a small threshold, so a quiet scene sends almost nothing. This is
an aesthetic wonder mode — stylisation, never neurostimulation.
"""
from __future__ import annotations

from dataclasses import dataclass

# keep in lockstep with halo-lua/ble/message_types.lua (PRISM)
MSG_PRISM = "prism"

_EASE = 0.25            # intensity/hue easing per react()
_EMIT_DELTA = 0.06      # re-emit only when intensity moves this much


@dataclass
class PrismLens:
    active: bool = False
    intensity: float = 0.5      # 0..1
    symmetry: int = 6           # mirror sectors (2..12)
    hue_rate: float = 1.0       # palette-cycle speed multiplier
    _last_emit_intensity: float = 0.5

    def enter(self, intensity: float = 0.5, symmetry: int = 6) -> dict:
        self.active = True
        self.intensity = _clamp01(intensity)
        self.symmetry = max(2, min(12, int(symmetry)))
        self._last_emit_intensity = self.intensity
        return self.frame()

    def exit(self) -> dict:
        self.active = False
        return {"t": MSG_PRISM, "active": 0}

    def react(self, loudness: float = 0.0, motion: float = 0.0) -> dict | None:
        """Ease intensity/hue toward the room's energy. Returns a frame only
        when it has moved enough to be worth sending."""
        if not self.active:
            return None
        target = _clamp01(0.35 + 0.5 * _clamp01(loudness) + 0.25 * _clamp01(motion))
        self.intensity += (target - self.intensity) * _EASE
        self.hue_rate = 0.6 + 1.8 * _clamp01(loudness)
        if abs(self.intensity - self._last_emit_intensity) < _EMIT_DELTA:
            return None
        self._last_emit_intensity = self.intensity
        return self.frame()

    def frame(self) -> dict:
        return {
            "t": MSG_PRISM,
            "active": 1 if self.active else 0,
            "intensity": round(self.intensity * 100),
            "symmetry": self.symmetry,
            "hue_rate": round(self.hue_rate, 2),
        }


def _clamp01(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else v
