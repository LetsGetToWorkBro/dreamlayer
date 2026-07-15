"""Confluence — two wearers, one entangled sky, and everything that
rides the bond."""
import time
from pathlib import Path

import pytest

from dreamlayer.confluence import (
    BondManager, EntangledSky, TinCan, SharedRhythms, DuetSession,
    export_claims, crossings, wrap_gift, unwrap_gift,
    Beacon, MeshManager,
    MSG_CONFLUENCE, MSG_TINCAN, BOND_TTL_S,
)
from dreamlayer.confluence.entangle import (
    MERGE_THRESHOLD, PEER_STALE_S,
)
from dreamlayer.dream_mode.premonition import RecurrenceModel
from dreamlayer.dream_mode.weather_ledger import WeatherSnapshot
from dreamlayer.memory.privacy import PrivacyGate

NOW = 1_700_000_000.0
assert time.gmtime(NOW).tm_wday == 1     # Tuesday anchor


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


class Veil:
    def __init__(self, allow=True):
        self.allow = allow

    def allow_capture(self):
        return self.allow


def bonded_pair(clock=None):
    """Two BondManagers through the full mutual opt-in."""
    clock = clock or Clock()
    a, b = BondManager(now_fn=clock), BondManager(now_fn=clock)
    offer = a.propose("dinner")
    b.accept(offer.bond_id, offer.code)
    a.confirm(offer.bond_id)
    return a, b, offer, clock


def colors(y=400, cb=300, cr=600):
    return [{"idx": i, "y": y, "cb": cb, "cr": cr} for i in range(1, 5)]


class TestBond:
    def test_mutual_opt_in_required(self):
        clock = Clock()
        a, b = BondManager(now_fn=clock), BondManager(now_fn=clock)
        offer = a.propose()
        # peer accepted, but proposer never confirmed: A is not live
        b.accept(offer.bond_id, offer.code)
        assert a.live_bond() is None
        assert a.send_weather(0.5, colors()) is None
        a.confirm(offer.bond_id)
        assert a.live_bond() is not None

    def test_both_sides_derive_the_same_key(self):
        a, b, offer, _ = bonded_pair()
        assert a.bond(offer.bond_id).key == b.bond(offer.bond_id).key

    def test_weather_roundtrip(self):
        a, b, _, _ = bonded_pair()
        pkt = a.send_weather(0.42, colors())
        received = b.receive_weather(pkt.to_wire())
        assert received is not None
        assert received.state == pytest.approx(0.42)

    def test_forged_packet_dropped(self):
        a, b, _, _ = bonded_pair()
        wire = a.send_weather(0.42, colors()).to_wire()
        wire["state"] = 0.99                     # tamper
        assert b.receive_weather(wire) is None

    def test_replay_dropped(self):
        a, b, _, _ = bonded_pair()
        wire = a.send_weather(0.4, colors()).to_wire()
        assert b.receive_weather(wire) is not None
        assert b.receive_weather(wire) is None   # same seq again

    def test_stranger_radio_ignored(self):
        _, b, _, _ = bonded_pair()
        stranger = BondManager(now_fn=Clock())
        offer = stranger.propose()
        stranger.accept(offer.bond_id, offer.code)
        stranger.confirm(offer.bond_id)
        wire = stranger.send_weather(0.9, colors()).to_wire()
        assert b.receive_weather(wire) is None

    def test_veil_silences_the_sender(self):
        clock = Clock()
        veil = Veil(True)
        a = BondManager(privacy=veil, now_fn=clock)
        b = BondManager(now_fn=clock)
        offer = a.propose()
        b.accept(offer.bond_id, offer.code)
        a.confirm(offer.bond_id)
        assert a.send_weather(0.5, colors()) is not None
        veil.allow = False
        assert a.send_weather(0.5, colors()) is None

    def test_dissolve_is_unilateral_and_immediate(self):
        a, b, offer, _ = bonded_pair()
        b.dissolve(offer.bond_id)
        wire = a.send_weather(0.5, colors()).to_wire()
        assert b.receive_weather(wire) is None

    def test_bond_expires(self):
        a, b, offer, clock = bonded_pair()
        clock.t += BOND_TTL_S + 1
        assert a.live_bond() is None
        assert a.send_weather(0.5, colors()) is None

    def test_only_weather_crosses(self):
        a, _, _, _ = bonded_pair()
        wire = a.send_weather(0.5, colors()).to_wire()
        assert set(wire) == {"bond_id", "seq", "state", "colors", "mac"}


