"""confluence/gift.py — a Weather Gift: this is what my morning felt like.

Pick a moment from your own WeatherLedger and hand it across the bond:
your partner's sky plays your recorded ambience for GIFT_PLAY_S seconds
— the light of your morning kitchen washing over their afternoon — then
their own weather flows back.

What crosses: one palette snapshot (four YCbCr slot dicts) and an hour
label. Never the place, never the day's events, never anything the
snapshot itself doesn't already show as pure color. Sending is a
deliberate act (an explicit call, never ambient), veil-gated on the
sender, and the receiver's replay is just palette frames — the same
verbatim-history machinery Yesterlight already trusts.
"""
from __future__ import annotations

from ..memory.privacy import AlwaysOnGate

GIFT_PLAY_S = 30.0
GIFT_FRAME_EVERY_S = 5.0     # re-assert the gifted sky at ledger cadence


def wrap_gift(bonds, snapshot) -> dict | None:
    """Sender: one ledger snapshot → an authenticated gift, or None
    (no bond / veiled)."""
    pkt = bonds.send_weather(state=-1.0, colors=snapshot.colors)
    if pkt is None:
        return None
    wire = pkt.to_wire()
    wire["gift"] = {"hour": int((snapshot.ts % 86400) // 3600)}
    return wire


def unwrap_gift(bonds, wire: dict, privacy=None) -> list[dict]:
    """Receiver: an authenticated gift → the palette frames that play it.
    A forged or unbonded gift plays nothing.

    Recall-gated (Veil/Recall Gate integrity, audit 2026-07-15): replaying a
    peer's gifted sky paints their recorded moment onto YOUR device — a
    read-back the full pause veil must silence ("deaf and blind"), so a paused
    wearer plays nothing even from a perfectly authentic gift. Incognito does
    NOT block it (recall survives incognito; only capture stops). Defaults to
    AlwaysOnGate() for the gate-less unit/SDK case."""
    gate = privacy or AlwaysOnGate()
    if not gate.allow_recall():
        return []
    pkt = bonds.receive_weather(wire)
    if pkt is None or "gift" not in wire:
        return []
    frames = []
    plays = int(GIFT_PLAY_S / GIFT_FRAME_EVERY_S)
    for _ in range(max(1, plays)):
        frames.append({"t": "palette", "colors": pkt.colors})
    return frames
