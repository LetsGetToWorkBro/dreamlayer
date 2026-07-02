"""dream_mode/inner_weather.py — you are also a place with a climate.

The room's weather comes from the mic and paints the rim. Your own
weather comes from your body — gait and micro head-motion from the IMU,
speech cadence from your own prosody — and it churns the *core*. The two
systems interfere on the display exactly the way they do in life: a calm
person in a loud room holds a still center while the rim storms; an
agitated person in a quiet library churns inside a settled sky.

Signals (all already streaming through RecallContext):
  imu_delta                     angular velocity per tick — restlessness
  imu_pose                      micro head-motion (short-window variance)
  ctx.extra["self_prosody"]     the wearer's own speech statistics when
                                the prosody stack attributes speech to
                                self: speech_rate_norm, pause_ratio,
                                hesitation_rate

Fusion: normalized channels blend into one state scalar in [0,1]
(0 = flowing, 1 = storming), double-EMA smoothed; the slow trend of the
state is the *storm front*. When the trend stays positive past the warn
threshold while the state climbs, one early warning fires (cooldown-
gated) — the display gets restless minutes before you'd have named the
feeling.

Rendering: {t="geometry", mode="churn", intensity=state} — a dedicated
channel the renderer applies to the core particle field without
clobbering the IMU's transient rotate/scatter gestures. Emission is
hysteresis-gated (±0.05) so a steady mood costs no BLE at all. The
Privacy Veil silences the estimator completely.
"""
from __future__ import annotations

import time
from typing import Optional

STATE_ALPHA = 0.15         # fast EMA on the fused sample
TREND_ALPHA = 0.05         # slow EMA whose slope is the storm front
EMIT_HYSTERESIS = 0.05
WARN_TREND = 0.008         # sustained per-tick climb that means weather
WARN_STATE = 0.55
WARN_SUSTAIN_TICKS = 6     # ≥3 s of climb at 2 Hz before we speak
WARN_COOLDOWN_S = 300.0

# channel weights
W_MOTION, W_MICRO, W_VOICE = 0.45, 0.25, 0.30


def _norm(v: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (v - lo) / (hi - lo)))


class InnerWeather:
    def __init__(self, privacy=None, now_fn=None) -> None:
        self._privacy = privacy
        self._now = now_fn or time.time
        self.state = 0.0           # 0 flowing … 1 storming
        self._slow = 0.0
        self._prev_slow = 0.0
        self.trend = 0.0
        self._climb_ticks = 0
        self._last_warn = -1e12
        # device boots with churn 0 — only genuine movement of the
        # state costs radio (and an empty ctx costs none at all)
        self._last_emit_state: float = 0.0
        self._prev_pose: Optional[dict] = None

    # -- fusion ------------------------------------------------------------

    def sample(self, ctx) -> float:
        """One raw fused sample from the current context."""
        delta = ctx.imu_delta or {}
        motion = _norm(abs(float(delta.get("yaw", 0.0)))
                       + abs(float(delta.get("pitch", 0.0)))
                       + abs(float(delta.get("roll", 0.0))), 0.0, 2.4)

        micro = 0.0
        pose = ctx.imu_pose
        if pose and self._prev_pose:
            micro = _norm(sum(abs(float(pose.get(k, 0.0))
                                  - float(self._prev_pose.get(k, 0.0)))
                              for k in ("pitch", "yaw", "roll")), 0.0, 0.6)
        if pose:
            self._prev_pose = dict(pose)

        voice = 0.0
        prosody = (ctx.extra or {}).get("self_prosody")
        if prosody:
            rate = _norm(abs(float(prosody.get("speech_rate_norm", 1.0))
                             - 1.0), 0.0, 0.8)
            hes = _norm(float(prosody.get("hesitation_rate", 0.0)), 0.0, 3.0)
            pau = _norm(abs(float(prosody.get("pause_ratio", 0.25)) - 0.25),
                        0.0, 0.5)
            voice = 0.4 * rate + 0.35 * hes + 0.25 * pau

        return W_MOTION * motion + W_MICRO * micro + W_VOICE * voice

    # -- the climate ---------------------------------------------------------

    def tick(self, ctx) -> list[dict]:
        """Advance the estimate; return frames to send (possibly empty)."""
        if self._privacy is not None and not self._privacy.allow_capture():
            return []

        raw = self.sample(ctx)
        self.state += STATE_ALPHA * (raw - self.state)
        self._prev_slow = self._slow
        self._slow += TREND_ALPHA * (raw - self._slow)
        self.trend = self._slow - self._prev_slow

        frames: list[dict] = []

        # the storm front: sustained climb toward a restless state
        if self.trend > WARN_TREND and self.state > WARN_STATE:
            self._climb_ticks += 1
        else:
            self._climb_ticks = 0
        now = self._now()
        if (self._climb_ticks >= WARN_SUSTAIN_TICKS
                and now - self._last_warn > WARN_COOLDOWN_S):
            self._last_warn = now
            self._climb_ticks = 0
            frames.append({"t": "event", "name": "inner_storm",
                           "state": round(self.state, 3)})

        # hysteresis-gated churn: a steady mood costs no radio
        if abs(self.state - self._last_emit_state) >= EMIT_HYSTERESIS:
            self._last_emit_state = self.state
            frames.append({"t": "geometry", "mode": "churn",
                           "intensity": round(self.state, 3)})
        return frames

    def storm_warned_recently(self) -> bool:
        return (self._now() - self._last_warn) < WARN_COOLDOWN_S
