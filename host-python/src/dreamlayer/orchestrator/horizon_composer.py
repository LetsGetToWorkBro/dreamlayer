"""orchestrator/horizon_composer.py

Meridian's Horizon Frame composer (docs/cinema_v2/horizon_frame.md).

Composes the day-ring — every remembered event, promise, and person
moment at its time-angle — from on-host state only (ring buffer, drift
engine): local-first, no cloud in the path. Emits the semantic BLE
payload ``{"t": "horizon", "seq": n, "paused": 0|1, "v": [dd, code,…]}``
mirrored by ``halo-lua/ble/message_types.lua`` (``HORIZON``) and plotted
by ``halo-lua/display/horizon.lua``. The device does zero clock math:
angles ship precomputed in deci-degrees screen space.

Dial geometry (docs/cinema_v2/horizon.md): now = −90° (12 o'clock),
past sweeps clockwise at 30°/hour, promise due-times counterclockwise,
both capped at ±5h with overflow compressed onto the elder tick / the
future-cap dot. The bottom seam (+60°…+120°) stays empty by
construction.
"""
from __future__ import annotations

import time
from typing import Optional

NOW_DEG = -90.0
DEG_PER_HOUR = 30.0
WINDOW_HOURS = 5.0
ELDER_DEG = 58.0
FUTURE_CAP_DEG = 122.0
MARKS_MAX = 48
CADENCE_S = 5.0

# code = kind*100 + state*10 + luma
KIND_MEMORY, KIND_PROMISE, KIND_PERSON, KIND_ELDER, KIND_FUTURE_CAP = 1, 2, 3, 4, 5
KIND_PREMONITION = 6   # future ghost (dream_mode/premonition.py)

_DRIFT_STATE_CODE = {
    "blooming": 1, "healthy": 2, "drifting": 3, "cracking": 4, "shattered": 5,
}

# ring-buffer kinds that render as person moments
_PERSON_KINDS = {"person"}
# kinds that are promises (rendered from the drift engine, not the buffer)
_PROMISE_KINDS = {"promise", "task"}

_CONF_FLOOR = 0.30   # below this an event is not worth a pixel


def _luma_tier(confidence: float) -> int:
    if confidence >= 0.70:
        return 2
    if confidence >= _CONF_FLOOR:
        return 1
    return 0


