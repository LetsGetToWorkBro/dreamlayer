"""hud/spatial_audio.py — the audible memory palace: recall as positioned sound.

The deep-research pick nobody does: move retrieval off the 256-px display and
into space. When Waypath answers "where's my bike?", the answer already carries
a relative bearing and a distance — so Juno's cue can *come from where the bike
is*: behind-left, eleven metres away, quiet with distance. The eyes stay on the
world; the ears do the pointing. (Research lead: Steam Audio / Resonance; the
seam below adopts a real HRTF backend when present, and the shipped fallback is
honest, tested psychoacoustics rather than a black box.)

Three layers, smallest-first:

* `spatialize(bearing_deg, distance_m)` — pure math from a cue's geometry to
  the binaural parameters human hearing actually uses: equal-power **pan**,
  distance **gain** (inverse rolloff, never fully silent), **ITD** (interaural
  time difference, Woodworth's spherical-head model — the dominant cue below
  ~1.5 kHz), **ILD** (interaural level difference, the dominant cue above),
  and a `behind` flag (front/back can't be encoded in ITD/ILD alone; renderers
  hint it with a gentle low-pass, phones may add a haptic).
* `render_stereo(mono, sr, params)` — an actual binaural renderer (numpy):
  per-ear gains, integer-sample ITD delay on the far ear, one-pole low-pass on
  rear sources. Deterministic; the tests measure the physics (energy ratio,
  onset delay, spectral tilt) rather than eyeballing.
* `spatial_payload(...)` — the compact dict a HUD card carries so any device
  (phone speaker, future buds) can render the cue with whatever fidelity it
  has; degrade order is pan+gain → +ITD → full HRTF.

Convention matches Waypath: bearing 0° = dead ahead, clockwise positive
(+90° = your right). Elevation is deliberately out of scope — anchors are
floor-level objects.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Optional

# Physiology + tuning constants
HEAD_RADIUS_M = 0.0875          # average adult head radius (Woodworth model)
SPEED_OF_SOUND = 343.0          # m/s at room temperature
MAX_ILD_DB = 8.0                # level difference at a fully lateral source
REF_DISTANCE_M = 1.0            # gain is 1.0 at or inside this distance
ROLLOFF = 0.8                   # gentle inverse rolloff exponent
MIN_GAIN = 0.15                 # a far cue stays audible — it's a pointer,
                                # not a simulation of a distant bicycle
REAR_LOWPASS_HZ = 2500.0        # the "behind you" spectral hint

try:  # numpy is a core dependency, but keep the pure-math half importable
    import numpy as _np
    _HAS_NUMPY = True
except Exception:  # pragma: no cover
    _np = None
    _HAS_NUMPY = False


@dataclass
class SpatialParams:
    """Everything a renderer needs, precomputed once per cue."""
    azimuth_deg: float          # normalized to (-180, 180], 0 = ahead, + = right
    distance_m: float
    pan: float                  # -1 (hard left) .. +1 (hard right), equal-power
    gain: float                 # distance attenuation, MIN_GAIN..1
    itd_s: float                # + means the LEFT ear is delayed (source right)
    ild_db: float               # + means the RIGHT ear is louder (source right)
    behind: bool

    def to_payload(self) -> dict:
        d = asdict(self)
        return {k: (round(v, 6) if isinstance(v, float) else v)
                for k, v in d.items()}


def _norm_azimuth(deg: float) -> float:
    """Into (-180, 180], clockwise-positive."""
    a = math.fmod(deg, 360.0)
    if a > 180.0:
        a -= 360.0
    elif a <= -180.0:
        a += 360.0
    return a


def spatialize(bearing_deg: float, distance_m: float) -> SpatialParams:
    """Cue geometry → binaural parameters. Pure, total, deterministic."""
    az = _norm_azimuth(bearing_deg)
    behind = abs(az) > 90.0
    # lateral component drives every left/right cue; front/back is the flag
    theta = math.radians(az)
    lateral = math.sin(theta)                       # -1 left .. +1 right

    pan = lateral                                    # equal-power at render time
    ild_db = MAX_ILD_DB * lateral
    # Woodworth: ITD = r/c * (sin θ + θ_lateral); use the folded frontal angle
    # so a source at 150° carries the same lateral delay as its 30° mirror
    folded = math.radians(180.0 - abs(az)) if behind else abs(theta)
    itd = (HEAD_RADIUS_M / SPEED_OF_SOUND) * (math.sin(folded) + folded)
    itd_s = math.copysign(itd, lateral) if lateral else 0.0

    d = max(0.0, float(distance_m))
    if d <= REF_DISTANCE_M:
        gain = 1.0
    else:
        gain = max(MIN_GAIN, (REF_DISTANCE_M / d) ** ROLLOFF)

    return SpatialParams(azimuth_deg=az, distance_m=d, pan=pan, gain=gain,
                         itd_s=itd_s, ild_db=ild_db, behind=behind)


def spatial_payload(bearing_deg: float, distance_m: float) -> dict:
    """The dict a HUD card carries under "spatial". Degrade order for
    renderers: pan+gain (any stereo device) → +itd (buds) → full HRTF seam."""
    return spatialize(bearing_deg, distance_m).to_payload()


# ---------------------------------------------------------------------------
# The shipped renderer: ILD + ITD + rear low-pass over a mono clip
# ---------------------------------------------------------------------------

def render_stereo(mono, sr: int, params: SpatialParams):
    """Binaurally place `mono` (float array, -1..1) at the cue's position.
    Returns an (n, 2) float32 array [L, R]. Needs numpy; raises otherwise
    (callers that only need parameters use spatialize/spatial_payload)."""
    if not _HAS_NUMPY:
        raise RuntimeError("render_stereo needs numpy")
    x = _np.asarray(mono, dtype=_np.float32) * params.gain

    # equal-power pan + ILD, composed per ear
    p = (params.pan + 1.0) / 2.0                     # 0 left .. 1 right
    left = math.cos(p * math.pi / 2.0)
    right = math.sin(p * math.pi / 2.0)
    half = 10.0 ** (abs(params.ild_db) / 2.0 / 20.0)
    if params.ild_db >= 0:                           # source right: R louder
        right *= half
        left /= half
    else:
        left *= half
        right /= half

    delay = int(round(abs(params.itd_s) * sr))       # far-ear onset delay
    n = len(x) + delay
    out = _np.zeros((n, 2), dtype=_np.float32)
    if params.itd_s >= 0:                            # left ear is the far ear
        out[:len(x), 1] = x * right
        out[delay:delay + len(x), 0] = x * left
    else:
        out[:len(x), 0] = x * left
        out[delay:delay + len(x), 1] = x * right

    if params.behind:                                # gentle spectral hint
        alpha = math.exp(-2.0 * math.pi * REAR_LOWPASS_HZ / sr)
        for ch in range(2):
            acc = 0.0
            col = out[:, ch]
            for i in range(n):                       # one-pole LP, in place
                acc = (1.0 - alpha) * col[i] + alpha * acc
                col[i] = acc
    return out


def cue_tone(sr: int = 22050, secs: float = 0.22, hz: float = 880.0):
    """A short, soft ping to spatialize when no voice clip is wanted —
    sine with a raised-cosine envelope, deterministic."""
    if not _HAS_NUMPY:
        raise RuntimeError("cue_tone needs numpy")
    t = _np.arange(int(sr * secs), dtype=_np.float32) / sr
    env = 0.5 * (1.0 - _np.cos(2.0 * math.pi * _np.minimum(t / secs, 1.0)))
    return (0.6 * _np.sin(2.0 * math.pi * hz * t) * env).astype(_np.float32)


# ---------------------------------------------------------------------------
# The HRTF seam (research lead: Steam Audio / Resonance). House pattern:
# lazy import + `available`; the ILD/ITD renderer above is the working
# fallback, so nothing here is ever load-bearing.
# ---------------------------------------------------------------------------

try:  # pragma: no cover - exercised only where the binding is installed
    import steamaudio as _steamaudio  # type: ignore
    _HAS_STEAM = True
except Exception:
    _steamaudio = None
    _HAS_STEAM = False


class SteamAudioRenderer:
    """Full-HRTF rendering when Valve's Steam Audio python binding is present
    (pip install steamaudio — optional, Apache-2.0). `available` is the flag;
    without it, use render_stereo above."""

    available = _HAS_STEAM

    def render(self, mono, sr: int, params: SpatialParams):
        if not self.available:
            raise RuntimeError(
                "steamaudio not installed — use spatial_audio.render_stereo")
        raise NotImplementedError(
            "HRTF backend wiring lands with the binding; the ILD/ITD renderer "
            "is the shipped path")


def attach_spatial(card: dict, bearing_deg: Optional[float],
                   distance_m: Optional[float]) -> dict:
    """Add the spatial payload to a HUD card when the cue has geometry; a
    place-only anchor ("at the north rack") has no direction, so no payload."""
    if bearing_deg is not None and distance_m is not None:
        card["spatial"] = spatial_payload(bearing_deg, distance_m)
    return card
