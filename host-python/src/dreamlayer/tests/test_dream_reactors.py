"""Timbre and Yesterlight — two lenses whose halves could not reach each other.

Both were written on both sides and connected on neither.
`dream_mode/timbre_reactor.py` and `dream_mode/yesterlight.py` produce raw
frames; `halo-lua/ble/message_types.lua` declares `TIMBRE` and `YESTERLIGHT`
and `dream_renderer.lua`/`horizon.lua` draw them, with the Lua carrying the
comment *"Python side dream_mode/timbre_reactor.py MSG_TIMBRE — keep in sync"*.
Their only caller was `DreamEngine`, built by the `Orchestrator` the shipped
Brain never instantiates (decisions/0001) — the fifth instance of that pattern.

`bridge/base.RAW_FRAME_TYPES` was missing both names as well, so a frame could
not have crossed the bridge even if something had produced one.
"""
from __future__ import annotations

import threading

from dreamlayer.ai_brain.server.dream_reactors import DreamReactors
from dreamlayer.bridge.base import RAW_FRAME_TYPES, pause_allows_raw


class _Brain:
    def __init__(self, veiled=False):
        self._event_lock = threading.Lock()
        self._event_subs: list = []
        self._veiled = veiled
        self._zone_was = "kitchen"

    def incognito_now(self):
        return self._veiled

    def push_raw(self, frame):
        from dreamlayer.ai_brain.server.server import Brain
        return Brain.push_raw(self, frame)

    def push_event(self, kind, card=None, veil_ok=False):
        # The REAL funnel, so the Veil and the interruption preferences apply
        # here exactly as they do in production rather than being stubbed away.
        from dreamlayer.ai_brain.server.server import Brain
        self.PROACTIVE_KINDS = Brain.PROACTIVE_KINDS
        return Brain.push_event(self, kind, card, veil_ok)

    def _may_interrupt(self, kind):
        return True

    def _attention_allows(self, kind, card):
        return True


class _Baseline:
    prosody_mean = {"pitch_mean": 180.0, "jitter": 0.02, "shimmer": 0.05,
                    "speech_rate": 3.1, "energy": 0.6, "pause_ratio": 0.2}


def _drain(brain):
    """Every frame the fan-out delivered this test."""
    out = []
    for q in brain._event_subs:
        while not q.empty():
            out.append(q.get_nowait())
    return out


def _sub(brain):
    import queue
    q: queue.Queue = queue.Queue(maxsize=64)
    brain._event_subs.append(q)
    return q


class TestTheTransportAcceptsThemAtAll:
    """The gap that made both lenses undeliverable regardless of any wiring."""

    def test_both_frame_types_are_transportable(self):
        assert "timbre" in RAW_FRAME_TYPES
        assert "yesterlight" in RAW_FRAME_TYPES

    def test_neither_crosses_the_pause_boundary(self):
        # Both derive from live signal — who is speaking, where you are — so
        # neither may pass while capture is paused. Adding them to the type set
        # must not have added them to the pause exemption.
        assert pause_allows_raw({"t": "timbre", "known": 1}) is False
        assert pause_allows_raw({"t": "yesterlight", "active": 1}) is False
        assert pause_allows_raw({"t": "dream_exit"}) is True   # still does


