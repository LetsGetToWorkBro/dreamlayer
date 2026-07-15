"""confluence/entangle.py — two nervous systems, one sky.

Each tick, my inner-weather state and palette meet the peer's latest
authenticated WeatherPacket. The blend is governed by one number:

  togetherness = 1 − |my_state − peer_state|, EMA-smoothed

  high  → MERGED: one coherent front — both palettes blend 50/50 into
          the sky/energy slots; the seam disappears
  low   → SPLIT: the sky divides — my weather keeps my half, the peer's
          half renders in their colors, and a visible seam stands where
          the fronts meet, drifting wider as we diverge

Nothing is said, nothing is measured out loud. The room just shows you
whether you're actually together.

Division of labor: all color math happens here on the phone; the device
receives one standard palette frame (the blended/mine sky) plus a
{t="confluence"} frame carrying only what it must draw — mode, the
seam angle, the peer's half-sky as a ready RGB, and a coherence value
for the seam's softness. A peer gone quiet (veiled, out of range)
fades: after PEER_STALE_S their weather stops influencing the sky and
a final solo frame restores it.
"""
from __future__ import annotations

import time
from typing import Optional

from ..memory.privacy import AlwaysOnGate

# keep in lockstep with halo-lua/ble/message_types.lua (CONFLUENCE)
MSG_CONFLUENCE = "confluence"

TOGETHER_ALPHA = 0.2
MERGE_THRESHOLD = 0.72        # above: one front
SPLIT_THRESHOLD = 0.55        # below: the sky divides (hysteresis band)
PEER_STALE_S = 12.0
EMIT_HYSTERESIS = 0.04
SEAM_BASE_DEG = -90.0         # the seam stands between the two of you


def _slot_rgb(colors: list, idx: int) -> tuple[int, int, int]:
    """YCbCr slot dict → approximate RGB (BT.601), for the peer band."""
    for c in colors or []:
        if c.get("idx") == idx:
            y = float(c.get("y", 512)) / 4.0
            cb = float(c.get("cb", 512)) / 4.0 - 128.0
            cr = float(c.get("cr", 512)) / 4.0 - 128.0
            r = y + 1.402 * cr
            g = y - 0.344 * cb - 0.714 * cr
            b = y + 1.772 * cb
            return (max(0, min(255, int(r))), max(0, min(255, int(g))),
                    max(0, min(255, int(b))))
    return (60, 70, 75)


def _blend_colors(mine: list, theirs: list) -> list:
    """50/50 YCbCr blend, slot by slot — the single coherent front."""
    theirs_by_idx = {c.get("idx"): c for c in theirs or []}
    out = []
    for c in mine or []:
        p = theirs_by_idx.get(c.get("idx"))
        if p is None:
            out.append(dict(c))
            continue
        out.append({"idx": c.get("idx"),
                    "y":  (int(c.get("y", 512)) + int(p.get("y", 512))) // 2,
                    "cb": (int(c.get("cb", 512)) + int(p.get("cb", 512))) // 2,
                    "cr": (int(c.get("cr", 512)) + int(p.get("cr", 512))) // 2})
    return out


class EntangledSky:
    def __init__(self, bonds, now_fn=None, privacy=None) -> None:
        self._bonds = bonds                  # BondManager
        self._now = now_fn or time.time
        # Recall gate for the inbound peer sky (Veil/Recall Gate integrity,
        # audit 2026-07-15). Folding in and re-painting the peer's weather is a
        # read-back onto MY device; the full pause veil ("deaf and blind") must
        # silence it. AlwaysOnGate() is the permissive fallback for the
        # gate-less unit/SDK case — production injects the real PrivacyGate.
        self._privacy = privacy or AlwaysOnGate()
        self.togetherness = 0.5
        self._peer_state: Optional[float] = None
        self._peer_colors: list = []
        self._peer_seen = -1e12
        self._last_mode: Optional[str] = None
        self._last_emit_tg: Optional[float] = None

    # -- inbound ----------------------------------------------------------

    def receive(self, wire: dict) -> bool:
        """Feed a peer packet (already-authenticated path lives in the
        BondManager). Returns True if it was genuine.

        Deaf under a full pause veil: while recall is denied we do not fold the
        peer's weather in at all, so nothing of theirs is held to be re-painted
        later (Veil/Recall Gate integrity)."""
        if not self._privacy.allow_recall():
            return False
        pkt = self._bonds.receive_weather(wire)
        if pkt is None:
            return False
        self._peer_state = pkt.state
        self._peer_colors = pkt.colors
        self._peer_seen = self._now()
        return True

    def peer_present(self) -> bool:
        return (self._peer_state is not None
                and (self._now() - self._peer_seen) < PEER_STALE_S)

    # -- the sky ------------------------------------------------------------

    def tick(self, my_state: float, my_colors: list) -> list[dict]:
        """Frames for MY device this tick (and the outbound packet is a
        separate concern — see BondManager.send_weather).

        Blind under a full pause veil: rendering the shared/split sky reads the
        peer's weather back onto MY device, so a paused wearer renders nothing
        (Veil/Recall Gate integrity). Incognito does not blind the sky."""
        if not self._privacy.allow_recall():
            return []
        if not self.peer_present():
            if self._last_mode is not None:
                self._last_mode = None
                self._last_emit_tg = None
                return [{"t": MSG_CONFLUENCE, "mode": "solo"}]
            return []

        assert self._peer_state is not None   # peer_present() above implies a peer state
        raw = 1.0 - min(1.0, abs(float(my_state) - self._peer_state))
        self.togetherness += TOGETHER_ALPHA * (raw - self.togetherness)
        tg = self.togetherness

        # hysteresis band keeps the sky from flapping at the boundary
        if self._last_mode == "merged":
            mode = "merged" if tg > SPLIT_THRESHOLD else "split"
        elif self._last_mode == "split":
            mode = "split" if tg < MERGE_THRESHOLD else "merged"
        else:
            mode = "merged" if tg >= MERGE_THRESHOLD else "split"

        changed = mode != self._last_mode
        moved = (self._last_emit_tg is None
                 or abs(tg - self._last_emit_tg) >= EMIT_HYSTERESIS)
        if not (changed or moved):
            return []
        self._last_mode = mode
        self._last_emit_tg = tg

        frames: list[dict] = []
        if mode == "merged":
            frames.append({"t": "palette",
                           "colors": _blend_colors(my_colors,
                                                   self._peer_colors)})
            frames.append({"t": MSG_CONFLUENCE, "mode": "merged",
                           "tg": int(round(tg * 100))})
        else:
            # my half keeps my weather; the peer's half arrives as one
            # ready RGB so the device does zero color math
            frames.append({"t": "palette", "colors": my_colors})
            divergence = 1.0 - tg
            frames.append({
                "t": MSG_CONFLUENCE, "mode": "split",
                "tg": int(round(tg * 100)),
                "seam_dd": int(round(SEAM_BASE_DEG * 10)),
                "gap_deg": int(round(8 + 32 * divergence)),
                "peer_rgb": list(_slot_rgb(self._peer_colors, 1)),
            })
        return frames
