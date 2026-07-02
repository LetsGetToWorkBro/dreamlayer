"""dream/mic_reactor.py — Palette Weather: mic FFT → emotional weather frames.

Halo Cinema v1 rewrite (docs/HALO_CINEMA_V1.md Phase 3 addendum).

Instead of "reactive" band-to-color mapping, the reactor runs a two-band
*emotional weather* model over the 32-bin FFT:

  LOW BAND  (bins 0-8, ~0-2.2kHz)   = atmospheric *pressure*
      drives the `sky` slot along the **Cb axis**:
      quiet room → settled cool cyan; bass-full room → storm blue-violet.
  HIGH BAND (bins 9-31, ~2.2-8kHz)  = *energy* (sibilance, clatter, hiss)
      drives the `energy` slot along the **Cr axis**:
      still air → neutral; bright energy → warm ember.

  Y (luma) on both follows total amplitude, so the whole field brightens
  with the room and dims with silence — weather you can read pre-consciously,
  not a VU meter.

The two trailing slots (`drift_a`, `drift_b`) echo sky/energy from the
*previous* tick, giving the field depth (a one-tick atmospheric lag).
`drift_b` is also the slot PlaceReactor biases — the engine calls
PlaceReactor after MicReactor so the ambient trust signal wins that slot.

Palette encoding
----------------
YCbCr values for frame.display.assign_color_ycbcr() are 0-1023 ints:
  Y  = luma  (0=black, 1023=white)
  Cb = blue-difference chroma (512=neutral)
  Cr = red-difference chroma  (512=neutral)
"""
from __future__ import annotations

from typing import Optional

from ..recall_context import RecallContext

# Two-band split over the 32-bin FFT (≈250Hz per bin at 16kHz)
_LOW_BANDS  = slice(0, 9)     # bins 0-8  — pressure
_HIGH_BANDS = slice(9, 32)    # bins 9-31 — energy

# Palette slots used for ambient color (mirrors themes.DYNAMIC_SLOTS /
# palette.lua reserve_dynamic): sky=1, energy=2, drift_a=3, drift_b=4
_AMBIENT_SLOTS = [1, 2, 3, 4]
_SLOT_SKY, _SLOT_ENERGY, _SLOT_DRIFT_A, _SLOT_DRIFT_B = _AMBIENT_SLOTS

# Neutral baseline: cool cyan (matches ACCENT_MEMORY)
_BASE_Y  = 420
_BASE_CB = 560
_BASE_CR = 450

# Weather axis gains
_PRESSURE_CB = 140    # low band pushes Cb toward storm blue-violet
_ENERGY_CR   = 170    # high band pushes Cr toward warm ember
_AMP_Y       = 200    # total amplitude lifts luma

_Y_MIN, _Y_MAX = 80, 900
_C_MIN, _C_MAX = 300, 800


class MicReactor:
    """Converts mic FFT data into palette-weather BLE commands."""

    def __init__(self, smoothing: float = 0.25) -> None:
        # EWM coefficient applied to band energies (1=instant, 0=frozen)
        self._alpha = smoothing
        self._pressure = 0.0
        self._energy   = 0.0
        self._prev_sky:    Optional[dict] = None
        self._prev_energy: Optional[dict] = None

    def tick(self, ctx: RecallContext) -> Optional[dict]:
        """Compute a palette-weather frame. Returns BLE cmd or None."""
        if not ctx.has_mic():
            return None

        fft = ctx.mic_fft or [0.0] * 32
        amp = ctx.mic_amplitude or 0.0

        self._pressure = _ewm(self._pressure, _mean(fft[_LOW_BANDS]),  self._alpha)
        self._energy   = _ewm(self._energy,   _mean(fft[_HIGH_BANDS]), self._alpha)

        y = _clamp(_BASE_Y + int(amp * _AMP_Y), _Y_MIN, _Y_MAX)

        sky = {
            "idx": _SLOT_SKY,
            "y":   y,
            "cb":  _clamp(_BASE_CB + int(self._pressure * _PRESSURE_CB), _C_MIN, _C_MAX),
            "cr":  _clamp(_BASE_CR - int(self._pressure * 30), _C_MIN, _C_MAX),
        }
        energy = {
            "idx": _SLOT_ENERGY,
            "y":   _clamp(y + int(self._energy * 60), _Y_MIN, _Y_MAX),
            "cb":  _clamp(_BASE_CB - int(self._energy * 40), _C_MIN, _C_MAX),
            "cr":  _clamp(_BASE_CR + int(self._energy * _ENERGY_CR), _C_MIN, _C_MAX),
        }

        # Trailing slots echo last tick's weather (one-tick atmospheric lag)
        drift_a = dict(self._prev_sky or sky,       idx=_SLOT_DRIFT_A)
        drift_b = dict(self._prev_energy or energy, idx=_SLOT_DRIFT_B)
        self._prev_sky, self._prev_energy = sky, energy

        return {
            "t":           "palette",
            "colors":      [sky, energy, drift_a, drift_b],
            "duration_ms": 2000,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mean(vals) -> float:
    lst = list(vals)
    return sum(lst) / len(lst) if lst else 0.0

def _ewm(prev: float, new: float, alpha: float) -> float:
    return prev + alpha * (new - prev)

def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))
