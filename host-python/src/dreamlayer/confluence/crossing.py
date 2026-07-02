"""confluence/crossing.py — shared future ghosts: where your rhythms meet.

Both wearers' Premonition models know their own recurrences. A crossing
is an hour where both rhythms predict presence at the same place — "we
both tend to be at the café Thursday at 15:00" — and it shimmers on BOTH
horizons as a shared future ghost.

Privacy shape: what crosses the bond is not your rhythm. Each side
exports only salted place-hashes of its predictable slots
(weekday, hour, H(salt|place)); the salt is the bond key, so the export
is meaningless outside this bond and unlinkable across bonds. Summaries,
kinds, and confidences never leave the phone. The intersection is
computed independently on each side — nobody learns the other's
schedule, only the overlap both already share.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class RhythmClaim:
    """One anonymized predictable slot: when + a salted where."""
    weekday: int
    hour: int
    place_hash: str


def export_claims(model, bond_key: bytes,
                  min_days: int = 2) -> list[dict]:
    """A Premonition model's predictable slots, anonymized for the bond.
    Suppressed and thin slots never leave the phone."""
    claims = []
    for slot, stats in model._slots.items():
        weekday, hour, _kind, _head, place = slot
        if len(stats.days) < min_days or stats.suppressed() or not place:
            continue
        claims.append({
            "wd": weekday, "h": hour,
            "p": hashlib.sha256(bond_key + place.encode())
                        .hexdigest()[:16],
        })
    # de-dup (several rhythms at one place-hour are one claim)
    seen, out = set(), []
    for c in claims:
        key = (c["wd"], c["h"], c["p"])
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def crossings(my_model, peer_claims: list[dict],
              bond_key: bytes) -> list[RhythmClaim]:
    """Hours where both rhythms predict the same salted place."""
    mine = {(c["wd"], c["h"], c["p"])
            for c in export_claims(my_model, bond_key)}
    out = []
    for c in peer_claims or []:
        key = (int(c.get("wd", -1)), int(c.get("h", -1)),
               str(c.get("p", "")))
        if key in mine:
            out.append(RhythmClaim(weekday=key[0], hour=key[1],
                                   place_hash=key[2]))
    return sorted(out, key=lambda r: (r.weekday, r.hour))


class SharedRhythms:
    """A Premonition-shaped provider the HorizonComposer can consume:
    crossings render as future ghosts on both rings, through the exact
    kind-6 path Premonition already ships."""

    def __init__(self, my_model, bond_key: bytes) -> None:
        self._model = my_model
        self._key = bond_key
        self._crossings: list[RhythmClaim] = []

    def update(self, peer_claims: list[dict]) -> list[RhythmClaim]:
        self._crossings = crossings(self._model, peer_claims, self._key)
        return list(self._crossings)

    def predict(self, now):
        """Only the predictions of MY model that fall on a crossing —
        a shared ghost is my own rhythm, confirmed by yours."""
        crossing_keys = {(c.weekday, c.hour) for c in self._crossings}
        return [p for p in self._model.predict(now)
                if (p.slot[0], p.slot[1]) in crossing_keys]