class TestTimbre:
    def _reactors(self, brain, baseline=_Baseline()):
        r = DreamReactors(brain, now_fn=lambda: 1000.0)
        r.timbre()._baselines = type("_B", (), {
            "get_baseline": staticmethod(lambda s: baseline)})()
        return r

    def test_a_known_voice_paints_the_rim(self):
        b = _Brain()
        q = _sub(b)
        r = self._reactors(b)
        assert r.note_speaker("maya") == 1
        frame = q.get_nowait()["raw"]
        assert frame["t"] == "timbre" and frame["known"] == 1
        assert len(frame["points"]) == 12

    def test_a_stranger_is_presence_without_identity(self):
        b = _Brain()
        q = _sub(b)
        r = self._reactors(b, baseline=None)
        assert r.note_speaker("stranger") == 1
        frame = q.get_nowait()["raw"]
        assert frame["known"] == 0, "a stranger was drawn as a known contact"

    def test_silence_is_not_a_stranger(self):
        # An empty label means nobody was attributed. Treating it as a stranger
        # would draw static every time the room went quiet.
        b = _Brain()
        _sub(b)
        assert self._reactors(b).note_speaker("") == 0
        assert _drain(b) == []

    def test_silence_does_not_even_reach_the_reactor(self):
        """What the early-out actually buys, and why asserting 0 is not enough.

        `TimbreReactor.tick` refuses an empty label too, so deleting
        `note_speaker`'s own guard changes no OUTCOME — a mutation removing it
        left the whole suite green. What it changes is cost: this runs on the
        capture hot path, once per attributed segment, and without the guard
        every silent beat builds a RecallContext and walks into the reactor to
        be told no.

        So the thing to pin is that the reactor is never consulted.
        """
        b = _Brain()
        _sub(b)
        r = DreamReactors(b, now_fn=lambda: 1000.0)
        seen = []
        r._timbre = type("_T", (), {
            "tick": staticmethod(lambda ctx: seen.append(ctx))})()
        assert r.note_speaker("") == 0
        assert seen == [], (
            "an empty speaker label was carried all the way into the reactor")

    def test_the_veil_stops_it(self):
        b = _Brain(veiled=True)
        _sub(b)
        assert self._reactors(b).note_speaker("maya") == 0
        assert _drain(b) == [], "a timbre frame crossed the Veil"

    def test_the_cooldown_holds_a_talkative_room_down(self):
        b = _Brain()
        _sub(b)
        r = self._reactors(b)
        assert r.note_speaker("maya") == 1
        assert r.note_speaker("maya") == 0, "the rim would strobe"

    def test_a_reactor_that_raises_never_breaks_capture(self):
        b = _Brain()
        r = DreamReactors(b)
        r._timbre = type("_T", (), {
            "tick": staticmethod(lambda ctx: (_ for _ in ()).throw(
                RuntimeError("boom")))})()
        assert r.note_speaker("maya") == 0

    def test_only_a_delivered_frame_counts(self):
        b = _Brain(veiled=True)
        _sub(b)
        r = self._reactors(b)
        r.note_speaker("maya")
        assert r.timbre_frames == 0 and r.timbre_live() is False


class TestYesterlight:
    def _armed(self, brain):
        """A ledger with something recorded, so the lens has a past to reach."""
        r = DreamReactors(brain, now_fn=lambda: 1000.0)
        led = r.ledger()
        for i in range(3):
            led.record("kitchen", {"colors": [{"idx": 0, "y": 40, "cb": 0,
                                               "cr": 0}]}, 0.4)
            led._last_record = 0.0            # its own 5s throttle, not the test
            led._buf[-1].ts = 500.0 + i * 60.0
        return r

    def test_a_place_with_no_past_never_arms(self):
        b = _Brain()
        _sub(b)
        r = DreamReactors(b, now_fn=lambda: 1000.0)
        for _ in range(6):
            r.note_pose({"pitch": -1.2}, "kitchen")
        assert r.yesterlight().active is False, (
            "it armed over a place it has no recorded ambience for — the "
            "replay would be invented")

    def test_a_held_look_back_arms_and_emits(self):
        b = _Brain()
        q = _sub(b)
        r = self._armed(b)
        sent = 0
        for _ in range(6):
            sent += r.note_pose({"pitch": -1.2}, "kitchen")
        assert r.yesterlight().active is True
        assert sent > 0
        frames = [q.get_nowait()["raw"] for _ in range(q.qsize())]
        assert any(f["t"] == "yesterlight" for f in frames)

    def test_returning_your_head_flows_the_present_back(self):
        b = _Brain()
        q = _sub(b)
        r = self._armed(b)
        for _ in range(6):
            r.note_pose({"pitch": -1.2}, "kitchen")
        while not q.empty():
            q.get_nowait()
        r.note_pose({"pitch": 0.0}, "kitchen")
        assert r.yesterlight().active is False
        frames = [q.get_nowait()["raw"] for _ in range(q.qsize())]
        assert any(f.get("active") == 0 for f in frames), (
            "no exit frame — the Horizon would stay dialled back")

    def test_a_glance_is_not_a_look(self):
        b = _Brain()
        _sub(b)
        r = self._armed(b)
        r.note_pose({"pitch": -1.2}, "kitchen")     # one tick only
        assert r.yesterlight().active is False

    def test_a_poseless_beat_is_ignored(self):
        b = _Brain()
        r = self._armed(b)
        assert r.note_pose({}, "kitchen") == 0
        assert r.note_pose(None, "kitchen") == 0

    def test_the_veil_stops_it(self):
        """Record a past FIRST, then raise the Veil.

        `_armed` cannot be used on an already-veiled Brain, and that is not a
        fixture inconvenience — it is the interaction. The ledger refuses to
        record while veiled, so a session that begins under the Veil has no past
        to walk into and the lens could never arm regardless. The case that
        needs asserting is the other one: a place with genuine recorded
        ambience, and the Veil going up afterwards.
        """
        b = _Brain()
        _sub(b)
        r = self._armed(b)
        b._veiled = True
        for _ in range(6):
            r.note_pose({"pitch": -1.2}, "kitchen")
        assert _drain(b) == [], "a yesterlight frame crossed the Veil"

    def test_the_ledger_records_nothing_while_veiled(self):
        b = _Brain(veiled=True)
        r = DreamReactors(b)
        assert r.note_weather("kitchen", {"colors": [{"idx": 0}]}, 0.4) is True
        assert not r.ledger()._buf, (
            "a veiled minute left a trace of the light in the room")


