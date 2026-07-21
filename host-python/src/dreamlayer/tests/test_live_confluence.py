"""Confluence on the Live Lens — two phones, one Brain, the REAL engine.

Everything here runs the genuine primitives (BondManager + EntangledSky):
the three-word opt-in, HMAC'd weather packets, the togetherness EMA with its
merge/split hysteresis, the stale-peer fade, and the veil silencing both
directions. The Brain is only the meeting point; these tests pin that it
adds no trust and stores nothing durable.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from dreamlayer.ai_brain.server import Brain, make_brain_server
from dreamlayer.ai_brain.server.live_confluence import LiveConfluence, room
from dreamlayer.ai_brain.server.store import BrainConfig

TOKEN = "rune-birch"


def _brain(tmp_path, **cfg) -> Brain:
    d = tmp_path / "cfg"
    d.mkdir()
    BrainConfig(token=TOKEN, **cfg).save(d)
    return Brain(d)


def _slots(hot: float = 0.5) -> list:
    q = lambda v: int((max(-1.0, min(1.0, v)) * 128 + 128)) * 4
    return [{"idx": 1, "y": 600, "cb": q(0.3 * hot), "cr": q(-0.1)},
            {"idx": 2, "y": 700, "cb": q(-0.12), "cr": q(0.4 * hot)}]


def _beats(conf, a, b, n, sa=0.8, sb=0.8):
    """n alternating weather beats; returns (frames_a, frames_b)."""
    fa, fb = [], []
    for _ in range(n):
        fa += conf.weather(a, sa, _slots())["frames"]
        fb += conf.weather(b, sb, _slots())["frames"]
    return fa, fb


class TestBondFlow:
    def test_propose_accept_speaks_the_real_code(self, tmp_path):
        conf = room(_brain(tmp_path))
        from dreamlayer.confluence.bond import CODE_WORDS
        out = conf.propose("phone-a")
        assert out.get("ok")
        assert out["code"].count("-") == CODE_WORDS - 1   # the REAL code shape
        assert conf.accept("phone-b", out["code"]) == {"ok": True}

    def test_wrong_code_never_bonds(self, tmp_path):
        conf = room(_brain(tmp_path))
        conf.propose("phone-a")
        assert "error" in conf.accept("phone-b", "wrong-words-here")
        # and weather stays un-entangled on both sides
        assert conf.weather("phone-b", 0.5, _slots())["entangled"] is False

    def test_cannot_accept_own_offer(self, tmp_path):
        conf = room(_brain(tmp_path))
        out = conf.propose("phone-a")
        assert "error" in conf.accept("phone-a", out["code"])

    def test_room_cap_refuses_politely(self, tmp_path):
        conf = room(_brain(tmp_path))
        for i in range(8):
            assert conf.propose(f"sid-{i}").get("ok")
        assert "error" in conf.propose("sid-9")


class TestSharedSky:
    def test_together_weathers_merge_with_a_blended_palette(self, tmp_path):
        conf = room(_brain(tmp_path))
        code = conf.propose("a")["code"]
        conf.accept("b", code)
        fa, fb = _beats(conf, "a", "b", 8, sa=0.8, sb=0.8)   # identical states
        merged = [f for f in fa + fb if f.get("mode") == "merged"]
        assert merged, "aligned weathers never merged"
        assert all(f["tg"] >= 72 for f in merged)            # above the threshold
        palettes = [f for f in fa + fb if f.get("t") == "palette"]
        assert palettes and all(c.get("idx") for c in palettes[0]["colors"])

    def test_divergence_splits_with_seam_and_peer_halfsky(self, tmp_path):
        conf = room(_brain(tmp_path))
        code = conf.propose("a")["code"]
        conf.accept("b", code)
        _beats(conf, "a", "b", 6, sa=0.8, sb=0.8)            # merge first
        fa, fb = _beats(conf, "a", "b", 12, sa=0.95, sb=0.05)  # then pull apart
        split = [f for f in fa + fb if f.get("mode") == "split"]
        assert split, "diverging weathers never split"
        f = split[-1]
        assert f["seam_dd"] == -900                          # SEAM_BASE_DEG * 10
        assert 8 <= f["gap_deg"] <= 40                       # widens with divergence
        assert len(f["peer_rgb"]) == 3                       # ready RGB, no math on-glass
        assert all(0 <= v <= 255 for v in f["peer_rgb"])

    def test_stale_peer_fades_to_solo(self, tmp_path):
        clock = {"t": 1000.0}
        conf = LiveConfluence(_brain(tmp_path), now_fn=lambda: clock["t"])
        code = conf.propose("a")["code"]
        conf.accept("b", code)
        _beats(conf, "a", "b", 6)
        conf.weather("a", 0.8, _slots())        # drain b's last queued packet
        clock["t"] += 13.0                                   # > PEER_STALE_S
        frames = conf.weather("a", 0.8, _slots())["frames"]
        assert any(f.get("mode") == "solo" for f in frames)

    def test_incognito_silences_both_directions(self, tmp_path):
        brain = _brain(tmp_path, network_mode="lan_only")    # incognito_now() True
        conf = room(brain)
        code = conf.propose("a")["code"]
        conf.accept("b", code)
        fa, fb = _beats(conf, "a", "b", 6)
        assert fa == [] and fb == []                         # blind and silent

    def test_dissolve_unlinks_and_room_holds_nothing_durable(self, tmp_path):
        brain = _brain(tmp_path)
        conf = room(brain)
        code = conf.propose("a")["code"]
        conf.accept("b", code)
        _beats(conf, "a", "b", 4)
        assert conf.dissolve("a") == {"ok": True}
        assert conf.weather("a", 0.5, _slots())["entangled"] is False
        # nothing confluence-shaped is ever persisted under the brain dir
        import pathlib
        blobs = [p for p in pathlib.Path(brain.cfg_dir).rglob("*")
                 if p.is_file() and "confluence" in p.name.lower()]
        assert blobs == []

    def test_bad_state_is_refused_not_crashed(self, tmp_path):
        conf = room(_brain(tmp_path))
        assert "error" in conf.weather("a", "stormy", _slots())


class TestHttpSurface:
    def test_full_flow_over_the_wire(self, tmp_path):
        brain = _brain(tmp_path)
        server = make_brain_server(brain, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def post(path, body):
            req = urllib.request.Request(
                base + path, data=json.dumps(body).encode(),
                headers={"X-DreamLayer-Token": TOKEN,
                         "Content-Type": "application/json"})
            with opener.open(req, timeout=10) as r:
                return json.loads(r.read())

        try:
            code = post("/dreamlayer/live/confluence/propose",
                        {"sid": "a"})["code"]
            assert post("/dreamlayer/live/confluence/accept",
                        {"sid": "b", "code": code}) == {"ok": True}
            frames = []
            for _ in range(8):
                frames += post("/dreamlayer/live/weather",
                               {"sid": "a", "state": 0.7,
                                "colors": _slots()})["frames"]
                frames += post("/dreamlayer/live/weather",
                               {"sid": "b", "state": 0.7,
                                "colors": _slots()})["frames"]
            assert any(f.get("mode") == "merged" for f in frames)
            assert post("/dreamlayer/live/confluence/dissolve",
                        {"sid": "a"}) == {"ok": True}
        finally:
            server.shutdown(); server.server_close()

    def test_weather_requires_the_token(self, tmp_path):
        brain = _brain(tmp_path)
        server = make_brain_server(brain, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            req = urllib.request.Request(
                base + "/dreamlayer/live/weather",
                data=b'{"sid":"x","state":0.5}',
                headers={"Content-Type": "application/json"})
            try:
                opener.open(req, timeout=10)
                raise AssertionError("unauthenticated weather accepted")
            except urllib.error.HTTPError as e:
                assert e.code == 401
        finally:
            server.shutdown(); server.server_close()


class TestPageShipsConfluence:
    def test_dream_chip_card_and_renderer(self):
        from dreamlayer.ai_brain.server.live import render_live
        page = render_live()
        for n in ('id="confbtn"', 'id="confcard"', "function confBeat",
                  "function drawConfluence", "function confPropose",
                  "function confAccept", "/dreamlayer/live/weather",
                  "seam_dd", "peer_rgb"):
            assert n in page, f"confluence piece missing: {n}"
        # chip lives only in dream mode; card text is built XSS-safe
        assert 'body[data-dream="on"] #confbtn' in page
        card = page.split("function confCard", 1)[1].split("function confHide", 1)[0]
        assert ".innerHTML" not in card
        assert "createElement" in card and ".textContent" in card


class TestRefuteFixes:
    """The confluence refute wave, pinned."""

    def test_double_propose_then_accepting_the_first_code_is_clean(self, tmp_path):
        # refute 2026-07-21: the stale offer survived a re-propose; accepting
        # its code hit BondManager.confirm's KeyError → an unhandled 500.
        conf = room(_brain(tmp_path))
        first = conf.propose("a")["code"]
        conf.propose("a")                                # re-propose replaces
        out = conf.accept("b", first)                    # old code: plain error
        assert "error" in out and "KeyError" not in str(out)
        assert conf.accept("b", conf.propose("a")["code"]) == {"ok": True}

    def test_malformed_colors_never_500_the_peers_beats(self, tmp_path):
        # refute 2026-07-21: one side's garbage slot reached _blend_colors /
        # _slot_rgb through the engine and raised on the PEER's beat.
        conf = room(_brain(tmp_path))
        code = conf.propose("a")["code"]
        conf.accept("b", code)
        for _ in range(8):
            conf.weather("a", 0.8, [{"idx": 1, "y": "stormy", "cb": None}])
            out = conf.weather("b", 0.8, _slots())       # must never raise
            assert "frames" in out

    def test_wrong_code_guessing_is_throttled(self, tmp_path):
        conf = room(_brain(tmp_path))
        conf.propose("a")
        for _ in range(10):
            assert "error" in conf.accept("b", "not-real")
        out = conf.accept("b", "not-real")
        assert "wait a minute" in out["error"]           # the guess window closed

    def test_colliding_codes_refuse_instead_of_bonding_arbitrarily(self, tmp_path):
        clock = {"t": 1000.0}
        conf = LiveConfluence(_brain(tmp_path), now_fn=lambda: clock["t"])
        c1 = conf.propose("a")["code"]
        conf.propose("x")
        conf._offers[next(iter(conf._offers))]  # offers exist
        # force a collision: give x's offer the same code as a's
        for o in conf._offers.values():
            o["code"] = c1
        assert "ambiguous" in conf.accept("b", c1)["error"]

    def test_resync_forces_one_fresh_emit(self, tmp_path):
        conf = room(_brain(tmp_path))
        code = conf.propose("a")["code"]
        conf.accept("b", code)
        _beats(conf, "a", "b", 8)                        # settled: no emits now
        quiet = conf.weather("a", 0.8, _slots())["frames"]
        assert quiet == []                               # EMIT_HYSTERESIS holds
        fresh = conf.weather("a", 0.8, _slots(), resync=True)["frames"]
        assert any(f.get("mode") in ("merged", "split") for f in fresh)
