"""The audible memory palace (hud/spatial_audio.py): recall as positioned sound.

The tests measure the *physics* of the rendered audio — onset delay between
ears, energy ratios, spectral tilt — rather than eyeballing arrays, and pin the
binaural parameters to the psychoacoustics they claim (Woodworth ITD ≈ 0.66 ms
at 90°, ILD sign, equal-power pan). Then the wiring: a Waypath cue with
geometry rides its spatial payload on the HUD card; a place-only anchor
doesn't pretend to have a direction."""
import math

import numpy as np
import pytest

from dreamlayer.hud import spatial_audio as sa


class TestSpatialize:
    def test_dead_ahead_is_centered(self):
        p = sa.spatialize(0.0, 2.0)
        assert p.pan == 0.0 and p.itd_s == 0.0 and p.ild_db == 0.0
        assert not p.behind

    def test_hard_right_is_textbook(self):
        p = sa.spatialize(90.0, 1.0)
        assert p.pan == pytest.approx(1.0)
        assert p.ild_db == pytest.approx(sa.MAX_ILD_DB)
        # Woodworth at 90°: r/c * (1 + π/2) ≈ 0.656 ms, left ear delayed
        expect = sa.HEAD_RADIUS_M / sa.SPEED_OF_SOUND * (1 + math.pi / 2)
        assert p.itd_s == pytest.approx(expect, rel=1e-6)
        assert p.itd_s > 0

    def test_left_mirrors_right(self):
        r, l = sa.spatialize(90.0, 3.0), sa.spatialize(-90.0, 3.0)
        assert l.pan == -r.pan and l.ild_db == -r.ild_db
        assert l.itd_s == pytest.approx(-r.itd_s)

    def test_behind_flag_and_folded_lateral(self):
        # 150° behind-right carries the same lateral cues as its 30° mirror
        front, back = sa.spatialize(30.0, 2.0), sa.spatialize(150.0, 2.0)
        assert not front.behind and back.behind
        assert back.pan == pytest.approx(front.pan)
        assert back.itd_s == pytest.approx(front.itd_s, rel=1e-6)

    def test_azimuth_normalizes(self):
        assert sa.spatialize(270.0, 1.0).azimuth_deg == -90.0
        assert sa.spatialize(-450.0, 1.0).azimuth_deg == -90.0

    def test_distance_gain_monotonic_with_floor(self):
        gains = [sa.spatialize(0, d).gain for d in (0.5, 1, 2, 5, 11, 50)]
        assert gains[0] == gains[1] == 1.0            # inside reference: full
        assert all(a >= b for a, b in zip(gains, gains[1:]))
        assert gains[-1] == sa.MIN_GAIN               # far: floored, not silent


class TestRenderStereo:
    def _onset(self, ch, thresh=1e-4):
        idx = np.nonzero(np.abs(ch) > thresh)[0]
        return int(idx[0]) if len(idx) else -1

    def test_right_source_is_louder_and_earlier_on_the_right(self):
        # 60 deg, not 90: at hard right equal-power zeroes the far ear entirely
        # (correct behavior), so measure ILD at 90 but ITD by cross-correlating
        # the two ears at 60, where both carry the same scaled waveform
        sr = 22050
        hard = sa.render_stereo(sa.cue_tone(sr), sr, sa.spatialize(90.0, 1.0))
        assert float(np.sum(hard[:, 1]**2)) > 4.0 * float(np.sum(hard[:, 0]**2))
        params = sa.spatialize(60.0, 1.0)
        out = sa.render_stereo(sa.cue_tone(sr), sr, params)
        L, R = out[:, 0], out[:, 1]
        assert float(np.sum(R**2)) > float(np.sum(L**2))          # ILD
        xc = np.correlate(L, R, mode="full")                       # ITD as lag
        lag = int(np.argmax(xc)) - (len(R) - 1)
        assert lag == round(params.itd_s * sr)                     # left delayed

    def test_center_source_is_symmetric(self):
        sr = 22050
        out = sa.render_stereo(sa.cue_tone(sr), sr, sa.spatialize(0.0, 1.0))
        assert float(np.sum(out[:, 0] ** 2)) == pytest.approx(
            float(np.sum(out[:, 1] ** 2)), rel=1e-4)
        assert self._onset(out[:, 0]) == self._onset(out[:, 1])

    def test_behind_source_is_darker(self):
        # the rear low-pass removes high-frequency energy relative to front
        sr = 22050
        tone = sa.cue_tone(sr, hz=4000.0)             # above the rear cutoff
        front = sa.render_stereo(tone, sr, sa.spatialize(30.0, 1.0))
        back = sa.render_stereo(tone, sr, sa.spatialize(150.0, 1.0))
        assert float(np.sum(back**2)) < 0.5 * float(np.sum(front**2))

    def test_distance_attenuates_energy(self):
        sr = 22050
        tone = sa.cue_tone(sr)
        near = sa.render_stereo(tone, sr, sa.spatialize(45.0, 1.0))
        far = sa.render_stereo(tone, sr, sa.spatialize(45.0, 10.0))
        assert float(np.sum(far**2)) < float(np.sum(near**2))

    def test_render_is_deterministic(self):
        sr = 22050
        a = sa.render_stereo(sa.cue_tone(sr), sr, sa.spatialize(60.0, 3.0))
        b = sa.render_stereo(sa.cue_tone(sr), sr, sa.spatialize(60.0, 3.0))
        assert np.array_equal(a, b)


class TestPayloadAndWiring:
    def test_payload_shape(self):
        p = sa.spatial_payload(90.0, 11.0)
        assert set(p) == {"azimuth_deg", "distance_m", "pan", "gain",
                          "itd_s", "ild_db", "behind"}
        assert p["behind"] is False and -1 <= p["pan"] <= 1

    def test_waypath_card_carries_spatial_for_bearing_anchor(self):
        from dreamlayer.orchestrator.waypath import WaypathLens
        lens = WaypathLens()
        lens.remember("bike", bearing_deg=120.0, distance_m=11.0,
                      place="north rack")
        cue = lens.locate("bike", heading_deg=30.0)   # rel bearing = 90 (right)
        assert cue.rel_bearing_deg == pytest.approx(90.0)
        card = lens.to_hud_card(cue)
        assert card["bearing_deg"] == pytest.approx(90.0)
        assert card["spatial"]["pan"] == pytest.approx(1.0)
        assert card["spatial"]["distance_m"] == 11.0

    def test_place_only_anchor_has_no_spatial(self):
        from dreamlayer.orchestrator.waypath import WaypathLens
        lens = WaypathLens()
        lens.remember("passport", place="top drawer")
        card = lens.to_hud_card(lens.locate("passport"))
        assert "spatial" not in card and card["bearing_deg"] is None

    def test_steam_seam_degrades_honestly(self):
        r = sa.SteamAudioRenderer()
        if not r.available:
            with pytest.raises(RuntimeError):
                r.render(sa.cue_tone(), 22050, sa.spatialize(0, 1))
