"""Reference interpreter semantics — the contract the Lua stage mirrors."""
import random

from dreamlayer.reality_compiler.v2 import (
    Figment, Scene, TextLine, PulseSpec, CounterDecl, CounterOp,
    Guard, Transition, END, SELF, Stage,
)


def timer_fig(duration=10.0, pulse_window=0.0) -> Figment:
    fig = Figment(name="t", initial="armed")
    armed = fig.add_scene(Scene(id="armed", lines=[
        TextLine("READY", row=1)]))
    armed.on["double"] = Transition(target="run")
    fig.add_scene(Scene(
        id="run", duration_sec=duration, tick="countdown",
        lines=[TextLine("{remaining}", row=1)],
        pulse=(PulseSpec(window_sec=pulse_window, rate_hz=2.0)
               if pulse_window else None),
        on_timeout=[Transition(target=END)],
    ))
    return fig


class TestTimeAndTransitions:
    def test_waits_for_trigger(self):
        st = Stage(timer_fig())
        st.step(100)
        assert st.current == "armed" and not st.ended

    def test_trigger_starts(self):
        st = Stage(timer_fig())
        assert st.inject("double")
        assert st.current == "run"

    def test_countdown_renders(self):
        st = Stage(timer_fig(duration=10))
        st.inject("double")
        st.step(3)
        assert st.frame().lines[0].text == "7"

    def test_clock_format_mmss(self):
        st = Stage(timer_fig(duration=180))
        st.inject("double")
        st.step(1)
        assert st.frame().lines[0].text == "2:59"

    def test_timeout_ends(self):
        st = Stage(timer_fig(duration=10))
        st.inject("double")
        st.step(10)
        assert st.ended

    def test_step_crosses_multiple_scenes(self):
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="a", duration_sec=2.0, lines=[],
                            on_timeout=[Transition(target="b")]))
        fig.add_scene(Scene(id="b", duration_sec=2.0, lines=[],
                            on_timeout=[Transition(target=END)]))
        st = Stage(fig)
        st.step(3.0)          # one call, lands 1 s into scene b
        assert st.current == "b"
        assert abs(st.scene_elapsed - 1.0) < 1e-6

    def test_unhandled_event_ignored(self):
        st = Stage(timer_fig())
        assert not st.inject("single")
        assert st.current == "armed"


class TestCountersAndGuards:
    def make(self, rounds=3) -> Figment:
        fig = Figment(name="t", initial="work")
        fig.add_counter(CounterDecl("round", start=1, lo=1, hi=rounds))
        fig.add_scene(Scene(
            id="work", duration_sec=1.0,
            lines=[TextLine("{count:round}", row=1)],
            on_timeout=[
                Transition(target=END, when=Guard("round", "ge", rounds)),
                Transition(target=SELF,
                           counter_ops=[CounterOp("round", "inc", 1)]),
            ]))
        return fig

    def test_guarded_loop_terminates(self):
        st = Stage(self.make(rounds=3))
        st.step(10)
        assert st.ended
        assert st.counters["round"] == 3

    def test_counters_saturate(self):
        fig = Figment(name="t", initial="a")
        fig.add_counter(CounterDecl("n", start=0, lo=0, hi=5))
        scene = fig.add_scene(Scene(id="a", lines=[]))
        scene.on["single"] = Transition(
            target=SELF, counter_ops=[CounterOp("n", "inc", 3)])
        st = Stage(fig)
        for _ in range(10):
            st.inject("single")
        assert st.counters["n"] == 5     # saturated, no overflow

    def test_token_replacement(self):
        st = Stage(self.make())
        assert st.frame().lines[0].text == "1"


class TestEmitBudget:
    def test_event_flood_clamped_by_token_bucket(self):
        fig = Figment(name="t", initial="a")
        scene = fig.add_scene(Scene(id="a", lines=[]))
        scene.on["single"] = Transition(target=SELF, emit="tap")
        st = Stage(fig)
        for _ in range(20):                 # 20 taps in zero time
            st.inject("single")
        assert len(st.emits) == 5           # burst capacity
        assert st.dropped_emits == 15       # flood never reaches BLE

    def test_bucket_refills_with_time(self):
        fig = Figment(name="t", initial="a")
        scene = fig.add_scene(Scene(id="a", lines=[]))
        scene.on["single"] = Transition(target=SELF, emit="tap")
        st = Stage(fig)
        for _ in range(5):
            st.inject("single")
        st.step(2.0)
        st.inject("single")
        assert len(st.emits) == 6


class TestPulse:
    def test_no_pulse_outside_window(self):
        st = Stage(timer_fig(duration=20, pulse_window=5))
        st.inject("double")
        st.step(5)
        assert not st.frame().pulse_on

    def test_pulse_inside_window(self):
        st = Stage(timer_fig(duration=20, pulse_window=5))
        st.inject("double")
        st.step(16)
        states = set()
        for _ in range(4):
            states.add(st.frame().pulse_on)
            st.step(0.25)
        assert states == {True, False}      # it breathes, on and off


class TestElapsedFreezing:
    def test_stopwatch_freeze(self):
        fig = Figment(name="t", initial="run")
        run = fig.add_scene(Scene(id="run", tick="countup",
                                  lines=[TextLine("{elapsed}", row=1)]))
        stop = fig.add_scene(Scene(id="stop",
                                   lines=[TextLine("{elapsed}", row=1)]))
        run.on["single"] = Transition(target="stop")
        stop.on["single"] = Transition(target="run")
        st = Stage(fig)
        st.step(7)
        st.inject("single")
        st.step(100)                         # frozen while stopped
        assert st.frame().lines[0].text == "7"


class TestBattery:
    def make(self) -> Figment:
        fig = Figment(name="t", initial="watch", battery_below=20)
        watch = fig.add_scene(Scene(id="watch", lines=[]))
        watch.on["battery_low"] = Transition(target="warn")
        fig.add_scene(Scene(id="warn", duration_sec=3.0,
                            lines=[TextLine("LOW", row=1)],
                            on_timeout=[Transition(target="watch")]))
        return fig

    def test_fires_below_threshold(self):
        st = Stage(self.make(), battery_level=10)
        st.step(1)
        assert st.current == "warn"

    def test_quiet_above_threshold(self):
        st = Stage(self.make(), battery_level=80)
        st.step(100)
        assert st.current == "watch"

    def test_cooldown_prevents_spam(self):
        st = Stage(self.make(), battery_level=10)
        st.step(1)          # warn
        st.step(3)          # back to watch
        st.step(10)         # cooldown holds — no immediate re-warn
        assert st.current == "watch"


class TestHotSwapRevoke:
    def test_swap_replaces_between_ticks(self):
        st = Stage(timer_fig())
        st.inject("double")
        other = Figment(name="other", initial="only")
        other.add_scene(Scene(id="only", lines=[TextLine("SWAPPED", row=1)]))
        st.swap(other)
        assert st.frame().lines[0].text == "SWAPPED"
        assert not st.ended

    def test_revoke_stops(self):
        st = Stage(timer_fig())
        st.inject("double")
        st.revoke()
        assert st.ended
        assert st.frame().ended


class TestRandomDuration:
    def test_seeded_reproducible(self):
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="a", duration_range=(1.0, 4.0), lines=[],
                            on_timeout=[Transition(target=END)]))
        a = Stage(fig, rng=random.Random(42))
        b = Stage(fig, rng=random.Random(42))
        assert a._duration == b._duration
        assert 1.0 <= a._duration <= 4.0