class TestTheBrainDrivesThem:
    def test_dream_pose_end_to_end(self, monkeypatch):
        # monkeypatch, NOT `Brain.x = ...; del Brain.x`. `incognito_now` is a
        # real method, so deleting it strips it from the class for every test
        # that follows — 202 unrelated failures, and the SECOND time this exact
        # mistake was made in this suite. There is no case where the bare
        # assignment is the right tool here.
        from dreamlayer.ai_brain.server.server import Brain
        b = Brain.__new__(Brain)
        b._event_lock, b._event_subs = threading.Lock(), []
        b._zone_was = "kitchen"
        monkeypatch.setattr(Brain, "incognito_now", lambda s: False)
        got = Brain.dream_pose(b, {"pitch": -1.2},
                               {"colors": [{"idx": 0, "y": 40}]}, 0.4)
        assert got["ok"] is True
        assert "yesterlight_active" in got

    def test_the_status_starts_honest(self):
        from dreamlayer.ai_brain.server.server import Brain
        b = Brain.__new__(Brain)
        got = Brain.dream_status(b)
        assert got["timbre_frames"] == 0
        assert got["yesterlight_frames"] == 0

    def test_the_routes_exist(self):
        import inspect

        from dreamlayer.ai_brain.server import server as s
        src = inspect.getsource(s)
        assert '"/dreamlayer/dream/pose": _post_dream_pose' in src

    def test_the_ear_paints_the_timbre(self):
        # Read the source: this is the one place a speaker LABEL exists, and a
        # regression would be silent — captions would keep working and the rim
        # would simply never light.
        import inspect

        from dreamlayer.ai_brain.server import ear as ear_mod
        src = inspect.getsource(ear_mod)
        assert "note_speaker" in src, (
            "nothing feeds the Timbre reactor a speaker any more")


class TestPushRawIsGated:
    def test_a_frame_with_no_type_is_refused(self):
        b = _Brain()
        _sub(b)
        assert b.push_raw({"known": 1}) == 0
        assert b.push_raw("not a frame") == 0

    def test_it_reaches_every_subscriber(self):
        b = _Brain()
        q1, q2 = _sub(b), _sub(b)
        assert b.push_raw({"t": "timbre", "known": 1}) == 2
        assert q1.get_nowait()["raw"]["t"] == "timbre"
        assert q2.get_nowait()["raw"]["t"] == "timbre"

    def test_an_unreadable_posture_drops_it(self):
        b = _Brain()

        def boom():
            raise RuntimeError("unreadable")
        b.incognito_now = boom
        _sub(b)
        assert b.push_raw({"t": "timbre"}) == 0, (
            "this is about the RECORD, so it must fail closed")


class TestTheLinkForwardsRawFrames:
    def test_a_raw_frame_reaches_the_bridge(self):
        from dreamlayer.ai_brain.server.halo_link import HaloLink

        class _Bridge:
            def __init__(self):
                self.raw, self.cards = [], []

            def connect(self):
                return {"device": "halo-test"}

            def disconnect(self):
                pass

            def load_lua_app(self, root):
                pass

            def send_card(self, payload, event="answer_ready"):
                self.cards.append((event, payload))

            def send_raw(self, obj):
                self.raw.append(obj)

        b, br = _Brain(), _Bridge()
        ln = HaloLink(b, bridge=br)
        ln.connect()
        try:
            assert b.push_raw({"t": "timbre", "known": 1}) == 1
            for _ in range(200):
                if ln.sent:
                    break
                import time as _t
                _t.sleep(0.01)
            assert br.raw == [{"t": "timbre", "known": 1}]
            assert br.cards == [], "a raw frame went out as a card"
        finally:
            ln.disconnect()


