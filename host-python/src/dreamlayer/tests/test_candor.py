"""test_candor.py — Candor Mirror, the inward self-coach (INNOVATION_SESSION 2.7).

Pins the two registers: the live pace arc (WPM → amp, the sustained-rush notice,
fillers hidden until peek) and the after-the-fact debrief (WPM with a trend
arrow, top fillers, folded-in narrative drift), plus the veil silencing both and
the orchestrator wiring.
"""
from __future__ import annotations

from dreamlayer.orchestrator.candor import CandorMirror, FAST_WPM


class Veil:
    def __init__(self, allow=True):
        self.allow = allow
    def allow_capture(self):
        return self.allow


def _words(n: int) -> str:
    return " ".join(["word"] * n)


# -- the live register --------------------------------------------------------

class TestLive:
    def test_amp_rises_with_pace_and_is_bounded(self):
        c = CandorMirror()
        # a calm 90-wpm stretch → arc near the bottom
        c.observe(_words(30), now=0.0)
        c.observe(_words(15), now=20.0)   # 45 words over 20s = 135 wpm-ish
        amp = c.amp(now=20.0)
        assert 0 <= amp <= 99

    def test_sustained_rush_trips_the_notice(self):
        c = CandorMirror()
        c.observe(_words(120), now=0.0)   # a fast burst
        assert c.live_wpm(now=2.0) > FAST_WPM
        assert c.notice(now=2.0) is True

    def test_calm_does_not_trip_the_notice(self):
        c = CandorMirror()
        c.observe(_words(30), now=0.0)
        c.observe(_words(30), now=30.0)   # 60 words / 30s = 120 wpm
        assert c.notice(now=30.0) is False

    def test_window_forgets_old_speech(self):
        c = CandorMirror()
        c.observe(_words(100), now=0.0)   # long ago
        c.observe(_words(10), now=100.0)  # only this is in the 30s window
        assert sum(w for _, w in c._window) == 10

    def test_live_frame_carries_fillers_for_peek(self):
        c = CandorMirror()
        c.observe("um so basically, um you know it works", now=0.0)
        frame = c.live_frame(now=1.0)
        assert frame is not None and frame["fillers"] >= 3   # um, um, basically, you know


# -- the post-mortem ----------------------------------------------------------

class TestDebrief:
    def test_debrief_reports_pace_and_top_fillers(self):
        c = CandorMirror()
        # 150 words across 60s → 150 wpm
        c.observe("um " + _words(74), now=0.0)
        c.observe("um you know " + _words(73), now=60.0)
        card = c.post_mortem()
        assert card["type"] == "CandorCard"
        assert 140 <= card["wpm"] <= 160
        assert "um" in card["fillers"]                        # the commonest filler shows

    def test_trend_arrow_across_sessions(self):
        c = CandorMirror()
        c.observe(_words(100), now=0.0); c.observe(_words(0) or "x", now=60.0)
        first = c.post_mortem()
        assert first["trend"] == ""                           # no history yet
        c.reset()
        # a much faster second session
        c.observe(_words(200), now=0.0); c.observe("x", now=60.0)
        second = c.post_mortem()
        assert second["trend"] == "↑"

    def test_drift_line_is_folded_in_not_invented(self):
        c = CandorMirror()
        c.observe(_words(40), now=0.0)
        plain = c.post_mortem()
        assert plain["drift"] == ""                           # nothing invented
        c.reset(); c.observe(_words(40), now=0.0)
        withdrift = c.post_mortem(drift="you told it differently on Tuesday")
        assert "Tuesday" in withdrift["drift"]
        assert any("Tuesday" in ln for ln in withdrift["lines"])

    def test_nothing_heard_no_card(self):
        assert CandorMirror().post_mortem() is None


# -- privacy ------------------------------------------------------------------

class TestVeil:
    def test_veil_silences_intake_and_output(self):
        c = CandorMirror(privacy=Veil(False))
        c.observe(_words(100), now=0.0)
        assert c.live_frame(now=1.0) is None
        assert c.post_mortem() is None
        assert c.filler_total() == 0                          # learned nothing


# -- orchestrator wiring ------------------------------------------------------

class TestOrchestrator:
    def _orch(self):
        from dreamlayer.orchestrator.orchestrator import Orchestrator
        from dreamlayer.tests.test_integration_dream_suite import FakeBridge
        return Orchestrator(FakeBridge())

    def test_candor_hear_then_debrief_sends_a_card(self):
        orc = self._orch()
        orc.candor_hear("um so basically we shipped it", now=0.0)
        orc.candor_hear("um you know it works now", now=30.0)
        card = orc.candor_debrief()
        assert card is not None and card["type"] == "CandorCard"

    def test_veil_yields_nothing(self):
        orc = self._orch()
        orc.privacy.pause()                 # raise the capture veil
        assert orc.candor_hear("um rushing now", now=0.0) is None
        assert orc.candor_debrief() is None
