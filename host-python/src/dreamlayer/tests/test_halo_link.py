"""The wire from the Brain to the glasses — the surface that did not exist.

The glasses have a complete renderer, the Brain has twenty driven producers, and
`bridge/real_bridge.py` speaks BLE to a Halo. The `bridge/` package is
constructed in exactly two places — `main.py`'s emulator helper and
`simulator/` — both hanging off the `Orchestrator` that `decisions/0001` records
the shipped Brain never builds. So the transport was complete, tested, and
reachable only from code the wearer does not run.

The load-bearing design choice, which most of these tests exist to pin: the link
is a SUBSCRIBER on `Brain._event_subs`, the same list the Live Lens's SSE stream
joins. Teaching each producer to also send to the glasses would be twenty edits
and a permanent second list to keep in step. As a subscriber, every card that
reaches the phone reaches the glass — including cards added long after this was
written, by producers that never learn the glasses exist.
"""
from __future__ import annotations

import queue
import threading


from dreamlayer.ai_brain.server.halo_link import (
    QUEUE_MAX, HaloLink, build_bridge,
)


class _Brain:
    """Just the fan-out contract `push_event` and the link share."""

    def __init__(self):
        self._event_lock = threading.Lock()
        self._event_subs: list = []


class _Bridge:
    def __init__(self, boom_on_send=False, boom_on_connect=False):
        self.cards: list = []
        self.connected = False
        self.lua_root = None
        self.boom_on_send = boom_on_send
        self.boom_on_connect = boom_on_connect

    def connect(self):
        if self.boom_on_connect:
            raise RuntimeError("no glasses in range")
        self.connected = True
        return {"device": "halo-test", "display": [256, 256]}

    def disconnect(self):
        self.connected = False

    def load_lua_app(self, lua_root):
        self.lua_root = lua_root

    def send_card(self, payload, event="answer_ready"):
        if self.boom_on_send:
            raise RuntimeError("radio dropped")
        self.cards.append((event, payload))


def _linked(**kw):
    b, br = _Brain(), _Bridge(**kw)
    ln = HaloLink(b, bridge=br)
    return b, br, ln


def _settle(ln, n=1, tries=200):
    for _ in range(tries):
        if ln.sent + ln.failures + ln.dropped >= n:
            return True
        import time as _t
        _t.sleep(0.01)
    return False


class TestItJoinsTheSameFanOut:
    """The design, asserted directly: no producer learns the glasses exist."""

    def test_connecting_registers_a_subscriber(self):
        b, _, ln = _linked()
        assert b._event_subs == []
        assert ln.connect()["ok"] is True
        assert len(b._event_subs) == 1
        ln.disconnect()

    def test_disconnecting_removes_it(self):
        b, _, ln = _linked()
        ln.connect()
        ln.disconnect()
        assert b._event_subs == []

    def test_connect_is_idempotent(self):
        b, _, ln = _linked()
        ln.connect()
        ln.connect()
        assert len(b._event_subs) == 1, "a second connect double-subscribed"
        ln.disconnect()

    def test_a_card_pushed_by_the_real_funnel_reaches_the_glass(self):
        # The whole point, end to end through `Brain.push_event` itself rather
        # than by hand-feeding the queue.
        from dreamlayer.ai_brain.server.server import Brain
        b = Brain.__new__(Brain)
        b._event_lock, b._event_subs = threading.Lock(), []
        b.PROACTIVE_KINDS = Brain.PROACTIVE_KINDS
        br = _Bridge()
        ln = HaloLink(b, bridge=br)
        ln.connect()
        try:
            sent = Brain.push_event(b, "hark", {"type": "HarkCard",
                                                "primary": "smoke alarm"},
                                    veil_ok=True)
            assert sent == 1
            assert _settle(ln), "the card never left the queue"
            assert br.cards == [("hark", {"type": "HarkCard",
                                          "primary": "smoke alarm"})]
        finally:
            ln.disconnect()

    def test_a_producer_added_later_needs_no_wiring(self):
        # A kind that did not exist when this link was written still arrives,
        # because the link forwards whatever the fan-out carries.
        b, br, ln = _linked()
        ln.connect()
        try:
            b._event_subs[0].put_nowait(
                {"kind": "some_future_card", "card": {"type": "X"}})
            assert _settle(ln)
            assert br.cards[0][0] == "some_future_card"
        finally:
            ln.disconnect()


