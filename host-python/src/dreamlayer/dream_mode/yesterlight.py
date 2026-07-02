"""dream_mode/yesterlight.py — walk through the past, in place.

Roll your head deliberately back and the Horizon dials back in time:
the palette weather replays the actual recorded ambience of this place,
the now-notch detaches and scrubs to the hour you're visiting, and
memory anchors near that hour glow at their marks. Return your head and
the present flows back.

Gesture contract (IMU pitch, radians; up is negative):
  enter : pitch <= ENTER_PITCH sustained ENTER_TICKS ticks — a held,
          deliberate look upward, not a glance
  depth : further tilt beyond the threshold scrubs further back,
          SCRUB_MIN_PER_RAD minutes per radian, clamped to what the
          ledger actually holds for this place
  exit  : pitch back above EXIT_PITCH, place change, ledger exhausted,
          or the hard TIMEOUT_S

Per active tick the controller emits (host → Halo, in this order):
  the replayed palette frame  {t="palette", colors=…}   (verbatim history)
  the scrub state             {t="yesterlight", active=1, notch_dd=…,
                               echo_dd=…?}
On exit it emits one {t="yesterlight", active=0} and the present resumes.

Scrub geometry matches the Horizon dial law exactly (now at −90°, past
clockwise at 30°/h, elder door at +58°), so the detached notch lands on
the same angles the day's marks already occupy.
"""
from __future__ import annotations

import time
from typing import Optional

# keep in lockstep with halo-lua/ble/message_types.lua (YESTERLIGHT)
MSG_YESTERLIGHT = "yesterlight"

ENTER_PITCH = -0.55        # rad — a deliberate held look upward
EXIT_PITCH = -0.25
ENTER_TICKS = 3            # sustained at 2 Hz ≈ 1.5 s
SCRUB_MIN_PER_RAD = 240.0  # tilt depth → minutes back
MAX_SCRUB_MIN = 300.0      # the dial's ±5 h window
TIMEOUT_S = 120.0
ECHO_WINDOW_S = 600.0      # anchors within ±10 min of the visited hour glow

NOW_DEG = -90.0
DEG_PER_HOUR = 30.0
ELDER_DEG = 58.0


def scrub_angle(minutes_back: float) -> float:
    """The detached notch's dial angle for a scrub depth (same law as
    HorizonComposer.angle_for_ts)."""
    deg = NOW_DEG + (minutes_back / 60.0) * DEG_PER_HOUR
    return min(deg, ELDER_DEG)


def freshness(age_s: float) -> float:
    """How un-dimmed a ghost is when visited at its own hour: 1.0 at the
    moment itself, fading to the ordinary ghost floor over the day."""
    return max(0.35, 1.0 - age_s / 86400.0)


class YesterlightController:
    def __init__(self, ledger, now_fn=None) -> None:
        self._ledger = ledger
        self._now = now_fn or time.time
        self.active = False
        self._held = 0
        self._entered_at = 0.0
        self._place: Optional[str] = None
        self._was_active = False

    # ------------------------------------------------------------------

    def tick(self, ctx) -> list[dict]:
        """Frames to send this tick (possibly empty)."""
        pitch = float((ctx.imu_pose or {}).get("pitch", 0.0))
        place = ctx.place_signature
        now = self._now()

        if not self.active:
            if place and pitch <= ENTER_PITCH and \
                    self._ledger.span(place) is not None:
                self._held += 1
                if self._held >= ENTER_TICKS:
                    self.active = True
                    self._entered_at = now
                    self._place = place
            else:
                self._held = 0
            return []

        # -- active: check exits first
        if (pitch >= EXIT_PITCH or place != self._place
                or (now - self._entered_at) > TIMEOUT_S):
            return self._exit()

        depth = max(0.0, (-pitch) - (-ENTER_PITCH))
        minutes_back = min(MAX_SCRUB_MIN, depth * SCRUB_MIN_PER_RAD)
        # even a threshold-deep hold visits at least a little while ago
        minutes_back = max(10.0, minutes_back)

        target_ts = now - minutes_back * 60.0
        snap = self._ledger.nearest(self._place, target_ts)
        if snap is None:
            span = self._ledger.span(self._place)
            if span is None:
                return self._exit()
            snap = self._ledger.nearest(self._place, max(span[0],
                                                         min(span[1],
                                                             target_ts)),
                                        tolerance_s=float("inf"))
            if snap is None:
                return self._exit()

        actual_minutes = max(0.0, (now - snap.ts) / 60.0)
        state = {
            "t": MSG_YESTERLIGHT,
            "active": 1,
            "notch_dd": int(round(scrub_angle(actual_minutes) * 10)),
        }
        echo = self._echo_angle(ctx, snap.ts, now)
        if echo is not None:
            state["echo_dd"] = echo

        self._was_active = True
        return [
            {"t": "palette", "colors": snap.colors},   # history, verbatim
            state,
        ]

    def _exit(self) -> list[dict]:
        self.active = False
        self._held = 0
        self._place = None
        if self._was_active:
            self._was_active = False
            return [{"t": MSG_YESTERLIGHT, "active": 0}]
        return []

    def _echo_angle(self, ctx, visited_ts: float,
                    now: float) -> Optional[int]:
        """If a memory anchor lives within the visited hour, its mark
        glows — the ghost un-dims to how fresh it was then."""
        for anchor in (ctx.world_anchors or []):
            ts = anchor.get("ts")
            if ts is None:
                continue
            if abs(float(ts) - visited_ts) <= ECHO_WINDOW_S:
                minutes = max(0.0, (now - float(ts)) / 60.0)
                return int(round(scrub_angle(minutes) * 10))
        return None
