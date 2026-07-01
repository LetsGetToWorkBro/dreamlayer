"""Backward compat: all 15 v1 intents lift, verify, and behave."""
import pytest

from dreamlayer.reality_compiler.v2 import (
    lift, verify, Stage, run_through, RealityCompilerV2, ALL_V1_TYPES,
)
# TODO(rename): dreamlayer.reality_compiler.schema after rename PR lands
from memoscape.reality_compiler.schema import (
    RoundTimerIntent, OvertimeTimerIntent, StopwatchIntent,
    IntervalTimerIntent, SimpleCounterIntent, BatteryWarningIntent,
    TeleprompterIntent, CoachingCueIntent, PointsMarkerIntent,
    NextClassIntent, TextSubtitlesIntent, HabitReminderIntent,
    ReactTimerIntent, GestureRepeaterIntent, SpeakerIndicatorIntent,
)

ALL_INTENTS = [
    RoundTimerIntent(), OvertimeTimerIntent(), StopwatchIntent(),
    IntervalTimerIntent(), SimpleCounterIntent(), BatteryWarningIntent(),
    TeleprompterIntent(), CoachingCueIntent(), PointsMarkerIntent(),
    NextClassIntent(), TextSubtitlesIntent(), HabitReminderIntent(),
    ReactTimerIntent(), GestureRepeaterIntent(), SpeakerIndicatorIntent(),
]


class TestAllFifteen:
    def test_registry_covers_all_v1_types(self):
        assert len(ALL_V1_TYPES) == 15

    @pytest.mark.parametrize("intent", ALL_INTENTS,
                             ids=[i.type for i in ALL_INTENTS])
    def test_lift_verifies(self, intent):
        fig = lift(intent)
        report = verify(fig)
        assert report.ok, str(report)
        assert fig.meta["v1_type"] == intent.type

    @pytest.mark.parametrize("intent", ALL_INTENTS,
                             ids=[i.type for i in ALL_INTENTS])
    def test_lift_runs_through(self, intent):
        assert len(run_through(lift(intent))) >= 1


class TestSemanticEquivalence:
    """The lift preserves what v1 actually did."""

    def test_round_timer_duration_and_trigger(self):
        fig = lift(RoundTimerIntent(duration_sec=180, overtime_sec=20,
                                    warning_start_sec=10))
        st = Stage(fig)
        st.inject("double")
        assert st.current == "round"
        st.step(180)
        assert st.current == "overtime"          # v1: OT phase follows
        st.step(20)
        assert st.current == "over"

    def test_round_timer_trigger_stops(self):
        fig = lift(RoundTimerIntent())
        st = Stage(fig)
        st.inject("double")
        st.step(5)
        st.inject("double")
        assert st.current == "armed"             # v1: same trigger stops

    def test_interval_rounds_count(self):
        fig = lift(IntervalTimerIntent(work_sec=45, rest_sec=15, rounds=8))
        st = Stage(fig)
        st.inject("double")
        st.step(8 * 60 - 1)                      # 8×(45+15) − 1
        assert st.current == "rest" and st.counters["round"] == 8
        st.step(1)
        assert st.current == "done"

    def test_counter_increment_and_reset(self):
        fig = lift(SimpleCounterIntent(start_value=5, increment=2))
        st = Stage(fig)
        st.inject("single"); st.inject("single")
        assert st.counters["tally"] == 9
        st.inject("long")
        assert st.counters["tally"] == 5

    def test_battery_warning_threshold(self):
        fig = lift(BatteryWarningIntent(threshold_pct=15))
        st = Stage(fig, battery_level=10)
        st.step(1)
        assert any("LOW BATTERY" in ln.text for ln in st.frame().lines)

    def test_coaching_cue_map(self):
        fig = lift(CoachingCueIntent())
        st = Stage(fig)
        st.inject("ble:2")
        assert st.frame().lines[0].text == "DEFEND"
        st.step(3.0)
        assert st.current == "ready"

    def test_points_marker_emits_to_host(self):
        fig = lift(PointsMarkerIntent(send_to_host=True))
        st = Stage(fig)
        st.inject("single")
        assert st.emits[0][1] == "point"
        st.inject("long")
        assert st.counters["points"] == 0        # undo

    def test_stopwatch_toggle(self):
        fig = lift(StopwatchIntent())
        st = Stage(fig)
        st.inject("single")                      # arm → running
        st.step(12)
        st.inject("single")                      # stop, frozen
        st.step(30)
        assert st.frame().lines[1].text == "12"

    def test_speaker_indicator_shows_name(self):
        fig = lift(SpeakerIndicatorIntent())
        st = Stage(fig)
        st.inject("text", "Maya")
        assert st.frame().lines[0].text == "Maya"

    def test_react_timer_measures_reaction(self):
        import random
        fig = lift(ReactTimerIntent(min_delay_ms=1000, max_delay_ms=4000))
        st = Stage(fig, rng=random.Random(3))
        delay = random.Random(3).uniform(1.0, 4.0)   # same seed, same draw
        st.inject("single")                      # arm → get ready
        st.step(delay)                           # GO! appears exactly now
        assert st.current == "go"
        st.step(0.35)                            # user reacts in 350 ms
        st.inject("single")
        assert st.frame().lines[0].text == "350 ms"


class TestV1TextSurface:
    """v1's plain-English phrasings keep working through compile_text."""

    @pytest.mark.parametrize("text,v1_type", [
        ("3 minute round timer with 20 seconds overtime", "round_timer"),
        ("45 seconds work 15 seconds rest 8 rounds interval", "interval_timer"),
        ("stopwatch", "stopwatch"),
        ("battery warning at 15%", "battery_warning"),
        ("simple counter", "simple_counter"),
    ])
    def test_v1_phrasings(self, text, v1_type, tmp_path):
        rc = RealityCompilerV2(vault_dir=tmp_path)
        res = rc.compile_text(text)
        assert res.ok
        assert res.figment.meta["v1_type"] == v1_type

    def test_unknown_text_still_raises_like_v1(self, tmp_path):
        rc = RealityCompilerV2(vault_dir=tmp_path)
        with pytest.raises(ValueError, match="Cannot parse intent"):
            rc.compile_text("make me a sandwich")

    def test_superset_the_five_v1_never_shipped(self):
        # these five had no template in v1's library — get() raised KeyError
        # TODO(rename): dreamlayer.reality_compiler.template_library after rename PR lands
        from memoscape.reality_compiler.template_library import get
        for intent in (OvertimeTimerIntent(), NextClassIntent(),
                       TextSubtitlesIntent(), GestureRepeaterIntent(),
                       SpeakerIndicatorIntent()):
            with pytest.raises(KeyError):
                get(intent.type)
            assert verify(lift(intent)).ok       # v2 lifts them anyway