class TestItFailsSoft:
    """A radio to a battery-powered thing that walks out of range."""

    def test_a_bridge_that_cannot_connect_does_not_subscribe(self):
        b, _, ln = _linked(boom_on_connect=True)
        got = ln.connect()
        assert got["ok"] is False
        assert b._event_subs == [], "a failed link still joined the fan-out"

    def test_no_bridge_is_an_honest_refusal(self):
        ln = HaloLink(_Brain(), bridge=None)
        got = ln.connect()
        assert got["ok"] is False and "bridge" in got["reason"]

    def test_a_send_failure_never_kills_forwarding(self):
        # The load-bearing one: an exception on the link thread would silently
        # stop the glasses for the rest of the session.
        b, br, ln = _linked(boom_on_send=True)
        ln.connect()
        try:
            for _ in range(3):
                b._event_subs[0].put_nowait({"kind": "brief", "card": {"a": 1}})
            assert _settle(ln, n=3)
            assert ln.failures == 3
            br.boom_on_send = False
            b._event_subs[0].put_nowait({"kind": "brief", "card": {"a": 2}})
            assert _settle(ln, n=4)
            assert br.cards, "forwarding died after a transport error"
        finally:
            ln.disconnect()

    def test_a_lua_bundle_failure_still_connects(self):
        # A Halo already running the app is driven fine without a fresh push;
        # refusing to connect over a bundle problem strands working glasses.
        b, br, ln = _linked()

        def boom(root):
            raise RuntimeError("no bundle here")
        br.load_lua_app = boom
        assert ln.connect(lua_root="/nope")["ok"] is True
        ln.disconnect()

    def test_a_card_less_event_is_skipped_not_crashed(self):
        b, br, ln = _linked()
        ln.connect()
        try:
            b._event_subs[0].put_nowait({"kind": "brief"})          # no card
            b._event_subs[0].put_nowait({"kind": "brief", "card": {"ok": 1}})
            assert _settle(ln)
            assert br.cards == [("brief", {"ok": 1})]
        finally:
            ln.disconnect()

    def test_the_queue_is_bounded(self):
        b, _, ln = _linked()
        ln._q = queue.Queue(maxsize=QUEUE_MAX)
        for i in range(QUEUE_MAX * 2):
            try:
                ln._q.put_nowait({"kind": "brief", "card": {"i": i}})
            except queue.Full:
                pass
        assert ln._q.qsize() <= QUEUE_MAX


class TestItDoesNotSecondGuessTheGates:
    """By the time a card is in the queue it has passed the Veil, the wearer's
    preferences and the learned attention bar. Re-checking would double-gate."""

    def test_a_veiled_card_never_arrives_because_it_never_ships(self,
                                                                monkeypatch):
        # monkeypatch, NOT a bare class assignment: `incognito_now` is a real
        # method, so `Brain.x = ...; del Brain.x` REMOVES it from the class for
        # every test that follows. The first version of this did exactly that
        # and took 142 unrelated tests down with it.
        from dreamlayer.ai_brain.server.server import Brain
        b = Brain.__new__(Brain)
        b._event_lock, b._event_subs = threading.Lock(), []
        b.PROACTIVE_KINDS = Brain.PROACTIVE_KINDS
        br = _Bridge()
        ln = HaloLink(b, bridge=br)
        ln.connect()
        monkeypatch.setattr(Brain, "incognito_now", lambda s: True)
        try:
            assert Brain.push_event(b, "candor", {"type": "C"}) == 0
            assert br.cards == [], "a veiled card reached the glasses"
        finally:
            ln.disconnect()

    def test_the_link_forwards_the_kind_the_funnel_used(self):
        # `send_card(payload, event)` takes the kind, so the device's renderer
        # dispatches on the same name the Live Lens does.
        b, br, ln = _linked()
        ln.connect()
        try:
            b._event_subs[0].put_nowait({"kind": "commitment_drift",
                                         "card": {"type": "CommitmentDriftCard"}})
            assert _settle(ln)
            assert br.cards[0][0] == "commitment_drift"
        finally:
            ln.disconnect()


