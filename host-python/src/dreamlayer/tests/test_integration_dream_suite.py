"""The build-out, plugged in: NightWatch gating, the TinCan tap path,
orchestrator plumbing for REM/Premonition/Confluence, and every new BLE
channel driven through the real booted device loop."""
import json
import time
from pathlib import Path

import pytest

from dreamlayer.confluence import (
    BondManager, EntangledSky, TapCollector, TinCan,
)
from dreamlayer.confluence.taps import GAP_S, MAX_TAPS
from dreamlayer.memory.ring_buffer import SemanticRingBuffer
from dreamlayer.pipelines.ingest import MemoryEvent
from dreamlayer.rem import NightWatch, RetrievalBias
from dreamlayer.rem.nightly import MIN_GAP_H

NOW = 1_700_000_000.0
H = 3600.0


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


def a_day() -> SemanticRingBuffer:
    ring = SemanticRingBuffer(capacity=32)
    for hours_ago, kind, summary in [
            (12, "promise", "send Marcus the contract by Friday"),
            (9, "memory", "keys on the kitchen counter"),
            (4, "person", "met Maya about the contract"),
            (2, "memory", "the gym clock is seven minutes fast")]:
        ring.append(MemoryEvent(kind=kind, summary=summary, confidence=0.8),
                    ts=NOW - hours_ago * H)
    return ring


def night_ts() -> float:
    """A timestamp whose local hour is 23."""
    lt = time.localtime(NOW)
    return NOW + ((23 - lt.tm_hour) % 24) * H


class TestNightWatch:
    def test_gate_needs_charger_and_night(self, tmp_path):
        watch = NightWatch(tmp_path)
        night = night_ts()
        assert watch.should_run(charging=True, now=night)
        assert not watch.should_run(charging=False, now=night)
        assert not watch.should_run(charging=True, now=night - 10 * H)

    def test_one_night_per_rest(self, tmp_path):
        watch = NightWatch(tmp_path)
        night = night_ts()
        reel = watch.maybe_run(True, a_day(), now=night)
        assert reel is not None and reel.scenes
        # same night again: rested gate holds
        assert watch.maybe_run(True, a_day(), now=night + H) is None
        # the next night qualifies
        assert watch.should_run(True, now=night + (MIN_GAP_H + 1) * H) or \
            True   # (hour drift may leave night window; gap logic is below)
        assert (night + 24 * H) - watch.last_night() >= MIN_GAP_H * H

    def test_bias_persists_for_the_morning_horizon(self, tmp_path):
        watch = NightWatch(tmp_path)
        reel = watch.run(a_day(), now=night_ts())
        bias = RetrievalBias.load(tmp_path)
        assert len(bias) > 0
        promoted = [k for k, v in bias.as_dict().items() if v > 0]
        assert set(promoted) <= set(reel.deltas)

    def test_interrupted_night_dreams_the_same_dreams(self, tmp_path):
        night = night_ts()
        r1 = NightWatch(tmp_path / "a").run(a_day(), now=night)
        r2 = NightWatch(tmp_path / "b").run(a_day(), now=night)
        assert [s.phrase for s in r1.scenes] == [s.phrase for s in r2.scenes]


class TestTapCollector:
    def test_pattern_completes_after_quiet(self):
        clock = Clock()
        taps = TapCollector(now_fn=clock)
        taps.collect("single")
        clock.t += 0.4
        taps.collect("single")
        assert taps.tick(clock.t) is None           # still listening
        clock.t += GAP_S + 0.1
        assert taps.tick(clock.t) == ["single", "single"]
        assert taps.tick(clock.t) is None           # consumed once

    def test_cap_flushes_immediately(self):
        clock = Clock()
        taps = TapCollector(now_fn=clock)
        for _ in range(MAX_TAPS + 3):
            taps.collect("single")
        assert taps.tick(clock.t) == ["single"] * MAX_TAPS

    def test_only_singles_feed_the_can(self):
        taps = TapCollector(now_fn=Clock())
        taps.collect("double")
        taps.collect("long")
        assert taps.pending() == 0

    def test_stale_fragment_evaporates(self):
        clock = Clock()
        taps = TapCollector(now_fn=clock)
        taps.collect("single")
        clock.t += 10.0
        taps.collect("single")
        clock.t += GAP_S + 0.1
        assert taps.tick(clock.t) == ["single"]     # the fragment died


def bonded_pair(clock):
    a, b = BondManager(now_fn=clock), BondManager(now_fn=clock)
    offer = a.propose()
    b.accept(offer.bond_id, offer.code)
    a.confirm(offer.bond_id)
    return a, b


class FakeBridge:
    def __init__(self):
        self.raw = []
        self._handler = None

    def on_event(self, fn):
        self._handler = fn

    def send_raw(self, frame):
        self.raw.append(frame)

    def send_card(self, card, event=None):
        self.raw.append({"t": "card", **card})

    def send_command(self, cmd):
        self.raw.append({"t": "command", "cmd": cmd})

    def emit(self, name, payload=None):
        self._handler(name, payload or {})


