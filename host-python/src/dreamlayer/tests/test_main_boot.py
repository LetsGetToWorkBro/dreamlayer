"""Boot halo-lua/main.lua end-to-end and drive both feature stacks.

The card-queue and HostComm wiring bugs fixed alongside this test lived
undetected because every Lua test exercised modules in isolation — nothing
ever ran main.lua's actual tick loop. This suite boots the real entry
point with a stubbed `halo` device API and pushes real framed envelopes
through the real protocol reassembler, covering:

  - Reality Compiler v2: figment put/swap/run/ack/revoke over BLE
  - Halo Cinema / Dream Mode: dream_enter, v2 SynesthesiaCard, dream_exit
  - Memory Mode: card_type-keyed cards flow through the queue
"""
import json
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

from dreamlayer.reality_compiler.v2 import (   # noqa: E402
    RealityCompilerV2, transport,
)

HALO_LUA = Path(__file__).resolve().parents[4] / "halo-lua"

DEVICE_STUB = '''
_G.__rx_queue, _G.__tx, _G.__drawn = {}, {}, {}
_G.halo = {
  bluetooth = {
    receive = function() return table.remove(_G.__rx_queue, 1) end,
    send = function(data) _G.__tx[#_G.__tx+1] = data end,
  },
  display = {
    text  = function(s, x, y, o) _G.__drawn[#_G.__drawn+1] = {s=s, y=y} end,
    clear = function() _G.__drawn = {} end,
    show  = function() _G.__shown = #_G.__drawn end,
  },
  battery_level = function() return 88 end,
}
'''


class Device:
    """main.lua booted against the stub, driven from Python."""

    def __init__(self):
        rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        rt.execute(f'package.path = "{HALO_LUA}/?.lua;{HALO_LUA}/app/?.lua;"'
                   ' .. package.path')
        rt.execute(DEVICE_STUB)
        self.rt = rt
        self.main = self.req("main")
        self.tick = rt.eval("_G._dreamlayer_tick")
        self._push = rt.eval(
            "function(b) _G.__rx_queue[#_G.__rx_queue+1] = b end")

    def req(self, name):
        r = self.rt.eval(f'require("{name}")')
        return r[0] if isinstance(r, tuple) else r

    def send(self, envelope: dict):
        """Deliver a host envelope through the real 4-byte framing."""
        self._push(transport.frame(envelope).decode("latin1"))

    def ticks(self, n: int):
        for _ in range(n):
            self.tick()

    def display(self) -> list[str]:
        drawn = self.rt.eval("_G.__drawn")
        return [drawn[i + 1]["s"] for i in range(len(drawn))]

    def tx_frames(self) -> list[dict]:
        tx = self.rt.eval("_G.__tx")
        out = []
        for i in range(len(tx)):
            raw = tx[i + 1].encode("latin1")
            out.append(json.loads(raw[4:].decode("utf-8")))
        return out


@pytest.fixture
def dev():
    return Device()


def rolls_figment():
    rc = RealityCompilerV2()
    s = rc.rehearse("Rolling rounds")
    s.double_tap()
    s.say("rolling - three minutes")
    s.say("last ten seconds, pulse")
    s.say("then it starts again")
    return s.finish().figment


class TestBoot:
    def test_boot_exposes_tick(self, dev):
        assert dev.tick is not None

    def test_cinema_cards_in_priority_table(self, dev):
        cp = dev.main["CARD_PRIORITY"]
        for card in ("SynesthesiaCard", "PaletteShiftCard", "WorldAnchorCard"):
            assert cp[card] is not None


class TestFigmentOverBle:
    def test_put_swap_run_ack_revoke(self, dev):
        fig = rolls_figment()
        dev.send(transport.put_envelope(fig))
        dev.send(transport.swap_envelope(fig.id))
        dev.ticks(3)

        stage = dev.req("app.figment_stage")
        assert stage["active_id"]() == fig.id

        # acks left the device through the bound BLE channel
        acks = [f for f in dev.tx_frames() if f["t"] == "figment_ack"]
        assert len(acks) == 2 and all(a["ok"] for a in acks)

        # physical double-tap (echoed by host) starts the round
        dev.send({"t": "button", "ev": "double"})
        dev.ticks(101)                       # trigger + ~5 s at 20 fps
        assert dev.display() == ["ROLLING", "2:55"]

        dev.send(transport.revoke_envelope(fig.id))
        dev.ticks(1)
        assert not stage["is_running"]()


class TestCinemaOverBle:
    def test_dream_mode_and_synesthesia_v2(self, dev):
        hc = dev.req("ble.host_comm")
        dev.send({"t": "dream_enter"})
        dev.ticks(1)
        assert bool(hc["dream_active"]())

        dev.send({"t": "card", "card_type": "SynesthesiaCard", "version": 2,
                  "phrase": "rain on glass",
                  "payload": {"phrase": "rain on glass"}})
        dev.ticks(3)                         # renders via dream pipeline

        dev.send({"t": "dream_exit"})
        dev.ticks(1)
        assert not hc["dream_active"]()


class TestMemoryModeCards:
    def test_card_type_keyed_cards_flow(self, dev):
        # hosts send card_type; the queue asserts on .type — main.lua
        # normalizes (the bug this file exists to keep dead)
        dev.send({"t": "command", "cmd": "show_ready"})
        dev.ticks(2)
        dev.send({"t": "card", "card_type": "ObjectRecallCard",
                  "object": "Keys"})
        dev.ticks(2)                         # no assert = queue accepted both

    def test_full_session_interleaves(self, dev):
        """Figment → dream → memory cards in one boot, no residue."""
        fig = rolls_figment()
        dev.send(transport.put_envelope(fig))
        dev.send(transport.swap_envelope(fig.id))
        dev.ticks(3)
        dev.send(transport.revoke_envelope(fig.id))
        dev.ticks(1)
        dev.send({"t": "dream_enter"})
        dev.ticks(1)
        dev.send({"t": "dream_exit"})
        dev.ticks(1)
        dev.send({"t": "card", "card_type": "ObjectRecallCard",
                  "object": "Keys"})
        dev.ticks(2)
        stage = dev.req("app.figment_stage")
        assert not stage["is_running"]()
