"""GhostMode, reachable at last — a circle of wearers through the Brain.

`confluence.mesh.MeshManager` was written whole: group keys, HMAC'd packets,
replay and stranger rejection, a quiet fade, a group TTL, a differentially-
private group summary. It was constructed NOWHERE.
`Orchestrator._init_confluence_plugins` sets `self.mesh = None` with the comment
"attached by the app layer when a circle is formed", and no app layer ever
formed one. `MeshEventBus` — the `event_bus` capability — wraps a MeshManager,
so it was unreachable for the same reason one layer out.

These cover the room that closes it, and they lean on the REAL primitives
throughout: a forged packet has to be rejected by the mesh's own HMAC, not by
anything this room re-implements.
"""
from __future__ import annotations

import tempfile

import pytest

from dreamlayer.ai_brain.server.live_circle import (
    CIRCLE_MAX, INBOX_MAX, ROOM_MAX, LiveCircle, room,
)
from dreamlayer.ai_brain.server.server import Brain


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def circle(brain, clock):
    return LiveCircle(brain, now_fn=clock)


def _formed(circle, a="a", b="b"):
    out = circle.form(a)
    assert circle.join(b, "", out["code"])["ok"] is True
    return out


class TestTheHandshake:
    def test_forming_gives_a_spoken_code(self, circle):
        out = circle.form("a")
        assert out["ok"] is True
        assert out["group"] and len(out["code"].split("-")) == 3

    def test_the_code_lets_someone_in(self, circle):
        out = _formed(circle)
        assert circle.join("c", out["group"], out["code"])["members"] == 3

    def test_a_wrong_code_is_refused(self, circle):
        circle.form("a")
        assert "error" in circle.join("b", "", "not-a-real-code")

    def test_wrong_codes_are_throttled(self, circle):
        circle.form("a")
        for _ in range(10):
            circle.join("b", "", "wrong-wrong-wrong")
        out = circle.join("b", "", "still-quite-wrong")
        assert "too many wrong codes" in out["error"]

    def test_an_ambiguous_code_bonds_nobody(self, circle, monkeypatch):
        # Two live circles minted the same words. Joining an arbitrary one is
        # how a stranger ends up inside your evening.
        from dreamlayer.confluence import mesh as mesh_mod
        monkeypatch.setattr(mesh_mod.secrets, "choice", lambda seq: seq[0])
        circle.form("a")
        circle.form("b")
        code = "-".join([mesh_mod._WORDS[0]] * 3)
        assert "ambiguous" in circle.join("c", "", code)["error"]

    def test_a_group_id_with_the_wrong_code_is_refused(self, circle):
        out = circle.form("a")
        assert "error" in circle.join("b", out["group"], "wrong-wrong-wrong")

    def test_leaving_is_unilateral(self, circle):
        out = _formed(circle)
        assert circle.leave("b")["ok"] is True
        assert circle.pulse("b")["in_circle"] is False
        assert circle.pulse("a")["in_circle"] is True   # the circle stands
        assert out["group"]

    def test_leaving_something_you_are_not_in_is_fine(self, circle):
        assert circle.leave("nobody")["ok"] is True

    def test_a_circle_is_capped(self, circle):
        out = circle.form("a")
        for i in range(CIRCLE_MAX + 2):
            circle.join(f"m{i}", out["group"], out["code"])
        assert "full" in circle.join("late", out["group"], out["code"])["error"]

    def test_the_room_is_capped(self, circle):
        for i in range(ROOM_MAX):
            circle.form(f"s{i}")
        assert "room is full" in circle.form("one-more")["error"]

    def test_a_session_needs_an_id(self, circle):
        assert "error" in circle.form("")
        assert "error" in circle.join("", "", "a-b-c")

    def test_reforming_leaves_the_old_circle(self, circle):
        first = _formed(circle)
        circle.form("a")                       # a mints a fresh circle
        assert circle.pulse("b")["group"] == first["group"]
        assert circle.pulse("a")["group"] != first["group"]


