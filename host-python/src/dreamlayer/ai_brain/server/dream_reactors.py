"""Timbre and Yesterlight — the two Dream Mode reactors, Brain-side.

WHAT WAS MISSING, AND IT WAS ONLY THIS
--------------------------------------
Both halves of each lens were already written and neither could reach the other.

  * `dream_mode/timbre_reactor.py` turns "a known voice just spoke, from that
    side" into a rim frame, with strangers rendered as noise derived from
    nothing about them.
  * `dream_mode/yesterlight.py` turns a held upward look into a scrub back
    through the Horizon, replaying a place as it actually was.
  * `halo-lua/ble/message_types.lua` has declared `TIMBRE` and `YESTERLIGHT`
    since it was written — *"Python side dream_mode/timbre_reactor.py
    MSG_TIMBRE — keep in sync"* — and `dream_renderer.lua` / `horizon.lua`
    draw both.

What did not exist was anything that ticked them. Their only caller is
`dream_mode/engine.DreamEngine`, built by the `Orchestrator` the shipped Brain
never instantiates (`decisions/0001`) — the fifth instance of that pattern, and
the same fix each time: re-host the plain half Brain-side rather than
resurrecting the Orchestrator.

`bridge/base.RAW_FRAME_TYPES` was missing both names too, so even a frame that
somehow got produced could not legally cross the bridge. The device half and
the Python half were both complete and the wire between them refused the
traffic.

THE TWO INPUTS ARE ALREADY IN THE BRAIN
---------------------------------------
Neither reactor needs a new sensor.

  * Timbre wants a speaker label and a bearing. The capture pipeline already
    resolves the speaker (`ear.py`), and the Truth Lens already keeps
    per-contact prosody baselines in its narrative store — which is exactly
    what `timbre_signature` reads. No bearing hardware exists yet, so the
    reactor's own `DEFAULT_DIRECTION_DEG` is used and nothing is invented.
  * Yesterlight wants IMU pitch and a place signature. The Live Lens already
    listens to `devicemotion` for the dream weather, and the Brain already
    knows the current place.

PRIVACY
-------
Both frames derive from live signal — who is speaking, where you are — so both
go out through `Brain.push_raw`, which applies the Veil and offers no
`veil_ok` escape. The bridge then applies `pause_allows_raw`, which refuses
both while paused. Two gates, neither duplicated here, and a stranger is never
identified: the reactor's own stranger path is noise seeded from a fixed
constant, not from anything about the person.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

log = logging.getLogger("dreamlayer.dream_reactors")

#: Ticks of IMU below which Yesterlight is not consulted at all. The controller
#: itself needs consecutive holds to arm, so feeding it a single stray sample
#: from a phone that moved once would only ever be noise on the way to nothing.
MIN_POSE_KEYS = ("pitch",)


class _Baselines:
    """The Truth Lens's per-contact prosody baselines, as Timbre wants them.

    `TimbreReactor` asks for `get_baseline(speaker).prosody_mean`. The narrative
    store already holds exactly that and is already built Brain-side by
    `truth_live`; this is the two-line shim between the names, not a second
    store. Returning None for an unknown contact is what makes a stranger draw
    as static rather than as somebody else's timbre.
    """

    def __init__(self, brain):
        self.brain = brain

    def get_baseline(self, speaker: str):
        """`ear.truth._lens._store.get_baseline(contact_id)`, defensively.

        The chain is long because the store is per-EAR: the Mac's mic and a
        phone streaming in are two different rooms, and `TruthRead` is built
        per ear for that reason. Either ear's baselines are the wearer's own,
        so the first one that answers wins. Every hop is optional — an ear that
        never opened, a lens never built — and a miss means "no baseline",
        which is precisely what makes a voice draw as static instead of as
        somebody else's timbre.
        """
        for attr in ("_ear", "_remote_ear"):
            try:
                lens = getattr(getattr(self.brain, attr, None), "truth", None)
                lens = getattr(lens, "_lens", None)
                store = getattr(lens, "_store", None)
                got = store.get_baseline(speaker) if store is not None else None
                if got is not None:
                    return got
            except Exception as exc:                 # noqa: BLE001
                log.debug("[dream] baseline lookup failed: %s",
                          type(exc).__name__)
        return None


class _Gate:
    """The Veil, fail-closed — the same posture every lens host here takes."""

    def __init__(self, brain):
        self._brain = brain

    def allow_capture(self) -> bool:
        try:
            return not bool(self._brain.incognito_now())
        except Exception:                            # noqa: BLE001
            return False

    def allow_recall(self) -> bool:
        return self.allow_capture()


class DreamReactors:
    """Both reactors, built once and held for the session."""

    def __init__(self, brain, now_fn=time.time):
        self.brain = brain
        self._now = now_fn
        self._timbre = None
        self._yester = None
        self._ledger = None
        #: Proof counters — what actually reached the glass, per lens. A built
        #: reactor is not a driven one, which is the distinction every promotion
        #: in this tree turns on.
        self.timbre_frames = 0
        self.yesterlight_frames = 0

    # ---------------------------------------------------------------- timbre

    def timbre(self):
        if self._timbre is None:
            from ...dream_mode.timbre_reactor import TimbreReactor
            self._timbre = TimbreReactor(baselines=_Baselines(self.brain),
                                         privacy=_Gate(self.brain),
                                         now_fn=self._now)
        return self._timbre

    def note_speaker(self, speaker: str, direction_deg: Optional[float] = None) -> int:
        """A voice was just attributed. Paint its timbre at the rim.

        Called from the capture path, which is the only place that knows a
        speaker label exists. An empty label means nobody was attributed and is
        NOT a stranger — a stranger is a voice that was heard and not matched,
        which the pipeline reports as `"stranger"`. Conflating the two would
        draw static every time the room was silent.
        """
        if not speaker:
            return 0
        from ...orchestrator.recall_context import RecallContext
        extra = {}
        if direction_deg is not None:
            extra["voice_direction_deg"] = float(direction_deg)
        ctx = RecallContext(speaker=str(speaker), extra=extra)
        try:
            frame = self.timbre().tick(ctx)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[dream] timbre tick failed: %s", type(exc).__name__)
            return 0
        if not frame:
            return 0                                  # held down by its cooldown
        sent = self.brain.push_raw(frame)
        if sent:
            self.timbre_frames += 1
        return sent

    # ----------------------------------------------------------- yesterlight

    def ledger(self):
        """The room's memory of its own light, persisted beside the Brain."""
        if self._ledger is None:
            from ...dream_mode.weather_ledger import WeatherLedger
            # In-memory and bounded (CAPACITY ≈ 5.7 h of continuous ambience per
            # place). Not persisted, deliberately: a record of the light in every
            # room you have been in, kept across restarts, is a movement history
            # with better manners — and Yesterlight is a thing you do in the
            # moment, not an archive you consult.
            self._ledger = WeatherLedger(privacy=_Gate(self.brain))
        return self._ledger

    def yesterlight(self):
        if self._yester is None:
            from ...dream_mode.yesterlight import YesterlightController
            self._yester = YesterlightController(self.ledger(), now_fn=self._now)
        return self._yester

    def note_weather(self, place: str, colors, amplitude: float = 0.0) -> bool:
        """Record what the light was here, so there is a past to walk back into.

        Yesterlight replays what the ledger holds; with nothing recorded it
        correctly refuses to arm. This is the recording half, and it is gated by
        the ledger's own capture check — a veiled minute leaves no trace, and
        replay of what was already lawfully recorded stays available.
        """
        if not place:
            return False
        try:
            self.ledger().record(str(place), colors, float(amplitude or 0.0))
            return True
        except Exception as exc:                     # noqa: BLE001
            log.debug("[dream] weather record failed: %s", type(exc).__name__)
            return False

    def note_pose(self, pose: dict, place: str = "") -> int:
        """One IMU beat from the phone. Returns frames actually delivered.

        The controller is stateful across beats — it counts consecutive held
        ticks before arming and it owns its own exit conditions — so it is built
        once and fed, never rebuilt per sample.
        """
        if not isinstance(pose, dict) or not any(k in pose for k in MIN_POSE_KEYS):
            return 0
        from ...orchestrator.recall_context import RecallContext
        ctx = RecallContext(imu_pose=dict(pose), place_signature=str(place or ""))
        try:
            frames = self.yesterlight().tick(ctx) or []
        except Exception as exc:                     # noqa: BLE001
            log.warning("[dream] yesterlight tick failed: %s", type(exc).__name__)
            return 0
        sent = 0
        for frame in frames:
            got = self.brain.push_raw(frame)
            if got:
                sent += 1
        if sent:
            self.yesterlight_frames += sent
        return sent

    # ---------------------------------------------------------------- report

    def status(self) -> dict:
        return {"timbre_frames": self.timbre_frames,
                "yesterlight_frames": self.yesterlight_frames,
                "yesterlight_active": bool(getattr(self._yester, "active", False))}

    def timbre_live(self) -> bool:
        return self.timbre_frames > 0

    def yesterlight_live(self) -> bool:
        return self.yesterlight_frames > 0


def reactors(brain) -> DreamReactors:
    """The Brain's one pair, built on first use and held for the session."""
    got = getattr(brain, "_dream_reactors", None)
    if got is None:
        got = DreamReactors(brain)
        brain._dream_reactors = got
    return got
