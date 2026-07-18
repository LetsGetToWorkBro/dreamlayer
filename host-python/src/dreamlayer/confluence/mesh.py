"""confluence/mesh.py — GhostMode: the pairwise bond, lifted to a group.

`bond.py` is a doorway between *two* wearers. A mesh is a *circle* of them — a
room, a hiking party, a crowd of friends — sharing one group key and gossiping
tiny packets to each other. It is the same crypto family and the same privacy
contract, one level up.

The contract, unchanged from the bond:

  - Only *feeling* crosses. A packet body is a weather scalar, a palette, a
    bearing + distance band, or a gesture symbol. **Never speech, places
    (absolute coordinates), or names.** Members are anonymous on the wire — a
    random `member_id`, nothing more. Any human name you attach ("that's
    Maya") lives only on *your* device (`alias`), exactly like a bond peer.
  - Your Privacy Veil silences your side completely (`emit` returns None).
  - Forged / replayed / stranger / self traffic is dropped silently.
  - A quiet member fades after QUIET_FADE_S; the whole group expires after
    GROUP_TTL_S unless renewed; leaving is unilateral.

Transport is a seam. `MeshTransport.send/recv` is injectable — the default is
an in-memory bus (tests, demo); on Halo the real one is BLE **LE Coded PHY**
(long-range, robust in a crowd), phone-relayed for reach. Nothing above the
seam knows the radio.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

from .bond import _WORDS         # reuse the human-code word list

GROUP_TTL_S = 8 * 3600.0         # a group is an evening, not a tracker
QUIET_FADE_S = 12.0              # a silent member fades from the circle
CODE_WORDS = 3                   # a group code is a touch longer than a bond's

# The ε-budget a single group's shared-view queries may spend in total. Small on
# purpose: a group "mood ring" is a glance, not an analytics endpoint, and a tight
# budget bounds how much repeated peeks can reveal about any one member.
MESH_DP_BUDGET = 3.0
# The public, fixed band vocabulary the group summary is released over. A FIXED
# category set is itself privacy-preserving: the histogram never reveals which
# exotic values were present, only the counts in these known buckets.
WEATHER_BANDS = ("storm", "grey", "clear")


def _weather_band(state) -> str:
    """Bucket a weather scalar (-1..1) into a public band label."""
    try:
        s = float(state)
    except (TypeError, ValueError):
        return "grey"
    if s < -0.33:
        return "storm"
    if s > 0.33:
        return "clear"
    return "grey"


# Per-GROUP-ID DP budgets that SURVIVE rejoin / reconnect / a second manager
# instance. A per-manager budget reset every _bind, so an attacker who keeps
# receiving the circle's packets could re-join in a loop, collect unlimited
# independent noisy releases of the same slowly-changing histogram, and average
# the Laplace noise back to zero — recovering the exact per-member values the DP
# was added to hide (refute 2026-07-18). Keying the budget on the group_id (which
# is fixed for the life of a circle) closes that: rejoining the same circle
# reuses its spent budget. Entries are pruned once a group has outlived
# GROUP_TTL_S, so this stays bounded.
_GROUP_BUDGETS: dict = {}      # group_id -> [PrivacyAccountant, last_used_ts]


def _reset_group_budgets() -> None:
    """Test hook: drop all persisted per-group DP budgets."""
    _GROUP_BUDGETS.clear()


def _group_budget(group_id: str, now: float, total: float):
    from ..differential_privacy import PrivacyAccountant
    for gid in [g for g, (_, ts) in _GROUP_BUDGETS.items() if now - ts > GROUP_TTL_S]:
        _GROUP_BUDGETS.pop(gid, None)          # expired circles free their budget
    entry = _GROUP_BUDGETS.get(group_id)
    if entry is None:
        entry = [PrivacyAccountant(total), now]
        _GROUP_BUDGETS[group_id] = entry
    else:
        entry[1] = now
    return entry[0]


# --- the only traffic: a tiny, signed, anonymous packet ---------------------

@dataclass
class MeshPacket:
    group_id: str
    sender: str                  # a random member id — never a name
    seq: int
    kind: str                    # "weather" | "bearing" | "gesture"
    body: dict                   # small: {state,colors} | {bearing_dd,dist} | {sym}
    mac: str = ""

    _FIELDS = ("group_id", "sender", "seq", "kind", "body")

    def payload(self) -> str:
        return json.dumps({k: getattr(self, k) for k in self._FIELDS},
                          sort_keys=True, separators=(",", ":"))

    def to_wire(self) -> dict:
        return {**json.loads(self.payload()), "mac": self.mac}

    @staticmethod
    def from_wire(d: dict) -> "MeshPacket":
        return MeshPacket(group_id=d["group_id"], sender=str(d["sender"]),
                          seq=int(d["seq"]), kind=str(d["kind"]),
                          body=dict(d.get("body") or {}), mac=d.get("mac", ""))


def _derive_group_key(group_id: str, code: str) -> bytes:
    return hashlib.sha256(f"ghostmesh|{group_id}|{code}".encode()).digest()


def _mac(key: bytes, payload: str) -> str:
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()[:24]


# --- transport seam: in-memory today, coded PHY on Halo ---------------------

@runtime_checkable
class MeshTransport(Protocol):
    def send(self, wire: dict) -> None: ...
    def recv(self) -> list: ...


class InMemoryBus:
    """A shared bus for tests/demo — every manager attached to it sees every
    other's sends (never its own). Stands in for the coded-PHY flood."""

    def __init__(self):
        self._queues: dict[str, list] = {}

    def attach(self, member_id: str) -> None:
        self._queues.setdefault(member_id, [])

    def send_from(self, member_id: str, wire: dict) -> None:
        for mid, q in self._queues.items():
            if mid != member_id:
                q.append(wire)

    def drain(self, member_id: str) -> list:
        q = self._queues.get(member_id, [])
        out, q[:] = list(q), []
        return out


