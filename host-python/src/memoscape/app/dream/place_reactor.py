"""dream/place_reactor.py — Ambient trust signal from place familiarity.

Halo Cinema v1 (docs/HALO_CINEMA_V1.md Phase 3 addendum).

Takes the current place signature and emits a subtle palette bias on the
`drift_b` slot (slot 4, see themes.DYNAMIC_SLOTS):

  known-safe place (signature has memory anchors)
      → chroma drifts toward ACCENT_MEMORY (settled teal)
  new place (signature never seen, no anchors)
      → chroma drifts toward ACCENT_ATTENTION (alert coral)

The drift ramps over RAMP_S seconds (8s at 2 Hz = 16 ticks), so walking
into an unfamiliar room *slowly* warms the ambient field rather than
flashing an alarm — an ambient trust signal, not a notification.

Slot-sharing contract: MicReactor also writes drift_b (as a weather trail).
DreamEngine calls PlaceReactor *after* MicReactor each tick, so while a
place bias is ramping the trust signal wins the slot; when the reactor is
idle (no place signature) it emits nothing and the weather trail returns.
"""
from __future__ import annotations

from typing import Optional

from ..recall_context import RecallContext
from ...hud import themes as T

RAMP_S     = 8.0    # full bias ramp duration, seconds
AMBIENT_HZ = 2.0    # engine tick rate (matches DreamEngine.AMBIENT_HZ)

_SLOT = T.DYNAMIC_SLOTS["drift_b"]

# YCbCr targets (0-1023) derived from the semantic accents
_TRUST_Y,  _TRUST_CB,  _TRUST_CR  = 420, 545, 400   # toward ACCENT_MEMORY
_NOVEL_Y,  _NOVEL_CB,  _NOVEL_CR  = 460, 470, 620   # toward ACCENT_ATTENTION
_NEUTRAL_Y, _NEUTRAL_CB, _NEUTRAL_CR = 420, 560, 450  # weather baseline


class PlaceReactor:
    """Emits a slow palette bias encoding place familiarity."""

    def __init__(self) -> None:
        self._known: set[str] = set()      # signatures with anchors seen
        self._current: Optional[str] = None
        self._ramp: float = 0.0            # 0 → 1 over RAMP_S

    def tick(self, ctx: RecallContext) -> Optional[dict]:
        """Return a palette bias frame, or None without place context."""
        sig = ctx.place_signature
        if not sig:
            self._current = None
            self._ramp = 0.0
            return None

        if ctx.world_anchors:
            self._known.add(sig)

        if sig != self._current:
            self._current = sig
            self._ramp = 0.0

        self._ramp = min(1.0, self._ramp + 1.0 / (RAMP_S * AMBIENT_HZ))

        if sig in self._known:
            ty, tcb, tcr = _TRUST_Y, _TRUST_CB, _TRUST_CR
            bias = "trust"
        else:
            ty, tcb, tcr = _NOVEL_Y, _NOVEL_CB, _NOVEL_CR
            bias = "novel"

        r = self._ramp
        return {
            "t": "palette",
            "colors": [{
                "idx": _SLOT,
                "y":   _lerp(_NEUTRAL_Y,  ty,  r),
                "cb":  _lerp(_NEUTRAL_CB, tcb, r),
                "cr":  _lerp(_NEUTRAL_CR, tcr, r),
            }],
            "duration_ms": int(1000 / AMBIENT_HZ),
            "bias": bias,
        }

    @property
    def ramp(self) -> float:
        return self._ramp


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)
