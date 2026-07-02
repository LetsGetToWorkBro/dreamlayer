"""dream_mode/timbre_reactor.py — see who's speaking before you turn.

In Dream Mode, when a known voice enters the room, that contact's
visual timbre (social_lens/timbre.py) glows at the rim on the side the
sound came from — synesthesia with an address book. Strangers render as
gray static: presence without identity, honoring the no-stranger-ID
contract (the static is random noise, derived from nothing about them).

Inputs, all already computed by the existing pipelines:
  ctx.speaker                    contact id when the social/truth stack
                                 has identified the voice; "stranger"
                                 when a voice is present but unmatched
  ctx.extra["voice_direction_deg"]   optional bearing; defaults straight
                                 ahead when the hardware can't say
  baselines.get_baseline(id)     the Truth Lens narrative store

Wire format (lockstep with halo-lua/ble/message_types.lua TIMBRE):
  {t="timbre", known=0|1, side_dd=deci-deg, points=[12 ints 1..15]}

Budget: at most one frame per HOLD_S per speaker; silence emits nothing.
"""
from __future__ import annotations

import random
import time
from typing import Optional

from ..social_lens.timbre import timbre_signature, POINTS

# keep in lockstep with halo-lua/ble/message_types.lua (TIMBRE)
MSG_TIMBRE = "timbre"

HOLD_S = 2.0
DEFAULT_DIRECTION_DEG = -90.0     # straight ahead on the dial


class TimbreReactor:
    def __init__(self, baselines=None, privacy=None, now_fn=None) -> None:
        self._baselines = baselines
        self._privacy = privacy
        self._now = now_fn or time.time
        self._last_emit: dict[str, float] = {}
        self._static_rng = random.Random(0xD1A1)

    def tick(self, ctx) -> Optional[dict]:
        if self._privacy is not None and not self._privacy.allow_capture():
            return None
        speaker = getattr(ctx, "speaker", None)
        if not speaker:
            return None

        now = self._now()
        if now - self._last_emit.get(speaker, 0.0) < HOLD_S:
            return None

        direction = float(
            (ctx.extra or {}).get("voice_direction_deg",
                                  DEFAULT_DIRECTION_DEG))

        points = self._known_points(speaker)
        if points is None:
            # a stranger: gray static — noise, derived from nothing
            # about them; presence is shown, identity never guessed
            points = [self._static_rng.randint(6, 10)
                      for _ in range(POINTS)]
            known = 0
        else:
            known = 1

        self._last_emit[speaker] = now
        return {
            "t": MSG_TIMBRE,
            "known": known,
            "side_dd": int(round(direction * 10)),
            "points": points,
        }

    def _known_points(self, speaker: str) -> Optional[list[int]]:
        if speaker == "stranger" or self._baselines is None:
            return None
        baseline = self._baselines.get_baseline(speaker)
        if baseline is None:
            return None
        prosody_mean = getattr(baseline, "prosody_mean", None) or {}
        if not prosody_mean:
            return None
        return timbre_signature(prosody_mean)