# --- a member of the circle, as seen locally --------------------------------

@dataclass
class MeshMember:
    member_id: str
    last_seen: float
    last_seq: int = -1
    kind: str = ""               # last packet kind
    body: dict = field(default_factory=dict)   # last body (bearing/weather)

    def fresh(self, now: float, fade: float = QUIET_FADE_S) -> bool:
        return (now - self.last_seen) < fade


# --- the group + its manager ------------------------------------------------

class MeshManager:
    """Form or join a group, emit your feeling to the circle, and receive the
    others'. Anonymous on the wire; names (aliases) never leave the device."""

    def __init__(self, privacy=None, now_fn=None,
                 me: Optional[str] = None):
        self._privacy = privacy
        self._now = now_fn or time.time
        self.me = me or secrets.token_hex(6)
        self.group_id: str = ""
        self._key: Optional[bytes] = None
        self._created: float = 0.0
        self._dissolved = False
        self._seq_out = 0
        self.members: dict[str, MeshMember] = {}
        self._aliases: dict[str, str] = {}     # member_id -> local name, on-device only

    # -- form / join / leave --------------------------------------------------

    def form(self, label: str = "ghostmode") -> tuple[str, str]:
        """Start a circle. Returns (group_id, code) to pass to the others (the
        same human-code handshake as a bond, just shared with more people)."""
        gid = secrets.token_hex(6)
        code = "-".join(secrets.choice(_WORDS) for _ in range(CODE_WORDS))
        self._bind(gid, code)
        return gid, code

    def join(self, group_id: str, code: str) -> None:
        """Join a circle you were given the code for."""
        self._bind(group_id, code)

    def _bind(self, group_id: str, code: str) -> None:
        self.group_id = group_id
        self._key = _derive_group_key(group_id, code)
        self._created = self._now()
        self._dissolved = False
        self._seq_out = 0
        self.members = {}

    def leave(self) -> None:
        self._dissolved = True

    def live(self) -> bool:
        return (self._key is not None and not self._dissolved
                and (self._now() - self._created) < GROUP_TTL_S)

    # -- local aliasing (never crosses) --------------------------------------

    def alias(self, member_id: str, name: str) -> None:
        """Label a member locally ('that pulse is Maya'). Stays on this device
        — the mesh never carries a name."""
        self._aliases[member_id] = name

    def name_of(self, member_id: str) -> str:
        return self._aliases.get(member_id, "")

    # -- the only traffic -----------------------------------------------------

    def emit(self, kind: str, body: dict) -> Optional[MeshPacket]:
        """Sign a packet for the circle — or nothing if veiled or not in a live
        group. The Veil silences the sender completely."""
        if self._privacy is not None and not self._privacy.allow_capture():
            return None
        if not self.live():
            return None
        self._seq_out += 1
        pkt = MeshPacket(group_id=self.group_id, sender=self.me,
                         seq=self._seq_out, kind=kind, body=dict(body or {}))
        assert self._key is not None   # a group is joined (key derived) before sending
        pkt.mac = _mac(self._key, pkt.payload())
        return pkt

    def receive(self, wire: dict) -> Optional[MeshMember]:
        """Authenticate a circle packet and fold it into the member's state.
        Forged / replayed / stranger / self / stale-group traffic is dropped
        silently. Returns the updated member, or None if rejected."""
        if not self.live():
            return None
        assert self._key is not None   # live() is False until a group key is derived
        try:
            pkt = MeshPacket.from_wire(wire)
        except (KeyError, TypeError, ValueError):
            return None
        if pkt.group_id != self.group_id:
            return None                        # a different circle
        if pkt.sender == self.me:
            return None                        # my own echo
        if not hmac.compare_digest(_mac(self._key, pkt.payload()), pkt.mac or ""):
            return None                        # forged
        now = self._now()
        m = self.members.get(pkt.sender)
        if m is not None and pkt.seq <= m.last_seq:
            return None                        # replay / out of order
        if m is None:
            m = MeshMember(member_id=pkt.sender, last_seen=now)
            self.members[pkt.sender] = m
        m.last_seq = pkt.seq
        m.last_seen = now
        m.kind = pkt.kind
        m.body = pkt.body
        return m

    def active(self, fade: float = QUIET_FADE_S) -> list:
        """Members heard from within the fade window — the live circle."""
        now = self._now()
        return [m for m in self.members.values() if m.fresh(now, fade)]

    # -- the shared view: a DP-protected group summary -----------------------
    def dp_group_summary(self, epsilon: float = 1.0,
                         fade: float = QUIET_FADE_S,
                         my_state=None) -> Optional[dict]:
        """A differentially-private view of the circle's collective feeling: a
        noisy headcount and a noisy histogram of weather bands.

        Releasing an EXACT group aggregate to a small circle leaks each member —
        in a group of three, a mean that jumps the instant you speak has told
        everyone your value. This adds calibrated Laplace noise (sensitivity 1
        per member) and spends from a fixed per-group ε-budget, so repeated peeks
        can't average the noise away; once the budget is spent the summary is
        refused (returns None) rather than leaking further. Optionally folds in
        the wearer's own current ``my_state`` as one member. Returns None when
        the group isn't live."""
        if not self.live() or epsilon <= 0:
            return None
        from ..differential_privacy import DPAggregator, PrivacyBudgetExceeded
        acct = _group_budget(self.group_id, self._now(), MESH_DP_BUDGET)
        # Pre-check the WHOLE epsilon so we never burn the count's half and then
        # fail on the histogram's — the release is all-or-nothing.
        if not acct.can_spend(epsilon):
            return None
        bands = [_weather_band(m.body.get("state"))
                 for m in self.active(fade) if m.kind == "weather"]
        if my_state is not None:
            bands.append(_weather_band(my_state))
        agg = DPAggregator(acct)
        try:
            # split ε: half for the headcount, half for the band histogram
            half = epsilon / 2.0
            headcount = agg.count(len(bands), half)
            histogram = agg.histogram(bands, WEATHER_BANDS, half)
        except (PrivacyBudgetExceeded, ValueError):
            return None
        return {"members": headcount, "bands": histogram,
                "epsilon_remaining": acct.remaining}
