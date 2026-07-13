"""P0-4: Halo features must work through the *live* main.lua registration.

The Timbre and TinCan visualizers shipped dead: main.lua registered their BLE
handlers without passing the tick clock, so on_timbre/on_tincan computed
until_ms = 0 + TTL and every frame expired on the first draw after ~2.5s of
uptime. The feature tests passed only because they called the renderer
directly (dr.timbre(0)). This drives the real boot and advances the clock past
the TTL first, the way the bug actually bit.
"""
from __future__ import annotations

import pytest

lupa = pytest.importorskip("lupa")

from dreamlayer.tests.test_glass_safety import Device   # boots real main.lua


def _points():
    return list(range(1, 13))            # 12 timbre points


class TestTimbreLifetime:
    def test_timbre_lifetime_is_measured_from_now_not_boot(self):
        d = Device()
        d.ticks(60)                       # 3000 ms uptime, past the 2500 ms TTL
        d.send({"t": "timbre", "known": 1, "side_dd": 0, "points": _points()})
        d.ticks(1)                        # process through the live registration
        dr = d.req("display.dream_renderer")
        # alive now (fixed: until ~= now+2500; the old bug set until = 2500 and
        # this same call returned nil because uptime had already passed it)
        assert dr.timbre(3000) is not None, \
            "timbre expired at boot-relative TTL — now_ms wasn't threaded"
        # and it still expires a full TTL *after* it arrived, not after boot
        assert dr.timbre(6000) is None

    def test_tincan_lifetime_is_measured_from_now(self):
        d = Device()
        d.ticks(60)                       # past any boot-relative window
        d.send({"t": "tincan", "side_dd": 0, "pulses": [0, 200, 400],
                "gap_ms": 100})
        d.ticks(1)
        dr = d.req("display.dream_renderer")
        tc = dr.tincan()
        assert tc is not None
        # t0 was stamped at ~now (3000+), not 0 — so it's in the recent past
        assert tc["t0_ms"] >= 3000