class TestTheTraffic:
    def test_a_pulse_reaches_the_others(self, circle):
        _formed(circle)
        circle.pulse("a", "weather", {"state": 0.8})
        out = circle.pulse("b", "weather", {"state": -0.2})
        assert out["heard"] == 1
        assert [m["body"]["state"] for m in out["members"]] == [0.8]

    def test_you_never_hear_yourself(self, circle):
        _formed(circle)
        circle.pulse("a", "weather", {"state": 0.8})
        assert circle.pulse("a")["members"] == []

    def test_everyone_in_the_circle_hears_it(self, circle):
        out = circle.form("a")
        circle.join("b", "", out["code"])
        circle.join("c", "", out["code"])
        circle.pulse("a", "weather", {"state": 0.5})
        heard = {who: [m["body"].get("state")
                       for m in circle.pulse(who)["members"]]
                 for who in ("b", "c")}
        assert 0.5 in heard["b"] and 0.5 in heard["c"]

    def test_a_forged_packet_is_dropped_by_the_mesh(self, circle):
        _formed(circle)
        s = circle._sessions["b"]
        wire = {"group_id": s["group"], "sender": "stranger", "seq": 1,
                "kind": "weather", "body": {"state": 0.9}, "mac": "0" * 64}
        s["inbox"].append(wire)
        out = circle.pulse("b")
        assert out["heard"] == 0 and out["members"] == []

    def test_a_replayed_packet_is_dropped(self, circle):
        _formed(circle)
        circle.pulse("a", "weather", {"state": 0.8})
        wire = list(circle._sessions["b"]["inbox"])
        assert circle.pulse("b")["heard"] == 1  # drained once, legitimately
        circle._sessions["b"]["inbox"].extend(wire)
        assert circle.pulse("b")["heard"] == 0  # …and never a second time

    def test_heard_counts_this_beat_not_the_session(self, circle):
        # A caller asking "did anyone answer me just now" is asking about this
        # beat; a running total answers a question nobody asked.
        _formed(circle)
        circle.pulse("a", "weather", {"state": 0.8})
        assert circle.pulse("b")["heard"] == 1
        assert circle.pulse("b")["heard"] == 0

    def test_a_stranger_circles_packet_is_dropped(self, circle):
        # Two circles on the same Brain must not bleed into each other.
        one = circle.form("a")
        circle.join("b", "", one["code"])
        circle.form("x")
        circle.pulse("a", "weather", {"state": 0.8})
        wire = circle._sessions["b"]["inbox"][0]
        circle._sessions["x"]["inbox"].append(wire)
        assert circle.pulse("x")["heard"] == 0

    def test_an_inbox_is_bounded(self, circle):
        _formed(circle)
        for i in range(INBOX_MAX * 2):
            circle.pulse("a", "weather", {"state": i / 100.0})
        assert len(circle._sessions["b"]["inbox"]) == INBOX_MAX

    def test_a_quiet_member_fades(self, circle, clock):
        _formed(circle)
        circle.pulse("a", "weather", {"state": 0.8})
        assert circle.pulse("b")["members"]
        clock.t += 30.0
        assert circle.pulse("b")["members"] == []

    def test_a_silent_session_is_dropped_from_the_room(self, circle, clock):
        _formed(circle)
        clock.t += 120.0
        assert circle.pulse("b")["in_circle"] is False

    def test_pulsing_outside_a_circle_is_not_an_error(self, circle):
        assert circle.pulse("nobody") == {"in_circle": False, "members": [],
                                          "heard": 0}


class TestTheSharedView:
    def test_the_circle_gets_a_noisy_summary(self, circle):
        _formed(circle)
        circle.pulse("a", "weather", {"state": 0.8})
        out = circle.pulse("b", "weather", {"state": -0.9})
        assert set(out["shared"]) == {"members", "bands", "epsilon_remaining"}
        assert set(out["shared"]["bands"]) == {"storm", "grey", "clear"}

    def test_the_budget_runs_out_and_the_summary_stops(self, circle):
        # An exact aggregate over three people tells everyone your value the
        # moment it moves; a budget that never ran out would let repeated peeks
        # average the noise away.
        _formed(circle)
        seen = [("shared" in circle.pulse("a", "weather", {"state": 0.1}))
                for _ in range(30)]
        assert seen[0] is True and seen[-1] is False


class TestTheVeil:
    """The Veil silences the sender completely — the mesh's own rule, enforced
    by the mesh, and this room must not route around it."""

    def test_a_veiled_member_sends_nothing(self, circle, brain):
        _formed(circle)
        brain.config.network_mode = "lan_only"
        out = circle.pulse("a", "weather", {"state": 0.8})
        assert out["sent"] is False
        assert circle._sessions["b"]["inbox"] == []

    def test_a_veiled_member_is_quiet_not_deaf(self, circle, brain):
        # Being silent is not the same as being cut off: `a` speaks while `b`
        # is veiled, and `b` still hears the circle.
        _formed(circle)
        circle.pulse("a", "weather", {"state": 0.8})
        brain.config.network_mode = "lan_only"
        out = circle.pulse("b")
        assert out["sent"] is False and out["heard"] == 1

    def test_an_unreadable_posture_sends_nothing(self, circle, brain,
                                                 monkeypatch):
        _formed(circle)
        monkeypatch.setattr(type(brain), "incognito_now",
                            lambda self: (_ for _ in ()).throw(RuntimeError()))
        assert circle.pulse("a", "weather", {"state": 0.8})["sent"] is False