class TestEntangledSky:
    def make(self):
        clock = Clock()
        a, b, _, _ = bonded_pair(clock)
        sky = EntangledSky(b, now_fn=clock)     # B's display
        return a, b, sky, clock

    def feed(self, a, sky, state, cols=None):
        assert sky.receive(a.send_weather(state, cols or colors()).to_wire())

    def test_convergence_merges_the_sky(self):
        a, _, sky, _ = self.make()
        self.feed(a, sky, 0.30)
        frames = []
        for _ in range(30):
            frames = sky.tick(my_state=0.30, my_colors=colors()) or frames
        conf = [f for f in frames if f["t"] == MSG_CONFLUENCE][-1]
        assert conf["mode"] == "merged"
        assert sky.togetherness > MERGE_THRESHOLD

    def test_merged_palette_is_the_blend(self):
        a, _, sky, _ = self.make()
        self.feed(a, sky, 0.30, cols=colors(y=800, cb=200, cr=200))
        frames = []
        for _ in range(30):
            frames += sky.tick(my_state=0.30,
                               my_colors=colors(y=400, cb=600, cr=600))
        merged = [f for f in frames if f["t"] == "palette"]
        assert merged, "a merged sky re-paints the palette"
        slot = merged[-1]["colors"][0]
        assert slot["y"] == 600 and slot["cb"] == 400   # 50/50

    def test_drift_splits_the_sky(self):
        a, _, sky, _ = self.make()
        self.feed(a, sky, 0.30)
        for _ in range(30):
            sky.tick(my_state=0.30, my_colors=colors())
        self.feed(a, sky, 0.95)                  # the peer storms away
        frames = []
        for _ in range(40):
            frames += sky.tick(my_state=0.10, my_colors=colors())
        splits = [f for f in frames
                  if f["t"] == MSG_CONFLUENCE and f["mode"] == "split"]
        assert splits
        assert "seam_dd" in splits[-1] and "peer_rgb" in splits[-1]
        # the seam widens with divergence
        assert splits[-1]["gap_deg"] > splits[0]["gap_deg"] * 0.9

    def test_quiet_peer_fades_to_solo(self):
        a, _, sky, clock = self.make()
        self.feed(a, sky, 0.30)
        sky.tick(my_state=0.30, my_colors=colors())
        clock.t += PEER_STALE_S + 1
        frames = sky.tick(my_state=0.30, my_colors=colors())
        assert frames == [{"t": MSG_CONFLUENCE, "mode": "solo"}]
        assert sky.tick(my_state=0.30, my_colors=colors()) == []

    def test_steady_togetherness_costs_no_radio(self):
        a, _, sky, _ = self.make()
        self.feed(a, sky, 0.30)
        for _ in range(40):
            frames = sky.tick(my_state=0.30, my_colors=colors())
        assert frames == []                      # settled: silence


class TestTinCan:
    def test_ping_roundtrip(self):
        clock = Clock()
        a, b, _, _ = bonded_pair(clock)
        can = TinCan(a, now_fn=clock)
        wire = can.compose(["single", "double", "long"])
        assert wire is not None
        assert b.receive_weather(wire) is not None   # authenticated
        frame = TinCan.render_frame(wire, side_deg=90.0)
        assert frame["t"] == MSG_TINCAN
        assert frame["pulses"] == [140, 320, 640]

    def test_cooldown_and_budget(self):
        clock = Clock()
        a, _, _, _ = bonded_pair(clock)
        can = TinCan(a, now_fn=clock)
        assert can.compose(["single"] * 20)["ping"] == [140] * 5  # capped
        assert can.compose(["single"]) is None                    # cooldown
        clock.t += 5.0
        assert can.compose(["single"]) is not None

    def test_no_bond_no_ping(self):
        can = TinCan(BondManager(now_fn=Clock()), now_fn=Clock())
        assert can.compose(["single"]) is None


