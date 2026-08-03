"""test_mesh_live.py — a few words, carried miles by radio.

`orchestrator/mesh_bridge.py` was a complete Meshtastic adapter with two real
bugs already found and fixed inside it, and no caller anywhere: its only
intended consumer was the `Orchestrator` the shipped Brain never builds
(`decisions/0001`).

Most of what is asserted here is about what may cross an open radio and what may
not. LoRa is a broadcast transport and whoever is on the other end is
UNAUTHENTICATED — a Meshtastic node ID is not an identity — so the inbound rule
(a card, and nothing else, ever) matters more than the happy path.
"""
from __future__ import annotations

import tempfile

import pytest

from dreamlayer.ai_brain.server.mesh_live import (
    MAX_CARD_CHARS, MAX_CHARS, MeshLink, link)
from dreamlayer.ai_brain.server.server import Brain


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


def _pushes(brain):
    seen = []
    brain.push_event = lambda kind, card=None, veil_ok=False: (
        seen.append((kind, card, veil_ok)) or 1)
    return seen


class _Radio:
    """Stands in for `MeshBridge`, and keeps the listener so a test can deliver
    an inbound line the way the pubsub bus would."""

    def __init__(self, ready=True, refuses=False, boom=False):
        self.ready = ready
        self.refuses = refuses
        self.boom = boom
        self.out: list = []
        self.listeners: list = []

    def connect(self):
        return self.ready

    def send(self, text, channel=0):
        if self.boom:
            raise RuntimeError("serial port vanished")
        if self.refuses:
            return False
        self.out.append(text)
        return True

    def on_text(self, fn):
        self.listeners.append(fn)

    def close(self):
        self.ready = False


class TestWhatMayLeaveOverTheAir:
    def test_a_typed_line_goes_out(self, brain):
        r = _Radio()
        assert MeshLink(brain, bridge=r).send("heading back now")["ok"] is True
        assert r.out == ["heading back now"]

    def test_the_veil_stops_the_transmitter_not_just_the_store(self, brain,
                                                              monkeypatch):
        """A stronger reading of incognito than "records nothing", and the right
        one for a radio: the wearer is saying the Brain is not acting on their
        behalf, and putting their words on an open channel is about the loudest
        way this product can act on it."""
        r = _Radio()
        monkeypatch.setattr(type(brain), "incognito_now", lambda self: True)
        out = MeshLink(brain, bridge=r).send("heading back now")
        assert out == {"ok": False, "reason": "veiled"}
        assert r.out == []

    def test_an_unreadable_posture_is_treated_as_veiled(self, brain,
                                                        monkeypatch):
        def _boom(self):
            raise RuntimeError("trust store unreadable")
        monkeypatch.setattr(type(brain), "incognito_now", _boom)
        r = _Radio()
        assert MeshLink(brain, bridge=r).send("hello")["reason"] == "veiled"
        assert r.out == []

    def test_a_long_line_is_refused_rather_than_silently_cut(self, brain):
        """The radio truncates at 230 BYTES itself and does it correctly; this
        is the earlier, kinder limit so the wearer is TOLD instead of losing the
        end of their sentence to a transport detail."""
        r = _Radio()
        out = MeshLink(brain, bridge=r).send("x" * (MAX_CHARS + 1))
        assert out["ok"] is False and out["reason"] == "too-long"
        assert r.out == []

    @pytest.mark.parametrize("text", ["", "   ", None])
    def test_nothing_is_sent_for_nothing(self, brain, text):
        r = _Radio()
        assert MeshLink(brain, bridge=r).send(text)["ok"] is False
        assert r.out == []

    def test_the_only_way_to_the_radio_is_the_send_route(self):
        """"Outbound is only ever a line the wearer typed" has to be a property
        of the WIRING, not a convention — otherwise a future caller reaches
        `MeshLink.send` with a transcript and every rule above is bypassed."""
        import pathlib

        import dreamlayer
        root = pathlib.Path(dreamlayer.__file__).parent
        callers = []
        for p in root.rglob("*.py"):
            if "tests" in p.parts or p.name == "mesh_live.py":
                continue
            src = p.read_text(encoding="utf-8", errors="ignore")
            if "link(brain).send(" in src or "link(self).send(" in src:
                callers.append(p.name)
        assert callers == ["server.py"], (
            f"something other than the send route reaches the radio: {callers}")


