"""dreamlayer.confluence — two wearers, one entangled sky.

When two DreamLayer wearers bond (explicit, mutual, revocable, and
expiring on its own), their palette weathers entangle: each display
renders the blend of both nervous systems' weather. Converge and the
shared sky settles into one coherent front; drift and you watch the sky
split. An empathy instrument disguised as ambience — nothing is said,
nothing is measured out loud.

Over the same bond:
  TinCan        silent gesture pings — taps play as light on the
                partner's rim
  Crossing      shared future ghosts where both rhythms already meet
                (salted place-hashes; schedules never cross)
  DuetSession   two performers, one figment — a behavior rehearsed
                together, signed separately, revoked independently
  Weather Gift  hand a recorded moment across: their sky plays your
                morning for thirty seconds

The privacy contract is the architecture: only weather crosses the
bond (a state scalar + four palette slots, HMAC'd against the bond
key); veils silence senders; a quiet peer fades; dissolve is unilateral.
"""
from .bond import BondManager, Bond, BondOffer, WeatherPacket, BOND_TTL_S
from .entangle import EntangledSky, MSG_CONFLUENCE
from .tincan import TinCan, MSG_TINCAN
from .crossing import SharedRhythms, RhythmClaim, export_claims, crossings
from .duet import DuetSession, keep_for_both
from .gift import wrap_gift, unwrap_gift, GIFT_PLAY_S
from .taps import TapCollector

__all__ = [
    "BondManager", "Bond", "BondOffer", "WeatherPacket", "BOND_TTL_S",
    "EntangledSky", "MSG_CONFLUENCE",
    "TinCan", "MSG_TINCAN",
    "SharedRhythms", "RhythmClaim", "export_claims", "crossings",
    "DuetSession", "keep_for_both",
    "wrap_gift", "unwrap_gift", "GIFT_PLAY_S",
    "TapCollector",
]