def tuesday_rhythm(model, place, hour=18):
    """Two Tuesdays of the same rhythm at `place`."""
    for weeks in (1, 2):
        ts = NOW - weeks * 7 * 86400.0
        day_start = ts - (time.gmtime(ts).tm_hour * 3600
                          + time.gmtime(ts).tm_min * 60
                          + time.gmtime(ts).tm_sec)
        model.observe("memory", "training rounds together",
                      day_start + hour * 3600.0, place=place)


class TestCrossing:
    def test_shared_rhythm_found(self):
        a_model, b_model = RecurrenceModel(), RecurrenceModel()
        tuesday_rhythm(a_model, "cafe")
        tuesday_rhythm(b_model, "cafe")
        key = b"bondkey"
        found = crossings(a_model, export_claims(b_model, key), key)
        assert len(found) == 1
        assert found[0].hour == 18

    def test_different_places_never_cross(self):
        a_model, b_model = RecurrenceModel(), RecurrenceModel()
        tuesday_rhythm(a_model, "cafe")
        tuesday_rhythm(b_model, "gym")
        key = b"bondkey"
        assert crossings(a_model, export_claims(b_model, key), key) == []

    def test_claims_carry_no_schedule(self):
        model = RecurrenceModel()
        tuesday_rhythm(model, "cafe")
        claims = export_claims(model, b"bondkey")
        for c in claims:
            assert set(c) == {"wd", "h", "p"}
            assert "cafe" not in c["p"]          # salted hash, not a name

    def test_salt_makes_claims_unlinkable_across_bonds(self):
        model = RecurrenceModel()
        tuesday_rhythm(model, "cafe")
        p1 = export_claims(model, b"bond-one")[0]["p"]
        p2 = export_claims(model, b"bond-two")[0]["p"]
        assert p1 != p2

    def test_veil_silences_the_crossing_export(self):
        """Audit 2026-07-14: the one confluence path touching predictive memory
        must honor the veil — a veiled/paused wearer exports NO claims, so
        nothing crosses the bond and no shared ghost is computed."""
        class Veiled:
            def allow_capture(self): return False
            def allow_recall(self): return False
        model = RecurrenceModel()
        tuesday_rhythm(model, "cafe")
        assert export_claims(model, b"bondkey") != []          # open: exports
        assert export_claims(model, b"bondkey", privacy=Veiled()) == []
        # and the local crossing computation is silenced too
        peer = RecurrenceModel(); tuesday_rhythm(peer, "cafe")
        assert crossings(model, export_claims(peer, b"k"), b"k",
                         privacy=Veiled()) == []
        sr = SharedRhythms(model, b"k", privacy=Veiled())
        sr.update(export_claims(peer, b"k"))
        assert sr.predict(0.0) == []

    def test_shared_ghosts_render_through_kind6(self):
        a_model, b_model = RecurrenceModel(), RecurrenceModel()
        tuesday_rhythm(a_model, "cafe")
        tuesday_rhythm(b_model, "cafe")
        key = b"bondkey"
        shared = SharedRhythms(a_model, key)
        assert shared.update(export_claims(b_model, key))
        # Tuesday 14:00 — the crossing at 18:00 is 4h ahead
        day_start = NOW - (time.gmtime(NOW).tm_hour * 3600
                           + time.gmtime(NOW).tm_min * 60
                           + time.gmtime(NOW).tm_sec)
        preds = shared.predict(day_start + 14 * 3600.0)
        assert len(preds) == 1 and preds[0].hour == 18


class TestDuet:
    def test_two_performers_one_figment(self):
        duet = DuetSession("Sparring drill", performers=("coach", "kid"))
        duet.double_tap("coach")
        duet.say("kid", "rolling - three minutes")
        duet.say("coach", "last ten seconds, pulse")
        duet.say("kid", "then it starts again")
        result = duet.finish()
        assert result.ok
        assert result.figment.meta["duet"]["credits"] == \
            ["coach", "kid", "coach", "kid"]
        assert result.figment.scenes["rolling"].duration_sec == 180.0

    def test_either_performer_corrects_any_beat(self):
        duet = DuetSession(performers=("coach", "kid"))
        duet.say("kid", "thirty seconds")
        bad = duet.say("kid", "strobe thirty times a second")
        assert not duet.finish().ok
        duet.redo("coach", bad.index, "last ten seconds, pulse")
        result = duet.finish()
        assert result.ok
        assert duet.credits[bad.index] == "coach"

    def test_unknown_performer_rejected(self):
        duet = DuetSession(performers=("a", "b"))
        with pytest.raises(ValueError):
            duet.tap("stranger")

    def test_both_keep_their_own_signed_copy(self, tmp_path):
        from dreamlayer.reality_compiler.v2 import RealityCompilerV2
        from dreamlayer.confluence import keep_for_both
        duet = DuetSession(performers=("a", "b"))
        duet.double_tap("a")
        duet.say("b", "rolling - three minutes")
        result = duet.finish()
        rc_a = RealityCompilerV2(vault_dir=tmp_path / "a")
        rc_b = RealityCompilerV2(vault_dir=tmp_path / "b")
        ea, eb = keep_for_both(result, rc_a, rc_b)
        assert ea.sig != eb.sig                  # separate keys
        rc_a.revoke(result.figment.id)           # independent revocation
        assert rc_a.repertoire() == []
        assert len(rc_b.repertoire()) == 1