class TestWhatArrivesOverTheAirStaysACard:
    """The single most tempting wrong line in the module. Whoever sent this is
    unauthenticated, so anything that let it reach the memory store would let a
    stranger in range write the wearer's history."""

    def _deliver(self, brain, radio, text, sender="!a1b2c3"):
        m = MeshLink(brain, bridge=radio)
        m.bridge()                                    # wires the listener
        radio.listeners[0](sender, text)
        return m

    def test_an_inbound_line_becomes_a_card(self, brain):
        seen = _pushes(brain)
        m = self._deliver(brain, _Radio(), "at the ridge, all fine")
        assert m.received == 1
        assert seen and seen[0][0] == "mesh"
        assert "ridge" in str(seen[0][1])

    def test_it_never_reaches_memory(self, brain):
        _pushes(brain)
        wrote = []
        brain.lenses().observe = lambda *a, **k: wrote.append(a) or True
        brain.lenses().ingest_utterance = lambda *a, **k: wrote.append(a)
        self._deliver(brain, _Radio(), "remember that Ana owes me twenty")
        assert wrote == [], (
            "a line off an open radio was written into the wearer's memory")

    def test_a_flooding_peer_cannot_fill_the_glass_with_one_card(self, brain):
        seen = _pushes(brain)
        self._deliver(brain, _Radio(), "y" * 4000)
        body = str(seen[0][1])
        assert "y" * (MAX_CARD_CHARS + 1) not in body

    def test_an_empty_line_draws_nothing(self, brain):
        seen = _pushes(brain)
        m = self._deliver(brain, _Radio(), "   ")
        assert seen == [] and m.received == 0

    def test_the_node_id_never_reaches_the_glass_as_anything(self, brain):
        """Looking a radio ID up against contacts would put a name on the glass
        that the transport cannot support; showing the raw ID would be four
        bytes of hex where a card has room for the message. Asserted against
        the CARD rather than by grepping the source — a word-scan over a file
        matches its own comments, which is how the first version of this test
        failed."""
        seen = _pushes(brain)
        self._deliver(brain, _Radio(), "on my way", sender="!deadbeef")
        body = str(seen[0][1])
        assert "on my way" in body
        assert "deadbeef" not in body

    def test_no_contact_lookup_happens_on_an_inbound_line(self, brain):
        seen = _pushes(brain)
        asked = []
        for name in ("voice_recall", "social_graph", "people"):
            if hasattr(brain, name):
                setattr(brain, name,
                        lambda *a, _n=name, **k: asked.append(_n) or None)
        self._deliver(brain, _Radio(), "on my way", sender="!deadbeef")
        assert asked == [], f"an unauthenticated node ID was looked up: {asked}"
        assert seen

    def test_a_push_that_raises_does_not_kill_the_receive_bus(self, brain):
        """This runs on meshtastic's pubsub thread, where an exception takes
        the bus down for the rest of the session."""
        def _boom(kind, card=None, veil_ok=False):
            raise RuntimeError("bridge closed")
        brain.push_event = _boom
        r = _Radio()
        m = self._deliver(brain, r, "hello")
        r.listeners[0]("!a1b2c3", "still listening")   # must not raise
        assert m.received == 2


