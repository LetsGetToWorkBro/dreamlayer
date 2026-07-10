"""test_physical_events.py — the $6 ESP32 physical-events path (INNOVATION 1.6).

A sensor out in the world POSTs a named signal to the Brain; the Brain forwards
it to the figment on stage as a scene event ("ble:3", "mail"). Covers the
transport envelope, the deployer's id-less push_event, the Brain's refusal when
nothing is armed, and — under lupa — the whole loop landing on the device:
main.lua routes the `event` envelope into the running figment's grammar and the
scene advances.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dreamlayer.reality_compiler.v2 import (
    Figment, Scene, TextLine, Transition, END,
    Vault, StageDeployer, transport,
)


# -- transport + deployer ------------------------------------------------------

def test_event_envelope_shape_and_frame_roundtrip():
    env = transport.event_envelope("ble:3")
    assert env == {"t": "event", "name": "ble:3"}
    raw = transport.frame(env)
    assert transport.parse_frame(raw) == env


def test_event_name_is_clamped():
    env = transport.event_envelope("x" * 100)
    assert len(env["name"]) == 32


def test_event_type_is_in_the_lua_lockstep_table():
    lua = (Path(__file__).resolve().parents[4]
           / "halo-lua" / "ble" / "message_types.lua").read_text()
    assert f'"{transport.EVENT}"' in lua        # message_types.lua EVENT = "event"


def test_push_event_carries_no_id_and_sends_one_frame(tmp_path):
    sent: list = []
    class Bridge:
        def send(self, raw): sent.append(raw)
    dep = StageDeployer(Vault(tmp_path / "v"), bridge=Bridge())
    rec = dep.push_event("ble:3")
    assert rec.success and rec.action == "event"
    assert [e for e in rec.envelopes] == [{"t": "event", "name": "ble:3"}]
    assert len(sent) == 1                        # exactly one frame on the wire
    assert transport.parse_frame(sent[0])["name"] == "ble:3"


# -- the device end: main.lua routes an event into the running figment ---------

lupa = pytest.importorskip("lupa")
from dreamlayer.tests.test_main_boot import Device  # noqa: E402  (reuse the boot harness)


def _mail_figment() -> Figment:
    """A figment that waits, then shows MAIL when it hears ble:3 — the mailbox
    reed switch closing."""
    f = Figment(name="Mailbox", initial="wait")
    f.add_scene(Scene(id="wait", duration_sec=600.0,
                      lines=[TextLine("WAIT", row=1)],
                      on={"ble:3": Transition(target="mail")}))
    f.add_scene(Scene(id="mail", duration_sec=5.0,
                      lines=[TextLine("MAIL", row=1)],
                      on_timeout=[Transition(target=END)]))
    return f


class TestEventReachesTheFigment:
    def test_ble_event_advances_the_running_figment(self):
        dev = Device()
        fig = _mail_figment()
        dev.send(transport.put_envelope(fig))
        dev.send(transport.swap_envelope(fig.id))
        dev.ticks(3)
        assert dev.display() == ["WAIT"]

        # the sensor fires: host → device `event {name:"ble:3"}`
        dev.send(transport.event_envelope("ble:3"))
        dev.ticks(2)
        assert dev.display() == ["MAIL"]         # the scene the grammar named

    def test_event_for_an_unlistened_name_is_a_noop(self):
        dev = Device()
        fig = _mail_figment()
        dev.send(transport.put_envelope(fig))
        dev.send(transport.swap_envelope(fig.id))
        dev.ticks(3)
        dev.send(transport.event_envelope("ble:9"))   # no scene lists ble:9
        dev.ticks(2)
        assert dev.display() == ["WAIT"]         # nothing moved


# -- the Brain's host route method --------------------------------------------

class TestBrainRcEvent:
    def _brain(self, tmp_path):
        from dreamlayer.ai_brain.server import Brain
        return Brain(tmp_path)

    def test_refuses_when_no_figment_is_armed(self, tmp_path):
        brain = self._brain(tmp_path)
        out = brain.rc_event("ble:3")
        assert out["ok"] is False and "no figment" in out["error"]

    def test_refuses_an_empty_name(self, tmp_path):
        brain = self._brain(tmp_path)
        assert brain.rc_event("")["ok"] is False

    def test_forwards_to_the_stage_when_armed(self, tmp_path):
        brain = self._brain(tmp_path)
        # a native interval puts a figment on stage (dry-run: no bridge)
        brain.rc_native("timer", {"seconds": 60, "label": "T"})
        assert brain._rc_active is not None
        out = brain.rc_event("ble:3")
        assert out["ok"] is True and out["name"] == "ble:3"
        # the event left as an id-less `event` envelope
        assert brain.rc.deployer.sent[-1] == {"t": "event", "name": "ble:3"}