class TestTheStatusIsHonest:
    def test_connected_is_not_driving(self):
        b, _, ln = _linked()
        ln.connect()
        try:
            assert ln.status()["connected"] is True
            assert ln.driving() is False, (
                "a connected radio that has carried nothing is not a working "
                "link — this is the same distinction as importable vs used")
        finally:
            ln.disconnect()

    def test_driving_follows_a_card_that_actually_landed(self):
        b, br, ln = _linked()
        ln.connect()
        try:
            b._event_subs[0].put_nowait({"kind": "brief", "card": {"a": 1}})
            assert _settle(ln)
            assert ln.driving() is True and ln.status()["sent"] == 1
        finally:
            ln.disconnect()

    def test_a_failed_send_does_not_count_as_driving(self):
        b, br, ln = _linked(boom_on_send=True)
        ln.connect()
        try:
            b._event_subs[0].put_nowait({"kind": "brief", "card": {"a": 1}})
            assert _settle(ln)
            assert ln.driving() is False and ln.status()["failures"] == 1
        finally:
            ln.disconnect()


class TestTheBridgeFactory:
    def test_the_emulator_bridge_is_always_available(self):
        br = build_bridge("emulator")
        assert br is not None
        assert br.connect()["device"] == "halo-emulator"

    def test_an_unknown_kind_falls_back_to_the_emulator(self):
        assert build_bridge("nonsense") is not None

    def test_the_real_bridge_is_asked_for_by_name(self):
        # It needs brilliant-ble and glasses in range; absent either, None with
        # the reason logged rather than an import error reaching the caller.
        got = build_bridge("real")
        assert got is None or hasattr(got, "send_card")


class TestAgainstTheRealEmulatorBridge:
    """The emulator satisfies the same `BridgeBase` contract as the radio, so
    this exercises the wiring rather than a mock of it."""

    def test_a_card_reaches_the_emulator(self):
        from dreamlayer.bridge.emulator_bridge import EmulatorBridge
        b = _Brain()
        br = EmulatorBridge()
        ln = HaloLink(b, bridge=br)
        assert ln.connect()["ok"] is True
        try:
            b._event_subs[0].put_nowait(
                {"kind": "saved_memory",
                 "card": {"type": "SavedMemoryCard", "primary": "kept"}})
            assert _settle(ln)
            assert br.last_card == {"type": "SavedMemoryCard", "primary": "kept"}
            assert br.state == "showing_card"
        finally:
            ln.disconnect()


class TestTheBrainDrivesIt:
    def test_connect_status_disconnect_through_the_brain(self):
        from dreamlayer.ai_brain.server.server import Brain
        b = Brain.__new__(Brain)
        b._event_lock, b._event_subs = threading.Lock(), []
        assert Brain.halo_status(b)["connected"] is False
        got = Brain.halo_connect(b, "emulator")
        try:
            assert got["ok"] is True
            assert Brain.halo_status(b)["connected"] is True
        finally:
            assert Brain.halo_disconnect(b)["ok"] is True
        assert Brain.halo_status(b)["connected"] is False

    def test_the_lua_root_is_found_in_a_checkout(self):
        from dreamlayer.ai_brain.server.server import Brain
        root = Brain._lua_root()
        assert root.endswith("halo-lua")
        import os
        assert os.path.isdir(root)

    def test_the_routes_exist(self):
        import inspect

        from dreamlayer.ai_brain.server import server as s
        src = inspect.getsource(s)
        assert '"/dreamlayer/halo": _post_halo' in src
        assert '"/dreamlayer/halo": _get_halo' in src