class TestTheRadioItself:
    def test_no_node_is_a_reason_not_a_crash(self, brain):
        m = MeshLink(brain, bridge=_Radio(ready=False))
        assert m.send("hello") == {"ok": False, "reason": "no-node"}

    def test_a_radio_that_refuses_says_so(self, brain):
        m = MeshLink(brain, bridge=_Radio(refuses=True))
        out = m.send("hello")
        assert out["ok"] is False and out["reason"] == "radio-refused"
        assert m.sent == 0

    def test_a_radio_that_raises_is_absorbed(self, brain):
        m = MeshLink(brain, bridge=_Radio(boom=True))
        assert m.send("hello")["reason"] == "radio-error"

    def test_the_listener_is_wired_once(self, brain):
        r = _Radio()
        m = MeshLink(brain, bridge=r)
        m.bridge()
        m.bridge()
        assert len(r.listeners) == 1, "a second listener would double every card"

    def test_a_brain_with_no_meshtastic_is_not_a_fault(self, brain,
                                                       monkeypatch):
        import dreamlayer.orchestrator.mesh_bridge as mb
        monkeypatch.setattr(mb, "default_mesh", lambda host=None: None)
        m = MeshLink(brain)
        assert m.bridge() is None
        assert m.ready() is False
        assert m.send("hello")["reason"] == "no-node"

    def test_the_lan_host_reaches_the_bridge(self, brain, monkeypatch):
        """A node that lives elsewhere on the network rather than on this Mac's
        USB — a config field, because the bundled .app has no environment."""
        import dreamlayer.orchestrator.mesh_bridge as mb
        got = {}
        monkeypatch.setattr(mb, "default_mesh",
                            lambda host=None: got.setdefault("host", host)
                            and None or _Radio())
        brain.config.mesh_tcp_host = "192.168.1.30"
        MeshLink(brain).bridge()
        assert got["host"] == "192.168.1.30"

    def test_close_lets_it_be_reopened(self, brain):
        m = MeshLink(brain, bridge=_Radio())
        assert m.ready() is True
        m.close()
        assert m._bridge is None


class TestThePromotionFollowsALineThatCrossed:
    def _env(self, brain, monkeypatch) -> dict:
        import dreamlayer.capabilities as caps
        seen = {}
        real = caps.report

        def _spy(env=None, **kw):
            seen.update(env or {})
            return real(env=env, **kw)
        monkeypatch.setattr(caps, "report", _spy)
        from dreamlayer.ai_brain.server.server import _capability_payload
        _capability_payload(brain)
        return seen

    def test_an_open_node_that_carried_nothing_is_not_live(self, brain,
                                                           monkeypatch):
        """A radio with no peer in range connects perfectly and carries
        nothing, which is the normal state of a mesh and not a working link."""
        monkeypatch.delenv("DL_WIRED_MESH_RANGE", raising=False)
        brain._mesh_link = MeshLink(brain, bridge=_Radio())
        assert brain._mesh_link.ready() is True
        assert brain._mesh_link.driving() is False
        assert "DL_WIRED_MESH_RANGE" not in self._env(brain, monkeypatch)

    def test_a_sent_line_promotes_it(self, brain, monkeypatch):
        monkeypatch.delenv("DL_WIRED_MESH_RANGE", raising=False)
        brain._mesh_link = MeshLink(brain, bridge=_Radio())
        brain._mesh_link.send("heading back")
        assert self._env(brain, monkeypatch)["DL_WIRED_MESH_RANGE"] == "1"

    def test_a_received_line_promotes_it_too(self, brain, monkeypatch):
        monkeypatch.delenv("DL_WIRED_MESH_RANGE", raising=False)
        _pushes(brain)
        r = _Radio()
        brain._mesh_link = MeshLink(brain, bridge=r)
        brain._mesh_link.bridge()
        r.listeners[0]("!a1", "on my way")
        assert self._env(brain, monkeypatch)["DL_WIRED_MESH_RANGE"] == "1"

    def test_a_refused_send_does_not_promote(self, brain, monkeypatch):
        monkeypatch.delenv("DL_WIRED_MESH_RANGE", raising=False)
        brain._mesh_link = MeshLink(brain, bridge=_Radio(refuses=True))
        brain._mesh_link.send("hello")
        assert "DL_WIRED_MESH_RANGE" not in self._env(brain, monkeypatch)

    def test_the_report_does_not_open_a_radio_to_ask(self, brain, monkeypatch):
        monkeypatch.delenv("DL_WIRED_MESH_RANGE", raising=False)
        assert "DL_WIRED_MESH_RANGE" not in self._env(brain, monkeypatch)
        assert getattr(brain, "_mesh_link", None) is None

    def test_the_link_is_built_once_and_held(self, brain):
        assert link(brain) is link(brain)
