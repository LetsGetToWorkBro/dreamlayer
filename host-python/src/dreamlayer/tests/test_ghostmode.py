"""test_ghostmode.py — the GhostMode mesh + The Beacon.

Pins the group-key handshake, gossip auth (forged / replayed / stranger / self
dropped), membership + fade + expiry, the "only feeling crosses / names never
cross" invariant, the veil gate, and the Beacon's bearing → pulse-train +
card. Transport rides the in-memory bus standing in for coded PHY.
"""
from __future__ import annotations

from dreamlayer.confluence.mesh import (
    MeshManager, GROUP_TTL_S, QUIET_FADE_S,
)
from dreamlayer.confluence.beacon import Beacon, dist_band, _bearing_word


class Clock:
    def __init__(self, t=0.0): self.t = t
    def __call__(self): return self.t


class Veil:
    """Minimal privacy stub: allow_capture() mirrors the real Veil gate."""
    def __init__(self, on=True): self._on = on
    def allow_capture(self): return self._on
    def pause(self): self._on = False


def _circle(n, clock):
    """n managers in one group, wired over a shared in-memory bus."""
    a = MeshManager(now_fn=clock, me="m0")
    gid, code = a.form("party")
    mgrs = [a] + [MeshManager(now_fn=clock, me=f"m{i}") for i in range(1, n)]
    for i, m in enumerate(mgrs):
        if i:
            m.join(gid, code)
    return mgrs, gid, code


def pos_wire(mgr, bearing_deg, distance_m, clock):
    """A member's signed bearing packet, as it'd arrive on the wire."""
    return Beacon(mgr, now_fn=clock).emit_position(bearing_deg, distance_m).to_wire()


# -- the group handshake ------------------------------------------------------

def test_form_and_join_share_one_key():
    clock = Clock()
    (a, b), gid, code = _circle(2, clock)
    pkt = a.emit("weather", {"state": 0.5, "colors": []})
    assert pkt is not None
    m = b.receive(pkt.to_wire())
    assert m is not None and m.member_id == a.me and m.body["state"] == 0.5


def test_a_wrong_code_cannot_join_the_circle():
    clock = Clock()
    (a, _b), gid, code = _circle(2, clock)
    intruder = MeshManager(now_fn=clock, me="x")
    intruder.join(gid, "wrong-wrong-wrong")
    assert a.receive(intruder.emit("weather", {"state": 1.0}).to_wire()) is None


# -- gossip auth: forged / replayed / stranger / self dropped ----------------

def test_forged_mac_is_dropped():
    clock = Clock()
    (a, b), *_ = _circle(2, clock)
    pkt = a.emit("bearing", {"bearing_dd": 900, "dist": "near"})
    wire = pkt.to_wire()
    wire["mac"] = "0" * 24                       # tamper
    assert b.receive(wire) is None


def test_replay_is_dropped():
    clock = Clock()
    (a, b), *_ = _circle(2, clock)
    w = a.emit("weather", {"state": 0.2}).to_wire()
    assert b.receive(w) is not None
    assert b.receive(w) is None                  # same seq again → replay


def test_a_strangers_group_is_ignored():
    clock = Clock()
    (a, b), *_ = _circle(2, clock)
    other = MeshManager(now_fn=clock, me="z")
    other.form("different-party")
    assert b.receive(other.emit("weather", {"state": 0.9}).to_wire()) is None


def test_my_own_echo_is_ignored():
    clock = Clock()
    (a, b), *_ = _circle(2, clock)
    pkt = a.emit("weather", {"state": 0.1})
    assert a.receive(pkt.to_wire()) is None      # I don't hear myself


# -- membership: fade + expiry -----------------------------------------------

def test_a_quiet_member_fades():
    clock = Clock()
    (a, b), *_ = _circle(2, clock)
    b.receive(a.emit("bearing", {"bearing_dd": 0, "dist": "close"}).to_wire())
    assert len(b.active()) == 1
    clock.t += QUIET_FADE_S + 1
    assert b.active() == []                       # faded from the circle
    assert len(b.members) == 1                    # remembered, just not fresh


def test_the_group_expires():
    clock = Clock()
    (a, b), *_ = _circle(2, clock)
    assert a.live()
    clock.t += GROUP_TTL_S + 1
    assert not a.live()
    assert a.emit("weather", {"state": 0.5}) is None   # dead group sends nothing


def test_leaving_is_unilateral():
    clock = Clock()
    (a, _b), *_ = _circle(2, clock)
    a.leave()
    assert not a.live() and a.emit("weather", {"state": 0.5}) is None


# -- the invariants: veil silences; names never cross ------------------------

def test_the_veil_silences_the_sender():
    clock = Clock()
    a = MeshManager(privacy=Veil(on=True), now_fn=clock)
    gid, code = a.form()
    assert a.emit("weather", {"state": 0.5}) is not None
    a._privacy.pause()
    assert a.emit("weather", {"state": 0.5}) is None


def test_names_never_cross_only_aliases_are_local():
    clock = Clock()
    (a, b), *_ = _circle(2, clock)
    b.receive(a.emit("bearing", {"bearing_dd": 0, "dist": "close"}).to_wire())
    # the wire carries no name — only the random member id
    wire = a.emit("bearing", {"bearing_dd": 0, "dist": "close"}).to_wire()
    assert "name" not in wire and "alias" not in wire
    assert set(wire["body"]) <= {"bearing_dd", "dist"}
    # the human name lives only on b's device
    b.alias(a.me, "Maya")
    assert b.name_of(a.me) == "Maya"


# -- The Beacon ---------------------------------------------------------------

def test_dist_band_and_bearing_word():
    assert dist_band(3) == "close" and dist_band(20) == "near" and dist_band(80) == "far"
    assert dist_band(None) == "far"
    assert _bearing_word(0) == "ahead" and _bearing_word(2700) == "left"


def test_beacon_points_at_the_group_nearest_first():
    clock = Clock()
    mgrs, gid, code = _circle(3, clock)
    me, x, y = mgrs
    beacon = Beacon(me, now_fn=clock)
    # x is far to the right (90°, 80m), y is close ahead-left (315°, 5m)
    me.receive(pos_wire(x, 90, 80, clock))
    me.receive(pos_wire(y, 315, 5, clock))
    contacts = beacon.contacts()
    assert [c.band for c in contacts] == ["close", "far"]   # nearest first
    frames = beacon.render_frames()
    assert frames and frames[0]["t"] == "beacon"
    assert frames[0]["side_dd"] == 3150 and frames[0]["band"] == "close"


def test_beacon_card_uses_local_alias_never_the_wire():
    clock = Clock()
    mgrs, gid, code = _circle(2, clock)
    me, friend = mgrs
    beacon = Beacon(me, now_fn=clock)
    me.receive(pos_wire(friend, 315, 5, clock))
    me.alias(friend.me, "Maya")
    card = beacon.card()
    assert card["type"] == "BeaconCard" and card["found"] == 1
    row = card["contacts"][0]
    assert row["who"] == "Maya" and row["where"] == "ahead-left" and row["band"] == "close"


def test_beacon_is_veil_gated():
    clock = Clock()
    a = MeshManager(privacy=Veil(on=True), now_fn=clock)
    a.form()
    beacon = Beacon(a, now_fn=clock)
    assert beacon.emit_position(90, 5) is not None
    a._privacy.pause()
    assert beacon.emit_position(90, 5) is None
