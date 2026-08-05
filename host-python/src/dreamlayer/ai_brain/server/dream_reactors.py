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

from .veil import RECALL_FOLLOWS_CAPTURE, VeilGate

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


class DreamReactors:
    """Both reactors, built once and held for the session."""

    def __init__(self, brain, now_fn=time.time):
        self.brain = brain
        self._now = now_fn
        self._timbre = None
        self._yester = None
        self._ledger = None
        self._mic = None
        #: Proof counters — what actually reached the glass, per lens. A built
        #: reactor is not a driven one, which is the distinction every promotion
        #: in this tree turns on.
        self.timbre_frames = 0
        self.yesterlight_frames = 0
        self.palette_frames = 0

    # ---------------------------------------------------------------- timbre

    def timbre(self):
        if self._timbre is None:
            from ...dream_mode.timbre_reactor import TimbreReactor
            self._timbre = TimbreReactor(baselines=_Baselines(self.brain),
                                         privacy=VeilGate(self.brain, recall=RECALL_FOLLOWS_CAPTURE),
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

    # ------------------------------------------------------------- weather

    def mic(self):
        if self._mic is None:
            from ...dream_mode.mic_reactor import MicReactor
            self._mic = MicReactor(privacy=VeilGate(self.brain, recall=RECALL_FOLLOWS_CAPTURE))
        return self._mic

    def note_mic(self, fft, amplitude: float = 0.0, place: str = "") -> dict:
        """One beat of ambient sound becomes the room's colour, on BOTH surfaces.

        `MicReactor` is the real primitive `DreamEngine` uses; the palette logic
        stays in one place rather than being re-derived in JavaScript for the
        phone. It refuses on its own when the veil is up — live audio driving a
        palette frame IS capture.

        The two surfaces take the same colours through different doors, and that
        asymmetry is in the transports rather than in the content:

          * the GLASSES have a native channel — a raw `palette` frame that
            `display/palette_animator.lua` animates across the whole disc;
          * the PHONE has none, so it gets a `PaletteShiftCard`, which is why
            `hud/cards.py:palette_shift_card` exists at all. Until now nothing
            called it, so the builder was real and the card was unreachable.

        The same colours are also recorded into the weather ledger, which is
        what gives Yesterlight a past to walk back into.
        """
        bands = list(fft or [])
        if not bands:
            # `RecallContext.has_mic()` is True for an EMPTY list, so the
            # reactor would happily paint the colour of silence here. That is
            # right for a quiet room and wrong for no room at all: a caller
            # with no analyser sends `[]`, and turning that into weather is
            # inventing a reading. Quiet is 32 low bands; nothing is nothing.
            return {"raw": 0, "card": 0}
        from ...orchestrator.recall_context import RecallContext
        ctx = RecallContext(mic_fft=bands,
                            mic_amplitude=float(amplitude or 0.0))
        try:
            cmd = self.mic().tick(ctx)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[dream] mic tick failed: %s", type(exc).__name__)
            return {"raw": 0, "card": 0}
        if not cmd:
            return {"raw": 0, "card": 0}             # veiled, or no mic signal
        raw = self.brain.push_raw(cmd)
        colors = list(cmd.get("colors") or [])
        card = 0
        if colors:
            from ...hud.cards import palette_shift_card
            card = self.brain.push_event(
                "palette", palette_shift_card(
                    colors=colors,
                    duration_ms=int(cmd.get("duration_ms") or 2000),
                    mood=str(cmd.get("mood") or "neutral")))
        if raw or card:
            self.palette_frames += 1
            self.note_weather(place, cmd, amplitude)
        return {"raw": raw, "card": card}

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
            self._ledger = WeatherLedger(privacy=VeilGate(self.brain, recall=RECALL_FOLLOWS_CAPTURE))
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
                "palette_frames": self.palette_frames,
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
