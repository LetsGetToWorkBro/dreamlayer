"""hud/motion_math.py

Python twin of the Meridian Lumen motion math in the device Lua
(``halo-lua/lib/easing.lua`` spring/anticipate and the ``SPRING_*`` /
``PAR_*`` / ``AURORA_*`` constant bank in ``halo-lua/display/animations.lua``).
Used by ``scripts/anim_preview.py`` and the golden exporters so host-side
previews move exactly like the glasses. Keep in sync with the Lua —
the parity tests regex both files.
"""
from __future__ import annotations

import math

# -- constants (mirror halo-lua/display/animations.lua, Lumen bank) ----------
SPRING_OMEGA = 7.4
SPRING_ZETA_SOFT = 0.85
SPRING_ZETA_SNAPPY = 0.63
SPRING_OVERSHOOT_MAX = 0.08
ANTICIPATE_FRAC = 0.12
ANTICIPATE_PX = 2
SQUASH_MAX = 0.25

PAL_WRITES_MAX = 8
DRAW_CALLS_MAX = 420

AURORA_PERIOD_MS = 12000
AURORA_Y_AMP = 120
AURORA_BASE_A = 0x2A3C46
AURORA_BASE_B = 0x2B3D45
AURORA_BASE_C = 0x293B43

SHIMMER_PERIOD_MS = 1400
SHIMMER_Y_LO = 180
SHIMMER_Y_HI = 400
PREMO_BASE = 0x58686E

HEARTBEAT_RISE_FRAC = 0.22

TRAIL_SAMPLES = 5
TRAIL_STEP_T = 0.06
SPEC_SWEEP_MS = 420
SPEC_BASE_A = 0x00FFA9
SPEC_BASE_B = 0x01FFAA
SPEC_BASE_C = 0x00FEAA
VOICE_BASE = 0xE06B53
CONDUCT_PERIOD_MS = 2400
CONDUCT_Y_AMP = 220
CHASE_Y_AMP = 300
VOICE_Y_GAIN = 200
VOICE_CR_GAIN = 60

PAR_MAX_PX = {"rim": 1, "ring": 2, "air": 3}
PAR_RATE_GAIN = 0.9
PAR_EMA_ALPHA = 0.35
PAR_SPRING_ZETA = 0.75
PAR_RETURN_MS = 260

PARTICLE_BUDGET = 24
BURST_N = 12
BURST_MS = 480
BURST_SPEED = 46
SHARD_N = 6
SHARD_MS = 700
SHARD_SPEED = 30
TEAR_SPIT_N = 3
TEAR_SPIT_MS = 320

SHATTER_FLASH_MS = 150
WAKE_REVEAL_MS = 600
WARP_STREAKS = 18
WARP_STREAK_LEN = 14

CHASE_SEGMENTS = 12

HARK_BREATHE_MS = 1100
HARK_BREATHE_URGENT_MS = 700
FACT_PULSE_MS = 420
GLANCE_NODE_R = 84
GLANCE_NODE_STAGGER_MS = 60
LISTEN_PULSE_MS = 1400

PRISM_BLOOM_MS = 600
PRISM_SPIN_RATE = 0.00004
PRISM_BREATH_MS = 5200
PRISM_RING_R_A = 60
PRISM_RING_R_B = 86


def spring(t: float, zeta: float = SPRING_ZETA_SOFT,
           omega: float = SPRING_OMEGA) -> float:
    """Closed-form damped-spring step response, normalized to t in [0, 1].

    Mirrors ``easing.spring`` in the device Lua exactly: a pure function
    of t (no integration state), so exported sequences are deterministic.
    """
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0
    zeta = min(zeta, 0.999)
    wd = omega * math.sqrt(1.0 - zeta * zeta)
    decay = math.exp(-zeta * omega * t)
    return 1.0 - decay * (math.cos(wd * t) + (zeta * omega / wd) * math.sin(wd * t))


def anticipate(t: float, frac: float = ANTICIPATE_FRAC,
               amt: float = 1.0) -> float:
    """Pull-back-then-fly easing; mirrors ``easing.anticipate`` in Lua."""
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0
    if t < frac:
        return -amt * math.sin(math.pi * (t / frac))
    return _in_out_cubic((t - frac) / (1.0 - frac))


def _in_out_cubic(t: float) -> float:
    if t < 0.5:
        return 4.0 * t * t * t
    t = 2.0 * t - 2.0
    return 1.0 + t * t * t / 2.0


def spring_overshoot(zeta: float) -> float:
    """First-peak overshoot of the step response (analytic)."""
    zeta = min(zeta, 0.999)
    return math.exp(-zeta * math.pi / math.sqrt(1.0 - zeta * zeta))