class HorizonComposer:
    """Stateless per-call composition + rate limiting + seq numbering."""

    def __init__(self, ring, drift=None, now_fn=None, rem=None,
                 premonition=None):
        self._ring = ring
        self._drift = drift
        self._now = now_fn or time.time
        # rem: optional RetrievalBias (dreamlayer.rem) — memories the
        # night promoted wake up one luma tier brighter; boosted marks
        # also survive the 48-mark cap preferentially.
        self._rem = rem
        # premonition: optional RecurrenceModel — future ghosts shimmer
        # ahead of the now-notch, always luma 1, dropped first at the cap
        self._premonition = premonition
        self._seq = 0
        self._last_emit: float = 0.0
        self._last_wire: Optional[str] = None

    def _rem_boost(self, kind: str, summary: str) -> float:
        if self._rem is None:
            return 0.0
        try:
            return max(0.0, float(self._rem.boost_for(kind, summary)))
        except Exception:
            return 0.0

    # -- geometry -------------------------------------------------------

    def angle_for_ts(self, ts: float, now: Optional[float] = None) -> float:
        """Screen angle for a past event timestamp (clamped to the elder
        door). Also used to stamp ``origin_deg`` on answer cards so the
        Focus law condenses them from where they live."""
        now = now if now is not None else self._now()
        hours_ago = max(0.0, (now - ts) / 3600.0)
        if hours_ago > WINDOW_HOURS:
            return ELDER_DEG
        return NOW_DEG + hours_ago * DEG_PER_HOUR

    def _angle_for_due(self, due_ts: float, now: float) -> Optional[float]:
        hours_until = (due_ts - now) / 3600.0
        if hours_until <= 0:
            # past due: it crosses to the past side like any other event
            return self.angle_for_ts(due_ts, now)
        if hours_until > WINDOW_HOURS:
            return None   # collapsed onto the future-cap dot
        return NOW_DEG - hours_until * DEG_PER_HOUR

    # -- composition -----------------------------------------------------

    def compose(self, now: Optional[float] = None, paused: bool = False) -> dict:
        """Build one full-state horizon frame. Any single frame fully
        heals the device (no diffs)."""
        now = now if now is not None else self._now()
        self._seq += 1
        if paused:
            # the empty pause frame: absence of marks must be deliverable
            return {"t": "horizon", "seq": self._seq, "paused": 1, "v": []}

        marks: list[tuple[float, int, float]] = []   # (deg, code, sort_conf)
        elder_needed = False
        future_cap_needed = False

        # -- memories & people from the ring buffer
        cutoff = now - WINDOW_HOURS * 3600.0
        for buffered in self._ring.since(0.0):
            ev = buffered.event
            kind = getattr(ev, "kind", "") or ""
            if kind in _PROMISE_KINDS:
                continue   # promises render from the drift engine
            conf = float(getattr(ev, "confidence", 0.0) or 0.0)
            if conf < _CONF_FLOOR:
                continue
            if buffered.ts < cutoff:
                elder_needed = True
                continue
            deg = self.angle_for_ts(buffered.ts, now)
            k = KIND_PERSON if kind in _PERSON_KINDS else KIND_MEMORY
            tier = _luma_tier(conf)
            boost = self._rem_boost(kind or "memory",
                                    getattr(ev, "summary", "") or "")
            if boost >= 0.15:
                tier = min(2, tier + 1)   # the night kept this one
            marks.append((deg, k * 100 + tier, conf + boost))

        # -- promises from the drift engine
        if self._drift is not None:
            for rec in self._drift.all_records():
                state = _DRIFT_STATE_CODE.get(getattr(rec, "state", ""), 2)
                due_ts = getattr(rec, "due_ts", None)
                pdeg: float | None
                if due_ts is None:
                    pdeg = None   # vague promise: waits at the future cap
                else:
                    pdeg = self._angle_for_due(float(due_ts), now)
                if pdeg is None:
                    future_cap_needed = True
                    continue
                conf = float(getattr(rec.event, "confidence", 0.5) or 0.5)
                conf += self._rem_boost(
                    "promise", getattr(rec.event, "summary", "") or "")
                marks.append((pdeg, KIND_PROMISE * 100 + state * 10 + 2, conf))

        # -- cap: drop lowest-confidence memories first, never promises.
        # When the cap forces drops, reserve one slot for the elder tick —
        # the overflow indicator must always fit (a full dial that hides
        # its own truncation would read as "covered everything").
        if len(marks) > MARKS_MAX:
            memories = sorted(
                (m for m in marks if m[1] // 100 in (KIND_MEMORY, KIND_PERSON)),
                key=lambda m: m[2],
            )
            keep_drop = len(marks) - (MARKS_MAX - 1)
            dropping = {id(m) for m in memories[:keep_drop]}
            marks = [m for m in marks if id(m) not in dropping]
            if dropping:
                elder_needed = True   # the day is bigger than the dial shows

        # -- future ghosts (Premonition): faint marks ahead of now,
        # never displacing real marks — they only fill spare capacity
        if self._premonition is not None:
            room = MARKS_MAX - len(marks) - 2   # keep space for elder/cap
            if room > 0:
                try:
                    preds = self._premonition.predict(now)
                except Exception:
                    preds = []
                for pred in preds[:room]:
                    hours_until = (pred.expected_ts - now) / 3600.0
                    if not 0.0 < hours_until <= WINDOW_HOURS:
                        continue
                    deg = NOW_DEG - hours_until * DEG_PER_HOUR
                    marks.append((deg, KIND_PREMONITION * 100 + 1,
                                  pred.confidence))

        if elder_needed and len(marks) < MARKS_MAX:
            marks.append((ELDER_DEG, KIND_ELDER * 100 + 1, 1.0))
        if future_cap_needed and len(marks) < MARKS_MAX:
            marks.append((FUTURE_CAP_DEG, KIND_FUTURE_CAP * 100 + 1, 1.0))

        v: list[int] = []
        for deg, code, _conf in marks:
            v.append(int(round(deg * 10)))
            v.append(int(code))
        return {"t": "horizon", "seq": self._seq, "paused": 0, "v": v}

    # -- emission (rate-limited full state) --------------------------------

    def maybe_frame(self, now: Optional[float] = None,
                    paused: bool = False) -> Optional[dict]:
        """Frame to send this tick, or None. Rate-limited to one per
        CADENCE_S unless the composed state changed."""
        now = now if now is not None else self._now()
        frame = self.compose(now, paused=paused)
        wire = repr((frame["paused"], frame["v"]))
        due = (now - self._last_emit) >= CADENCE_S
        changed = wire != self._last_wire
        if not due and not changed:
            self._seq -= 1   # frame not sent: do not burn the seq
            return None
        self._last_emit = now
        self._last_wire = wire
        return frame
