"""v2/transport.py — BLE envelopes for figments, in lockstep with
halo-lua/ble/message_types.lua.

Figments travel as data over the existing 4-byte-length-framed JSON
envelope protocol (ble/protocol.lua). New message types (mirrored in
message_types.lua — keep both files in sync):

  host → Halo
    figment_put     {t, id, figment, hash}    stage stores it (inactive)
    figment_swap    {t, id}                   hot-swap between ticks
    figment_revoke  {t, id}                   stop + clear, go ambient
    figment_text    {t, id, text}             push into the text slot

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


def put_envelope(fig: Figment) -> dict:
    return {"t": FIGMENT_PUT, "id": fig.id, "figment": fig.to_dict(),
            "hash": content_hash(fig)}


def swap_envelope(figment_id: str) -> dict:
    return {"t": FIGMENT_SWAP, "id": figment_id}


def revoke_envelope(figment_id: str) -> dict:
    return {"t": FIGMENT_REVOKE, "id": figment_id}


def text_envelope(figment_id: str, text: str) -> dict:
    return {"t": FIGMENT_TEXT, "id": figment_id, "text": text[:64]}


def frame(envelope: dict) -> bytes:
    """4-byte big-endian total-length header + JSON body, exactly the
    framing ble/protocol.lua reassembles."""
    body = json.dumps(envelope, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    total = len(body) + 4
    return total.to_bytes(4, "big") + body


def parse_frame(raw: bytes) -> dict:
    total = int.from_bytes(raw[:4], "big")
    if total != len(raw):
        raise ValueError(f"frame length header {total} != actual {len(raw)}")
    return json.loads(raw[4:].decode("utf-8"))
