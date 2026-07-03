"""pairing.py — connect phone + brain + glasses with one code.

Pairing should be a scan, not a setup wizard. The Mac mini Brain shows a
pairing code (the panel renders it as a QR); the phone reads it and is
instantly wired to the Brain. The same bundle can carry the glasses' BLE id
so one code brings the whole trio together.

    bundle = PairingBundle(brain_url="http://studio-mbp.local:7777",
                           token="rune-birch", glasses_id="HALO-9F2A")
    code = encode_pairing(bundle)          # → shown as a QR on the Brain panel
    # …phone scans…
    connect_all(orc, decode_pairing(code)) # phone now talks to Brain + glasses

The code is a compact, URL-safe base64 of a tiny JSON — no secrets beyond the
pairing token you already chose, and it only ever travels the way you show it
(a QR on your own screen).
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, asdict
from typing import Optional

SCHEME = "dreamlayer"          # dreamlayer:<base64> for deep-link / QR


@dataclass
class PairingBundle:
    brain_url: str = ""
    token: str = ""
    glasses_id: str = ""       # BLE identifier of the glasses (optional)
    label: str = "DreamLayer"
    relay_url: str = ""        # reach the Brain off your LAN (optional)


def encode_pairing(bundle: PairingBundle) -> str:
    payload = {k: v for k, v in asdict(bundle).items() if v}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return SCHEME + ":" + base64.urlsafe_b64encode(raw).decode("ascii")


def decode_pairing(code: str) -> PairingBundle:
    s = code.strip()
    if s.startswith(SCHEME + ":"):
        s = s[len(SCHEME) + 1:]
    raw = base64.urlsafe_b64decode(s.encode("ascii"))
    data = json.loads(raw.decode("utf-8"))
    return PairingBundle(
        brain_url=data.get("brain_url", ""), token=data.get("token", ""),
        glasses_id=data.get("glasses_id", ""),
        label=data.get("label", "DreamLayer"),
        relay_url=data.get("relay_url", ""))


def connect_all(orchestrator, bundle: PairingBundle,
                http_post=None, encode_frame=None) -> dict:
    """Wire a phone (orchestrator) to a paired Brain (and note the glasses).

    Registers the Brain as the laptop tier on the orchestrator's router and
    records the glasses id. Returns a small status dict.
    """
    from .ai_brain import connect_brain
    connected_brain = bool(bundle.brain_url)
    if connected_brain:
        connect_brain(orchestrator.brain, bundle.brain_url, bundle.token,
                      http_post=http_post, encode_frame=encode_frame)
        # a paired Brain is the Mac mini tier — actually use it (leave phone-only)
        if hasattr(orchestrator, "connect_mac_mini"):
            orchestrator.connect_mac_mini(True)
        # remember where to poll for live message pop-ups
        if hasattr(orchestrator, "brain_url"):
            orchestrator.brain_url = bundle.brain_url
            orchestrator.brain_token = bundle.token
    if bundle.glasses_id:
        orchestrator.glasses_id = bundle.glasses_id
    return {"brain": connected_brain, "glasses": bool(bundle.glasses_id),
            "url": bundle.brain_url}
