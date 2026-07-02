"""confluence/bond.py — the handshake: explicit, mutual, revocable.

A bond is the only doorway between two DreamLayer wearers, and it opens
from both sides or not at all:

  1. A proposes:  offer = BondManager.propose("dinner with M")
     → a bond id and a short human code (shown on A's phone / spoken)
  2. B accepts the code:  BondManager.accept(offer.bond_id, code)
  3. A confirms B's acceptance:  BondManager.confirm(bond_id)
     Only now is the bond LIVE on either side.

Both sides derive the same link key from (bond_id, code) and every
packet that crosses the link is HMAC'd with it — a stranger's radio
cannot inject weather into your sky.

The privacy contract is the whole point:
  - only WeatherPackets cross: a state scalar, four palette slots, a
    sequence number. No identity, no transcript, no location, ever.
  - your Privacy Veil silences your side completely (nothing sent), and
    a veiled partner simply fades from your sky.
  - dissolve() is unilateral and immediate; bonds also expire on their
    own after BOND_TTL_S without renewal.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional

BOND_TTL_S = 8 * 3600.0        # a bond is an evening, not a surveillance
CODE_WORDS = 2                 # short human-confirmable code


@dataclass
class BondOffer:
    bond_id: str
    code: str                   # spoken/shown between the two humans
    label: str


@dataclass
class WeatherPacket:
    """The only thing that ever crosses a bond."""
    bond_id: str
    seq: int
    state: float                # the sender's inner-weather scalar
    colors: list                # the sender's four palette slot dicts
    mac: str = ""

    _FIELDS = ("bond_id", "seq", "state", "colors")

    def payload(self) -> str:
        return json.dumps({k: getattr(self, k) for k in self._FIELDS},
                          sort_keys=True, separators=(",", ":"))

    def to_wire(self) -> dict:
        return {**json.loads(self.payload()), "mac": self.mac}

    @staticmethod
    def from_wire(d: dict) -> "WeatherPacket":
        return WeatherPacket(bond_id=d["bond_id"], seq=int(d["seq"]),
                             state=float(d["state"]),
                             colors=d.get("colors") or [],
                             mac=d.get("mac", ""))


def _derive_key(bond_id: str, code: str) -> bytes:
    return hashlib.sha256(f"confluence|{bond_id}|{code}".encode()).digest()


def _mac(key: bytes, payload: str) -> str:
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()[:24]


@dataclass
class Bond:
    bond_id: str
    label: str
    key: bytes
    created: float
    proposed_by_me: bool
    accepted_by_peer: bool = False
    confirmed_by_me: bool = False
    dissolved: bool = False
    seq_out: int = 0
    seq_in_last: int = -1

    def live(self, now: float) -> bool:
        return (self.accepted_by_peer and self.confirmed_by_me
                and not self.dissolved
                and (now - self.created) < BOND_TTL_S)


class BondManager:
    def __init__(self, privacy=None, now_fn=None,
                 rng: Optional[secrets.SystemRandom] = None) -> None:
        self._privacy = privacy
        self._now = now_fn or time.time
        self._bonds: dict[str, Bond] = {}

    # -- the three-step mutual opt-in ---------------------------------------

    def propose(self, label: str = "confluence") -> BondOffer:
        bond_id = secrets.token_hex(6)
        code = "-".join(secrets.choice(_WORDS) for _ in range(CODE_WORDS))
        self._bonds[bond_id] = Bond(
            bond_id=bond_id, label=label, key=_derive_key(bond_id, code),
            created=self._now(), proposed_by_me=True)
        return BondOffer(bond_id=bond_id, code=code, label=label)

    def accept(self, bond_id: str, code: str,
               label: str = "confluence") -> Bond:
        """The peer's side: accepting an offer creates the mirror bond
        (accepted, awaiting the proposer's confirmation ping)."""
        bond = Bond(bond_id=bond_id, label=label,
                    key=_derive_key(bond_id, code), created=self._now(),
                    proposed_by_me=False, accepted_by_peer=True,
                    confirmed_by_me=True)
        self._bonds[bond_id] = bond
        return bond

    def confirm(self, bond_id: str) -> Bond:
        """The proposer's side, after the peer's acceptance arrives."""
        bond = self._bonds[bond_id]
        bond.accepted_by_peer = True
        bond.confirmed_by_me = True
        return bond

    def dissolve(self, bond_id: str) -> None:
        if bond_id in self._bonds:
            self._bonds[bond_id].dissolved = True

    def bond(self, bond_id: str) -> Optional[Bond]:
        return self._bonds.get(bond_id)

    def live_bond(self) -> Optional[Bond]:
        now = self._now()
        for bond in self._bonds.values():
            if bond.live(now):
                return bond
        return None

    # -- the only traffic ------------------------------------------------------

    def send_weather(self, state: float,
                     colors: list) -> Optional[WeatherPacket]:
        """Package my weather for the peer — or nothing, if veiled or
        unbonded. The veil silences the sender side completely."""
        if self._privacy is not None and not self._privacy.allow_capture():
            return None
        bond = self.live_bond()
        if bond is None:
            return None
        bond.seq_out += 1
        pkt = WeatherPacket(bond_id=bond.bond_id, seq=bond.seq_out,
                            state=round(float(state), 3),
                            colors=colors or [])
        pkt.mac = _mac(bond.key, pkt.payload())
        return pkt

    def receive_weather(self, wire: dict) -> Optional[WeatherPacket]:
        """Authenticate a peer packet. Forged, replayed, stale, or
        unbonded traffic is dropped silently."""
        try:
            pkt = WeatherPacket.from_wire(wire)
        except (KeyError, TypeError, ValueError):
            return None
        bond = self._bonds.get(pkt.bond_id)
        if bond is None or not bond.live(self._now()):
            return None
        if not hmac.compare_digest(_mac(bond.key, pkt.payload()),
                                   pkt.mac or ""):
            return None
        if pkt.seq <= bond.seq_in_last:
            return None                      # replay
        bond.seq_in_last = pkt.seq
        return pkt


_WORDS = [
    "amber", "birch", "cedar", "delta", "ember", "fjord", "glade",
    "harbor", "indigo", "juniper", "krill", "lumen", "meadow", "nectar",
    "onyx", "prism", "quartz", "rune", "sable", "tide", "umber",
    "violet", "willow", "xenon", "yarrow", "zephyr",
]