class TestWeatherGift:
    def snapshot(self):
        return WeatherSnapshot(ts=NOW - 6 * 3600.0, place="kitchen",
                               colors=colors(y=700), amplitude=0.3)

    def test_gift_plays_on_the_peer_sky(self):
        a, b, _, _ = bonded_pair()
        wire = wrap_gift(a, self.snapshot())
        frames = unwrap_gift(b, wire)
        assert len(frames) == 6                  # 30s at ledger cadence
        assert all(f["t"] == "palette" for f in frames)
        assert frames[0]["colors"][0]["y"] == 700

    def test_forged_gift_plays_nothing(self):
        a, b, _, _ = bonded_pair()
        wire = wrap_gift(a, self.snapshot())
        wire["colors"] = colors(y=100)           # tamper
        assert unwrap_gift(b, wire) == []

    def test_veiled_sender_cannot_gift(self):
        clock = Clock()
        veil = Veil(False)
        a = BondManager(privacy=veil, now_fn=clock)
        assert wrap_gift(a, self.snapshot()) is None


class TestDeviceRenderer:
    @pytest.fixture
    def renderer(self):
        lupa = pytest.importorskip("lupa")
        rt = lupa.LuaRuntime(unpack_returned_tuples=True)
        root = Path(__file__).resolve().parents[4] / "halo-lua"
        rt.execute(f'package.path = "{root}/?.lua;" .. package.path')
        r = rt.eval('require("display.dream_renderer")')
        return rt, (r[0] if isinstance(r, tuple) else r)

    def test_lockstep_constants(self):
        root = Path(__file__).resolve().parents[4] / "halo-lua"
        lua = (root / "ble" / "message_types.lua").read_text()
        assert f'"{MSG_CONFLUENCE}"' in lua
        assert f'"{MSG_TINCAN}"' in lua

    def test_split_stored_solo_clears(self, renderer):
        rt, dr = renderer
        dr.on_confluence(rt.table(t=MSG_CONFLUENCE, mode="split", tg=30,
                                  seam_dd=-900, gap_deg=24,
                                  peer_rgb=rt.table(200, 80, 60)))
        c = dr.confluence()
        assert c["mode"] == "split" and c["gap_deg"] == 24
        dr.on_confluence(rt.table(t=MSG_CONFLUENCE, mode="solo"))
        assert dr.confluence() is None

    def test_tincan_pulse_train_consumed(self, renderer):
        rt, dr = renderer
        dr.on_tincan(rt.table(t=MSG_TINCAN, side_dd=900,
                              pulses=rt.table(140, 320), gap_ms=220), 0)
        assert dr.tincan() is not None
        dr.draw_frame(100)          # headless safe mid-train
        dr.draw_frame(5000)         # long past the train: consumed


