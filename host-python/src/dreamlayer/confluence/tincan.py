"""confluence/tincan.py — two cans, one string: silent gesture pings.

Tap a little rhythm on your button and it plays on your partner's rim
as light pulses at your bearing — morse for two, without a sound and
without a word on either display. The vocabulary is the button's own:
single, double, long. That's it. It is deliberately too small to say
anything except "I'm here", "look up", "let's go" — whatever the two of
you decide it means, which is the point.

Budget: a ping is at most MAX_PULSES pulses and at most one ping per
COOLDOWN_S crosses the bond. Pings ride the bond envelope (HMAC'd like
weather) and render device-side via {t="tincan"}.
"""
from __future__ import annotations

import time
from typing import Optional

# keep in lockstep with halo-lua/ble/message_types.lua (TINCAN)
MSG_TINCAN = "tincan"

MAX_PULSES = 5
COOLDOWN_S = 4.0
PULSE_MS = {"single": 140, "double": 320, "long": 640}
GAP_MS = 220


class TinCan:
    def __init__(self, bonds, now_fn=None) -> None:
        self._bonds = bonds
        self._now = now_fn or time.time
        self._last_sent = -1e12

    def compose(self, taps: list[str]) -> Optional[dict]:
        """Taps → an authenticated ping for the peer, or None (no live
        bond / cooldown / empty). Unknown gestures are dropped, not
        guessed."""
        pulses = [PULSE_MS[t] for t in taps if t in PULSE_MS][:MAX_PULSES]
        if not pulses:
            return None
        now = self._now()
        if now - self._last_sent < COOLDOWN_S:
            return None
        bond = self._bonds.live_bond()
        if bond is None:
            return None
        pkt = self._bonds.send_weather(state=-1.0, colors=[])
        if pkt is None:                      # veiled: cans go quiet too
            return None
        self._last_sent = now
        wire = pkt.to_wire()
        wire["ping"] = pulses
        return wire

    @staticmethod
    def render_frame(wire: dict, side_deg: float = 90.0) -> dict:
        """The receiving phone turns a ping into the device frame: pulse
        train at the partner's bearing (default: across the table)."""
        return {
            "t": MSG_TINCAN,
            "side_dd": int(round(side_deg * 10)),
            "pulses": list(wire.get("ping") or [])[:MAX_PULSES],
            "gap_ms": GAP_MS,
        }