class TestThePaletteReachesBothSurfaces:
    """The producer that did not exist. `hud/cards.py:palette_shift_card` had no
    caller anywhere in the tree, so the phone could never receive a
    PaletteShiftCard — and the phone is the surface that NEEDS one, because the
    glasses get palette weather natively as a raw frame their animator sweeps
    and the browser page has no such channel."""

    def _fft(self, loud=True):
        return [0.8 if loud else 0.02] * 32

    def _reactors(self, brain):
        return DreamReactors(brain, now_fn=lambda: 1000.0)

    def test_one_beat_paints_the_glass_and_the_phone(self):
        b = _Brain()
        q = _sub(b)
        got = self._reactors(b).note_mic(self._fft(), 0.6, "kitchen")
        assert got["raw"] == 1, "the glasses got no raw palette frame"
        assert got["card"] == 1, "the phone got no PaletteShiftCard"
        kinds = []
        while not q.empty():
            ev = q.get_nowait()
            kinds.append(ev.get("raw", {}).get("t") if ev.get("raw")
                         else (ev.get("card") or {}).get("type"))
        assert "palette" in kinds and "PaletteShiftCard" in kinds

    def test_both_carry_the_same_colours(self):
        # One primitive, one decision. If these ever diverge the phone is
        # showing a different room than the glasses are.
        b = _Brain()
        q = _sub(b)
        self._reactors(b).note_mic(self._fft(), 0.6, "kitchen")
        raw = card = None
        while not q.empty():
            ev = q.get_nowait()
            if ev.get("raw"):
                raw = ev["raw"]
            elif ev.get("card"):
                card = ev["card"]
        assert raw and card
        assert card["colors"] == raw["colors"]

    def test_the_veil_stops_both(self):
        b = _Brain(veiled=True)
        _sub(b)
        got = self._reactors(b).note_mic(self._fft(), 0.6, "kitchen")
        assert got == {"raw": 0, "card": 0}
        assert _drain(b) == [], "a palette crossed the Veil"

    def test_no_reading_paints_nothing_but_a_quiet_room_still_does(self):
        """`[]` is no microphone; 32 low bands is a quiet room.

        `RecallContext.has_mic()` is True for an empty list, so without an
        explicit guard the reactor paints the colour of silence for a caller
        that has no analyser at all — weather invented out of an absent sensor.
        A genuinely quiet room DOES still get a colour, deliberately: the sky
        never flatlines.
        """
        b = _Brain()
        _sub(b)
        assert self._reactors(b).note_mic([], 0.0, "kitchen") == {"raw": 0,
                                                                 "card": 0}
        quiet = self._reactors(_Brain())
        _sub(quiet.brain)
        assert quiet.note_mic(self._fft(loud=False), 0.01, "kitchen")["raw"] == 1

    def test_it_feeds_the_weather_ledger_too(self):
        # The same colours are what give Yesterlight a past to walk back into.
        b = _Brain()
        _sub(b)
        r = self._reactors(b)
        r.note_mic(self._fft(), 0.6, "kitchen")
        assert r.ledger()._buf, "nothing was recorded for Yesterlight to replay"

    def test_only_a_delivered_beat_counts(self):
        b = _Brain(veiled=True)
        _sub(b)
        r = self._reactors(b)
        r.note_mic(self._fft(), 0.6, "kitchen")
        assert r.palette_frames == 0

    def test_the_phone_ships_the_spectrum_not_a_colour(self):
        """The palette decision must live in `MicReactor`, once.

        A second definition written in JavaScript would drift from the one the
        glasses run, and the two surfaces would start showing different rooms.
        """
        from dreamlayer.ai_brain.server import live
        assert "dreamBeatToBrain" in live._PAGE
        assert '"/dreamlayer/dream/pose"' in live._PAGE
        assert "fft:" in live._PAGE

    def test_the_phone_sends_a_real_pitch(self):
        # Yesterlight reads pitch in radians. Before this the phone sent none,
        # so the lens was fed a constant 0 and could never arm.
        from dreamlayer.ai_brain.server import live
        assert "dmotion.pitch" in live._PAGE
        assert "Math.atan2(-ay, -az)" in live._PAGE