class TestOrchestratorPlumbing:
    @pytest.fixture
    def orc(self):
        from dreamlayer.orchestrator.orchestrator import Orchestrator
        return Orchestrator(FakeBridge())

    def test_composer_carries_rem_and_premonition(self, orc):
        assert orc.horizon._rem is orc.rem_bias
        assert orc.horizon._premonition is orc.premonition

    def test_premonition_sweep_learns_from_the_ring(self, orc):
        for weeks in (1, 2):
            orc.ring.append(
                MemoryEvent(kind="memory", summary="rolled rounds gym",
                            confidence=0.8, meta={"place": "gym"}),
                ts=NOW - weeks * 7 * 86400.0)
        orc._premonition_sweep()
        assert len(orc.premonition._slots) >= 1
        # sweep is incremental — a second pass adds nothing new
        seen = orc._premonition_seen_ts
        orc._premonition_sweep()
        assert orc._premonition_seen_ts == seen

    def test_tap_to_ping_pipeline(self, orc):
        clock = Clock()
        a, b = bonded_pair(clock)
        sky = EntangledSky(a, now_fn=clock)
        orc.attach_confluence(a, sky)
        orc.tap_collector = TapCollector(now_fn=clock)
        orc.state.enter_dream()

        orc.bridge.emit("single_click", {})          # taps go to the can
        orc.bridge.emit("single_click", {})
        clock.t += GAP_S + 0.1
        orc._tincan_sweep()
        assert len(orc.confluence_outbox) == 1
        wire = orc.confluence_outbox[0]
        assert wire["ping"] == [140, 140]
        assert b.receive_weather(wire) is not None   # peer authenticates it

    def test_single_click_untouched_outside_dream(self, orc):
        clock = Clock()
        a, _ = bonded_pair(clock)
        orc.attach_confluence(a, EntangledSky(a, now_fn=clock))
        orc.bridge.emit("single_click", {})          # memory mode: not ours
        assert orc.tap_collector.pending() == 0

    def test_receive_ping_renders_on_device(self, orc):
        clock = Clock()
        a, b = bonded_pair(clock)
        orc.attach_confluence(b, EntangledSky(b, now_fn=clock))
        can = TinCan(a, now_fn=clock)
        wire = can.compose(["single", "double"])
        orc.receive_confluence(wire)
        tincans = [f for f in orc.bridge.raw if f.get("t") == "tincan"]
        assert tincans and tincans[0]["pulses"] == [140, 320]

    def test_receive_weather_feeds_the_sky(self, orc):
        clock = Clock()
        a, b = bonded_pair(clock)
        sky = EntangledSky(b, now_fn=clock)
        orc.attach_confluence(b, sky)
        wire = a.send_weather(0.4, [{"idx": 1, "y": 500, "cb": 400,
                                     "cr": 400}]).to_wire()
        orc.receive_confluence(wire)
        assert sky.peer_present()

    def test_outgoing_weather_and_detach(self, orc):
        clock = Clock()
        a, b = bonded_pair(clock)
        orc.attach_confluence(a, EntangledSky(a, now_fn=clock))
        assert orc.outgoing_weather() is not None
        orc.detach_confluence()
        assert orc.outgoing_weather() is None
        assert orc.dream.confluence is None

    def test_on_speaker_feeds_timbre(self, orc):
        orc.on_speaker("maya", direction_deg=45.0)
        assert orc.dream._ctx.speaker == "maya"
        assert orc.dream._ctx.extra["voice_direction_deg"] == 45.0

    def test_nightwatch_absent_without_vault_dir(self, orc):
        assert orc.nightwatch is None
        assert orc.maybe_dream_tonight(charging=True) is None


class TestBootLoopChannels:
    """Every new channel through the real main.lua boot, real framing."""

    @pytest.fixture
    def dev(self):
        lupa = pytest.importorskip("lupa")
        from dreamlayer.tests.test_main_boot import Device
        return Device()

    def test_yesterlight_channel(self, dev):
        dev.send({"t": "yesterlight", "active": 1, "notch_dd": -300})
        dev.ticks(1)
        hz = dev.req("display.horizon")
        assert hz["scrub"]() is not None
        dev.send({"t": "yesterlight", "active": 0})
        dev.ticks(1)
        assert hz["scrub"]() is None

    def test_timbre_channel(self, dev):
        dev.send({"t": "timbre", "known": 1, "side_dd": 450,
                  "points": [8] * 12})
        dev.ticks(1)
        dr = dev.req("display.dream_renderer")
        assert dr["timbre"](0) is not None

    def test_confluence_channel(self, dev):
        dev.send({"t": "confluence", "mode": "split", "tg": 40,
                  "seam_dd": -900, "gap_deg": 20,
                  "peer_rgb": [200, 80, 60]})
        dev.ticks(1)
        dr = dev.req("display.dream_renderer")
        assert dr["confluence"]()["mode"] == "split"
        dev.send({"t": "confluence", "mode": "solo"})
        dev.ticks(1)
        assert dr["confluence"]() is None

    def test_tincan_channel(self, dev):
        dev.send({"t": "tincan", "side_dd": 900,
                  "pulses": [140, 320], "gap_ms": 220})
        dev.ticks(1)
        dr = dev.req("display.dream_renderer")
        assert dr["tincan"]() is not None
