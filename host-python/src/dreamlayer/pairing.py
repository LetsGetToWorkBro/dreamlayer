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
import binascii
import json
from dataclasses import dataclass, asdict

SCHEME = "dreamlayer"          # dreamlayer:<base64> for deep-link / QR

# A pairing code is a tiny JSON (a URL, a short token, a BLE id). Anything much
# larger is not ours — cap the input so a hostile QR/deep-link can't hand us a
# multi-megabyte blob to base64-decode + json-parse (audit 2026-07-14: decode
# had no size cap and no error handling).
_MAX_CODE_LEN = 4096
_OK_SCHEMES = ("http://", "https://")


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


def _checked_url(value: str, field_name: str) -> str:
    """A decoded URL is fed into live HTTP — refuse anything that isn't http(s)
    so a crafted code can't smuggle a file:// / javascript: scheme into the
    connect path (audit 2026-07-14). Empty is allowed (the field is optional)."""
    if value and not value.startswith(_OK_SCHEMES):
        raise ValueError(f"pairing {field_name} must be http(s): {value!r}")
    return value


def decode_pairing(code: str) -> PairingBundle:
    """Decode a pairing code back to a bundle. Raises ``ValueError`` on anything
    malformed (bad base64, non-JSON, oversized, or a non-http(s) URL) so callers
    get one predictable exception type instead of a raw binascii/JSON error."""
    s = (code or "").strip()
    if len(s) > _MAX_CODE_LEN:
        raise ValueError(f"pairing code too long ({len(s)} > {_MAX_CODE_LEN})")
    if s.startswith(SCHEME + ":"):
        s = s[len(SCHEME) + 1:]
    try:
        raw = base64.urlsafe_b64decode(s.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"not a valid pairing code: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("pairing payload is not a JSON object")
    return PairingBundle(
        brain_url=_checked_url(data.get("brain_url", ""), "brain_url"),
        token=data.get("token", ""),
        glasses_id=data.get("glasses_id", ""),
        label=data.get("label", "DreamLayer"),
        relay_url=_checked_url(data.get("relay_url", ""), "relay_url"))


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