class TestNamesNeverCross:
    def test_an_alias_is_local_only(self, circle):
        _formed(circle)
        circle.pulse("a", "weather", {"state": 0.8})
        out = circle.pulse("b")
        member = out["members"][0]["member"]
        assert circle.alias("b", member, "Maya")["ok"] is True
        assert circle.pulse("b")["members"][0]["name"] == "Maya"
        # …and nobody else's view of the same member carries it.
        circle.pulse("b", "weather", {"state": 0.1})
        assert all(m["name"] == "" for m in circle.pulse("a")["members"])

    def test_aliasing_outside_a_circle_is_refused(self, circle):
        assert circle.alias("nobody", "x", "Maya")["ok"] is False


class TestTheEventBus:
    """`event_bus` (`MeshEventBus`) is what the room speaks through, not a
    wrapper beside it — that is the difference between the capability being
    wired and being present."""

    def test_every_packet_goes_through_the_bus(self, circle):
        _formed(circle)
        seen = []
        circle._sessions["a"]["bus"].on("emit", seen.append)
        circle.pulse("a", "weather", {"state": 0.8})
        assert len(seen) == 1 and seen[0].kind == "weather"

    def test_a_veiled_emit_publishes_nothing(self, circle, brain):
        # The bus never fabricates a packet: a veiled emit returns None and
        # subscribers see nothing, which is what keeps the privacy contract
        # true for a listener that never reads the mesh directly.
        _formed(circle)
        seen = []
        circle._sessions["a"]["bus"].on("emit", seen.append)
        brain.config.network_mode = "lan_only"
        circle.pulse("a", "weather", {"state": 0.8})
        assert seen == []

    def test_a_rejected_packet_publishes_nothing(self, circle):
        _formed(circle)
        seen = []
        circle._sessions["b"]["bus"].on("receive", seen.append)
        circle._sessions["b"]["inbox"].append(
            {"group_id": "nope", "sender": "x", "seq": 1, "kind": "weather",
             "body": {}, "mac": "0" * 64})
        circle.pulse("b")
        assert seen == []

    def test_a_bad_listener_does_not_break_the_beat(self, circle):
        _formed(circle)

        def boom(_pkt):
            raise RuntimeError("subscriber blew up")
        circle._sessions["a"]["bus"].on("emit", boom)
        assert circle.pulse("a", "weather", {"state": 0.8})["sent"] is True


class TestTheRoute:
    def test_the_room_is_cached_on_the_brain(self, brain):
        assert room(brain) is room(brain)

    def test_the_routes_are_registered(self, brain):
        import inspect

        from dreamlayer.ai_brain.server import server as server_mod
        src = inspect.getsource(server_mod)
        for path in ("/dreamlayer/live/circle/form",
                     "/dreamlayer/live/circle/join",
                     "/dreamlayer/live/circle/leave",
                     "/dreamlayer/live/circle/alias",
                     "/dreamlayer/live/circle/pulse"):
            assert f'"{path}"' in src

    def test_two_phones_can_share_a_sky_through_the_routes(self, brain):
        # The whole chain a wearer touches: form → say the code → join → beat.
        r = room(brain)
        out = r.form("phone-a")
        assert r.join("phone-b", "", out["code"])["ok"] is True
        r.pulse("phone-a", "weather", {"state": 0.7})
        got = r.pulse("phone-b", "weather", {"state": -0.4})
        assert got["in_circle"] and got["heard"] == 1


class TestTheCapabilityIsProven:
    """`event_bus` is promoted from proof, like every other runtime-promoted
    capability: pyee importing is not a bus, and a bus around a manager that
    never joined a circle is the dormant state this file exists to end."""

    def test_an_empty_room_proves_nothing(self, circle):
        assert circle.members_live() == 0

    def test_a_formed_circle_is_the_proof(self, circle):
        _formed(circle)
        assert circle.members_live() == 2

    def test_leaving_takes_it_back_down(self, circle):
        _formed(circle)
        circle.leave("a")
        circle.leave("b")
        assert circle.members_live() == 0

    def test_an_expired_group_is_not_live(self, circle, clock):
        from dreamlayer.confluence.mesh import GROUP_TTL_S
        _formed(circle)
        clock.t += GROUP_TTL_S + 1.0
        assert circle.members_live() == 0