class TestVeilRecallGate:
    """Veil/Recall Gate integrity (audit 2026-07-15). Inbound peer content —
    a gifted sky, an entangled sky, a beacon rim — is a read-back painted onto
    MY device, so the full pause veil ("deaf and blind") must silence it. These
    fail on revert: without the gate a paused wearer still sees the peer. And
    incognito must NOT silence recall — only capture stops while incognito, so
    you can still see what you already share."""

    def snapshot(self):
        return WeatherSnapshot(ts=NOW - 6 * 3600.0, place="kitchen",
                               colors=colors(y=700), amplitude=0.3)

    # -- gift.unwrap_gift -----------------------------------------------------

    def test_paused_veil_silences_gifted_sky(self):
        a, b, _, _ = bonded_pair()
        gate = PrivacyGate()
        gate.pause()
        assert unwrap_gift(b, wrap_gift(a, self.snapshot()), privacy=gate) == []
        # unpaused (default gate): the gifted sky plays in full
        frames = unwrap_gift(b, wrap_gift(a, self.snapshot()))
        assert len(frames) == 6 and frames[0]["colors"][0]["y"] == 700

    def test_incognito_still_replays_the_gift(self):
        a, b, _, _ = bonded_pair()
        gate = PrivacyGate()
        gate.set_incognito(True)                 # capture stops, recall does not
        assert not gate.allow_capture() and gate.allow_recall()
        frames = unwrap_gift(b, wrap_gift(a, self.snapshot()), privacy=gate)
        assert len(frames) == 6

    # -- entangle.EntangledSky ------------------------------------------------

    def test_paused_veil_blinds_the_entangled_sky(self):
        clock = Clock()
        a, b, _, _ = bonded_pair(clock)
        gate = PrivacyGate()
        sky = EntangledSky(b, now_fn=clock, privacy=gate)
        assert sky.receive(a.send_weather(0.30, colors()).to_wire())
        opened = []
        for _ in range(30):
            opened += sky.tick(my_state=0.30, my_colors=colors())
        assert opened                            # open: renders the shared sky
        gate.pause()
        assert sky.peer_present()                # the peer is still fresh...
        assert sky.tick(my_state=0.30, my_colors=colors()) == []   # ...yet blind

    def test_paused_veil_makes_the_sky_deaf(self):
        clock = Clock()
        a, b, _, _ = bonded_pair(clock)
        gate = PrivacyGate()
        gate.pause()
        sky = EntangledSky(b, now_fn=clock, privacy=gate)
        assert sky.receive(a.send_weather(0.30, colors()).to_wire()) is False
        assert not sky.peer_present()

    def test_incognito_leaves_the_sky_entangled(self):
        clock = Clock()
        a, b, _, _ = bonded_pair(clock)
        gate = PrivacyGate()
        gate.set_incognito(True)
        sky = EntangledSky(b, now_fn=clock, privacy=gate)
        assert sky.receive(a.send_weather(0.30, colors()).to_wire())
        frames = []
        for _ in range(30):
            frames += sky.tick(my_state=0.30, my_colors=colors())
        assert frames                            # incognito still renders

    # -- beacon.Beacon --------------------------------------------------------

    def _lit_beacon(self, clock, gate):
        """A Beacon whose mesh already holds one fresh peer bearing. The fold is
        done at the mesh level so the render gate is what's under test."""
        me = MeshManager(now_fn=clock, me="me")
        peer = MeshManager(now_fn=clock, me="peer")
        gid, code = me.form()
        peer.join(gid, code)
        pkt = peer.emit("bearing", {"bearing_dd": 900, "dist": "near"})
        assert me.receive(pkt.to_wire()) is not None
        return Beacon(me, now_fn=clock, privacy=gate)

    def test_paused_veil_blinds_the_beacon(self):
        clock = Clock()
        gate = PrivacyGate()
        beacon = self._lit_beacon(clock, gate)
        assert beacon.render_frames()            # open: a pulse at the bearing
        assert beacon.card() is not None
        gate.pause()
        assert beacon.render_frames() == []      # blind
        assert beacon.card() is None

    def test_paused_veil_makes_the_beacon_deaf(self):
        clock = Clock()
        me = MeshManager(now_fn=clock, me="me")
        peer = MeshManager(now_fn=clock, me="peer")
        gid, code = me.form()
        peer.join(gid, code)
        gate = PrivacyGate()
        gate.pause()
        beacon = Beacon(me, now_fn=clock, privacy=gate)
        pkt = peer.emit("bearing", {"bearing_dd": 900, "dist": "near"})
        assert beacon.receive(pkt.to_wire()) is None   # deaf: not folded in

    def test_incognito_leaves_the_beacon_lit(self):
        clock = Clock()
        gate = PrivacyGate()
        gate.set_incognito(True)
        beacon = self._lit_beacon(clock, gate)
        assert beacon.render_frames()            # incognito still pulses
        assert beacon.card() is not None
