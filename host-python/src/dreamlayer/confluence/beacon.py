"""confluence/beacon.py — The Beacon: find your people through a crowd.

Ride the GhostMode mesh with one job: point you at your group. Each member
emits a coarse **bearing + distance band relative to themselves** (never an
absolute location); on your rim it renders as a pulse train at that bearing —
nearer people pulse faster and brighter. No map, no "where are you" text.

Privacy: only bearing/presence crosses (it rides `MeshManager.emit`, so the
Veil silences it and forged/stranger traffic drops). Names never cross — the
card shows a member by the local alias you set, or a neutral tag.

Distance is a band, not a number: "close" / "near" / "far". That's all a
crowd-finder needs, and it's all we're willing to send.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from ..memory.privacy import AlwaysOnGate

# render lockstep with tincan: a pulse train at a bearing
MSG_BEACON = "beacon"
BANDS = ("close", "near", "far")
# nearer = faster, brighter pulse cadence
_BAND_PULSE = {"close": (160, 140), "near": (120, 260), "far": (90, 420)}  # (bright 0-255-ish, gap_ms)
_BAND_RANK = {"close": 0, "near": 1, "far": 2, "": 3}


def dist_band(distance_m: Optional[float]) -> str:
    """Map metres to a coarse band. None → unknown ('far' cadence)."""
    if distance_m is None:
        return "far"
    if distance_m <= 8:
        return "close"
    if distance_m <= 40:
        return "near"
    return "far"


@dataclass
class BeaconContact:
    member_id: str
    alias: str                   # local name you set, or "" (never from the wire)
    bearing_dd: int              # bearing in decidegrees (0=ahead, +right)
    band: str                    # "close" | "near" | "far"
    fresh: bool


class Beacon:
    def __init__(self, mesh, now_fn=None, privacy=None):
        self._mesh = mesh
        self._now = now_fn or time.time
        # Recall gate for the inbound circle (Veil/Recall Gate integrity, audit
        # 2026-07-15). Folding a peer's bearing in and pulsing it onto MY rim is
        # a read-back onto my device; the full pause veil ("deaf and blind")
        # must silence it. AlwaysOnGate() is the gate-less unit/SDK fallback.
        self._privacy = privacy or AlwaysOnGate()

    # -- emit my own position (bearing + band, never coordinates) ------------

    def emit_position(self, bearing_deg: float,
                      distance_m: Optional[float] = None):
        """Broadcast where I am *relative to me* to the circle. Veil-gated via
        the mesh. Returns the signed MeshPacket or None."""
        body = {"bearing_dd": int(round(bearing_deg * 10)) % 3600,
                "dist": dist_band(distance_m)}
        return self._mesh.emit("bearing", body)

    def receive(self, wire: dict):
        """Fold a peer's bearing packet into the mesh; returns the member.

        Deaf under a full pause veil: while recall is denied we do not fold a
        peer's bearing in, so nothing of theirs is held to be pulsed later
        (Veil/Recall Gate integrity)."""
        if not self._privacy.allow_recall():
            return None
        return self._mesh.receive(wire)

    # -- read the circle ------------------------------------------------------

    def contacts(self) -> list:
        """Everyone found, nearest first. Only members whose last packet was a
        bearing; each tagged with the local alias (never a wire name)."""
        out: list[BeaconContact] = []
        now = self._now()
        for m in self._mesh.members.values():
            if m.kind != "bearing":
                continue
            band = str(m.body.get("dist") or "far")
            out.append(BeaconContact(
                member_id=m.member_id, alias=self._mesh.name_of(m.member_id),
                bearing_dd=int(m.body.get("bearing_dd", 0)),
                band=band if band in BANDS else "far",
                fresh=m.fresh(now)))
        out.sort(key=lambda c: (not c.fresh, _BAND_RANK.get(c.band, 3),
                                c.bearing_dd))
        return out

    def render_frames(self) -> list:
        """A device frame per fresh contact: a pulse train at their bearing,
        cadence set by distance band (reuses the TinCan pulse-train shape).

        Blind under a full pause veil: pulsing a peer's bearing reads the circle
        back onto MY rim, so a paused wearer renders nothing (Veil/Recall Gate
        integrity). Incognito does not blind the rim."""
        if not self._privacy.allow_recall():
            return []
        frames = []
        for c in self.contacts():
            if not c.fresh:
                continue
            bright, gap = _BAND_PULSE.get(c.band, _BAND_PULSE["far"])
            frames.append({"t": MSG_BEACON, "side_dd": c.bearing_dd,
                           "band": c.band, "bright": bright, "gap_ms": gap})
        return frames

    def card(self) -> Optional[dict]:
        """A BeaconCard listing who's found and roughly where. None when the
        circle is empty — or when the full pause veil silences recall, since the
        card reads the circle back onto the screen (Veil/Recall Gate integrity)."""
        if not self._privacy.allow_recall():
            return None
        found = [c for c in self.contacts() if c.fresh]
        if not found:
            return None
        rows = []
        for c in found:
            who = c.alias or "a friend"
            rows.append({"who": who, "where": _bearing_word(c.bearing_dd),
                         "band": c.band})
        return {"type": "BeaconCard", "found": len(found), "contacts": rows}


# -- turn a bearing into a human word ----------------------------------------

_DIRS = [(0, "ahead"), (45, "ahead-right"), (90, "right"), (135, "behind-right"),
         (180, "behind"), (225, "behind-left"), (270, "left"),
         (315, "ahead-left"), (360, "ahead")]


def _bearing_word(bearing_dd: int) -> str:
    deg = (bearing_dd / 10.0) % 360
    best = min(_DIRS, key=lambda d: abs(d[0] - deg))
    return best[1]
