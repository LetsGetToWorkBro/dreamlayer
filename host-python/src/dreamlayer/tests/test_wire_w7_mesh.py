"""W7 — the off-grid mesh (Meshtastic), wired end to end.

The tincan bond is Bluetooth-range; a Meshtastic node carries it miles, off-grid.
The bridge (mesh_bridge.MeshBridge) shipped, but nothing on the orchestrator
attached a node, relayed an inbound text to the glass, or teed a tincan pulse
over LoRa. These tests pin that glue with an injectable fake node — no radio,
no wheel.

Posture check: the mesh only carries what the tincan surface already sends —
short pulse markers, never transcripts, memories, or positions — and inbound
text is Veil-gated before it ever reaches the glass.
"""
from __future__ import annotations

from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def _orc():
    from dreamlayer.orchestrator.orchestrator import Orchestrator
    return Orchestrator(FakeBridge())


def _cards(orc):
    return [c for c in orc.bridge.raw
            if isinstance(c, dict) and c.get("t") == "card"]


class FakeMesh:
    """A stand-in Meshtastic node: records what was sent, exposes the on_text
    callback the bridge registers, mirrors connect/close."""
    def __init__(self, ok=True):
        self.ok = ok
        self.sent = []
        self._on = None
        self.closed = False

    def connect(self):
        return self.ok

    def on_text(self, fn):
        self._on = fn

    def send(self, text):
        self.sent.append(text)
        return True

    def close(self):
        self.closed = True


def test_attach_mesh_connects_and_registers():
    o = _orc()
    mesh = FakeMesh()
    assert o.attach_mesh(mesh) is True
    assert o._mesh is mesh
    assert mesh._on is not None          # on_text wired to _on_mesh_text


def test_attach_mesh_false_when_node_wont_connect():
    o = _orc()
    assert o.attach_mesh(FakeMesh(ok=False)) is False
    assert o._mesh is None


def test_mesh_send_forwards_when_attached():
    o = _orc()
    o.attach_mesh(FakeMesh())
    assert o.mesh_send("hi") is True
    assert o._mesh.sent == ["hi"]


def test_mesh_send_false_without_node():
    o = _orc()
    assert o.mesh_send("hi") is False


def test_inbound_text_renders_a_card_veil_down():
    o = _orc()
    mesh = FakeMesh()
    o.attach_mesh(mesh)
    mesh._on("basecamp", "on my way")
    cards = _cards(o)
    assert len(cards) == 1
    primary = cards[0].get("primary", "").lower()
    assert "basecamp" in primary and "on my way" in primary


def test_inbound_text_suppressed_when_veiled():
    o = _orc()
    mesh = FakeMesh()
    o.attach_mesh(mesh)
    o.set_incognito(True)
    mesh._on("basecamp", "secret coordinates")
    assert _cards(o) == []


def test_mesh_tee_sends_a_nonverbal_pulse():
    o = _orc()
    o.attach_mesh(FakeMesh())
    o.mesh_tee([1, 2, 3])
    # a short dot-marker, never the content
    assert o._mesh.sent and set(o._mesh.sent[0]) <= {"·"}
    assert 1 <= len(o._mesh.sent[0]) <= 8


def test_mesh_tee_noop_without_node():
    o = _orc()
    o.mesh_tee([1, 2, 3])       # no node → silent no-op, must not raise


def test_mesh_tee_caps_pulse_length():
    o = _orc()
    o.attach_mesh(FakeMesh())
    o.mesh_tee(list(range(50)))
    assert len(o._mesh.sent[0]) <= 8


def test_detach_mesh_closes_node():
    o = _orc()
    mesh = FakeMesh()
    o.attach_mesh(mesh)
    o.detach_mesh()
    assert mesh.closed is True
    assert o._mesh is None


def test_tincan_sweep_tees_over_mesh(monkeypatch):
    o = _orc()
    o.attach_mesh(FakeMesh())

    class _Tincan:
        def compose(self, pattern):
            return {"pattern": pattern}
    o.tincan = _Tincan()
    # a finished tap pattern out of the collector
    monkeypatch.setattr(o.tap_collector, "tick", lambda: [1, 0, 1])
    o._tincan_sweep()
    assert o.confluence_outbox                    # BLE path still fired
    assert o._mesh.sent                           # AND the LoRa tee fired
