"""v2/transport.py — BLE envelopes for figments, in lockstep with
halo-lua/ble/message_types.lua.

Figments travel as data over the existing 4-byte-length-framed JSON
envelope protocol (ble/protocol.lua). New message types (mirrored in
message_types.lua — keep both files in sync):

  host → Halo
    figment_put     {t, id, figment, hash}    stage stores it (inactive)
    figment_swap    {t, id}                   hot-swap between ticks
    figment_revoke  {t, id}                   stop + clear, go ambient
    figment_text    {t, id, text, slot?}      push into the (named) text slot
    event           {t, name}                 a physical-world signal (e.g.
                                              "ble:3") delivered to the running
                                              figment's scene grammar

  Halo → host
    figment_ack     {t, id, ok, hash}         put/swap/revoke result
    figment_event   {t, id, tag}              rate-limited emit from a
                                              running figment
"""
from __future__ import annotations

import json

from .figment import Figment
from .signer import content_hash

# message type constants (mirror ble/message_types.lua)
FIGMENT_PUT    = "figment_put"
FIGMENT_SWAP   = "figment_swap"
FIGMENT_REVOKE = "figment_revoke"
FIGMENT_TEXT   = "figment_text"
FIGMENT_ACK    = "figment_ack"
FIGMENT_EVENT  = "figment_event"
EVENT          = "event"           # host → Halo: a generic named world signal


def put_envelope(fig: Figment) -> dict:
    return {"t": FIGMENT_PUT, "id": fig.id, "figment": fig.to_dict(),
            "hash": content_hash(fig)}


def swap_envelope(figment_id: str) -> dict:
    return {"t": FIGMENT_SWAP, "id": figment_id}


def revoke_envelope(figment_id: str) -> dict:
    return {"t": FIGMENT_REVOKE, "id": figment_id}


def text_envelope(figment_id: str, text: str, slot: str = "") -> dict:
    """Push host text into a figment's slot. The default (empty) slot fills
    the `{slot}` token; a named slot fills `{slot:<name>}`. The stage bounds
    both the value length and the number of distinct named slots."""
    env = {"t": FIGMENT_TEXT, "id": figment_id, "text": text[:64]}
    if slot:
        env["slot"] = str(slot)[:32]
    return env


def event_envelope(name: str) -> dict:
    """A physical-world signal for the *running* figment (whichever it is) —
    e.g. a reed switch closing becomes `event {name:"ble:3"}`, which the
    scene grammar can list as an exit. Names are clamped: the device only
    ever acts on names its active figment's scenes actually listen for."""
    return {"t": EVENT, "name": str(name)[:32]}


try:  # optional, compact wire codec — extras group `memory`/`platform`
    import cbor2  # type: ignore
    _HAS_CBOR = True
except Exception:
    cbor2 = None                        # type: ignore
    _HAS_CBOR = False


def frame(envelope: dict, codec: str = "json") -> bytes:
    """4-byte big-endian total-length header + body.

    ``codec="json"`` (default) is byte-for-byte what ble/protocol.lua
    reassembles today — the device wire is unchanged. ``codec="cbor"`` emits a
    compact, self-describing CBOR body instead (fewer bytes over the air, a real
    schema at the type layer); it is auto-detected on parse, so a JSON reader is
    never handed a CBOR frame it can't read. CBOR is host/phone-ready now;
    flipping the *device* default needs a Lua CBOR decoder on-glass (an owner
    action — see docs/CONCURRENCY.md hardware seams), so JSON stays the default.

    The bodies are distinguishable by their first byte — canonical JSON always
    starts with ``{`` (0x7B); CBOR maps start in 0xA0–0xBF — so the reader sniffs
    without a version byte, keeping old frames valid."""
    if codec == "cbor":
        if not _HAS_CBOR:
            raise RuntimeError("cbor2 not installed (extras: memory/platform)")
        body = cbor2.dumps(envelope, canonical=True)
    else:
        body = json.dumps(envelope, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
    total = len(body) + 4
    return total.to_bytes(4, "big") + body


def parse_frame(raw: bytes) -> dict:
    """Reassemble a frame, auto-detecting JSON vs CBOR from the first body byte
    (JSON `{` = 0x7B; CBOR map = 0xA0–0xBF). Old JSON frames parse unchanged."""
    total = int.from_bytes(raw[:4], "big")
    if total != len(raw):
        raise ValueError(f"frame length header {total} != actual {len(raw)}")
    body = raw[4:]
    if body[:1] == b"{":
        return json.loads(body.decode("utf-8"))
    if 0xA0 <= body[0] <= 0xBF:          # a CBOR map
        if not _HAS_CBOR:
            raise RuntimeError("frame is CBOR but cbor2 is not installed")
        return cbor2.loads(body)
    # fall back to JSON (e.g. a non-object payload) for backward compatibility
    return json.loads(body.decode("utf-8"))
