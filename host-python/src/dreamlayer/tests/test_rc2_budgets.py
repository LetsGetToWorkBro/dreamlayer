"""Budget verification: the constraint envelope, with negative cases."""
from dreamlayer.reality_compiler.v2 import (
    Figment, Scene, TextLine, PulseSpec, CounterDecl, CounterOp,
    Guard, Transition, END, SELF, verify,
)


def minimal(duration=10.0) -> Figment:
    fig = Figment(name="t", initial="a")
    fig.add_scene(Scene(id="a", duration_sec=duration,
                        lines=[TextLine("hi", row=1)],
                        on_timeout=[Transition(target=END)]))
    return fig


def codes(fig) -> set[str]:
    return {v.code for v in verify(fig).violations}


class TestStructural:
    def test_minimal_passes(self):
        assert verify(minimal()).ok

    def test_empty_figment(self):
        assert "empty" in codes(Figment(name="t", initial="a"))

    def test_missing_initial(self):
        fig = Figment(name="t", initial="nope")
        fig.add_scene(Scene(id="a", lines=[]))
        assert "initial" in codes(fig)

    def test_scene_cap(self):
        fig = Figment(name="t", initial="s0")
        for i in range(33):
            fig.add_scene(Scene(id=f"s{i}", duration_sec=1.0,
                                on_timeout=[Transition(target=END)]))
        assert "scene_count" in codes(fig)

    def test_unknown_target(self):
        fig = minimal()
        fig.scenes["a"].on["single"] = Transition(target="ghost")
        assert "target" in codes(fig)

    def test_unknown_event(self):
        fig = minimal()
        fig.scenes["a"].on["telepathy"] = Transition(target=END)
        assert "event" in codes(fig)

    def test_ble_byte_events_are_valid(self):
        fig = minimal()
        fig.scenes["a"].on["ble:3"] = Transition(target=END)
        assert verify(fig).ok

    def test_color_whitelist(self):
        fig = minimal()
        fig.scenes["a"].lines[0].color = "#FF0000"   # raw hex is not a token
        assert "color" in codes(fig)

    def test_text_length_cap(self):
        fig = minimal()
        fig.scenes["a"].lines[0].content = "x" * 25
        assert "text_len" in codes(fig)

    def test_line_cap(self):
        fig = minimal()
        fig.scenes["a"].lines = [TextLine("x", row=r) for r in range(5)]
        assert verify(fig).ok
        fig.scenes["a"].lines.append(TextLine("y", row=0))
        assert "lines" in codes(fig)

    def test_undeclared_counter(self):
        fig = minimal()
        fig.scenes["a"].on_timeout = [
            Transition(target=END, counter_ops=[CounterOp("ghost")])]
        assert "counter" in codes(fig)

    def test_guard_only_on_timeout(self):
        fig = minimal()
        fig.add_counter(CounterDecl("n"))
        fig.scenes["a"].on["single"] = Transition(
            target=END, when=Guard("n", "ge", 1))
        assert "guard" in codes(fig)

    def test_last_timeout_branch_must_be_default(self):
        fig = minimal()
        fig.add_counter(CounterDecl("n"))
        fig.scenes["a"].on_timeout = [
            Transition(target=END, when=Guard("n", "ge", 1))]
        assert "branches" in codes(fig)


class TestTemporal:
    def test_sub_breath_duration_rejected(self):
        assert "duration" in codes(minimal(duration=0.2))

    def test_timed_scene_needs_timeout(self):
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="a", duration_sec=5.0, lines=[]))
        assert "timeout" in codes(fig)

    def test_timeout_needs_duration(self):
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="a", lines=[],
                            on_timeout=[Transition(target=END)]))
        assert "timeout" in codes(fig)

    def test_countdown_tick_needs_duration(self):
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="a", tick="countdown", lines=[]))
        assert "tick" in codes(fig)


class TestDisplayBudget:
    def test_pulse_rate_cap(self):
        fig = minimal()
        fig.scenes["a"].pulse = PulseSpec(window_sec=5, rate_hz=30.0)
        assert "pulse_rate" in codes(fig)

    def test_pulse_window_must_fit(self):
        fig = minimal(duration=5.0)
        fig.scenes["a"].pulse = PulseSpec(window_sec=10, rate_hz=2.0)
        assert "pulse" in codes(fig)

    def test_legal_pulse_passes(self):
        fig = minimal(duration=60.0)
        fig.scenes["a"].pulse = PulseSpec(window_sec=10, rate_hz=2.0)
        report = verify(fig)
        assert report.ok
        assert report.worst_display_hz == 2.0


class TestBleBudget:
    def _cycle(self, secs_a: float, emit_a: bool,
               secs_b: float = 0.0, emit_b: bool = False) -> Figment:
        fig = Figment(name="t", initial="a")
        two = secs_b > 0
        fig.add_scene(Scene(
            id="a", duration_sec=secs_a, lines=[],
            on_timeout=[Transition(target="b" if two else SELF,
                                   emit="x" if emit_a else None)]))
        if two:
            fig.add_scene(Scene(
                id="b", duration_sec=secs_b, lines=[],
                on_timeout=[Transition(target="a",
                                       emit="y" if emit_b else None)]))
        return fig

    def test_self_loop_flood_rejected(self):
        # emit every 0.5 s = 2/s > 1/s budget
        assert "ble_flood" in codes(self._cycle(0.5, True))

    def test_self_loop_within_budget(self):
        report = verify(self._cycle(2.0, True))
        assert report.ok
        assert report.worst_emit_per_sec == 0.5

    def test_two_scene_cycle_flood(self):
        # two emits around a 1.5 s cycle = 1.33/s
        assert "ble_flood" in codes(self._cycle(0.5, True, 1.0, True))

    def test_two_scene_cycle_ok(self):
        assert verify(self._cycle(1.0, True, 1.0, False)).ok

    def test_event_emits_not_flagged_statically(self):
        # event-triggered emits consume external events; the runtime
        # token bucket clamps them (tested in test_rc2_interpreter)
        fig = minimal()
        fig.scenes["a"].on["single"] = Transition(target=SELF, emit="tap")
        assert verify(fig).ok


class TestWarnings:
    def test_unreachable_scene_warns(self):
        fig = minimal()
        fig.add_scene(Scene(id="island", lines=[]))
        report = verify(fig)
        assert report.ok
        assert any(w.code == "unreachable" for w in report.warnings)

    def test_beat_provenance_carried(self):
        fig = minimal()
        fig.scenes["a"].pulse = PulseSpec(window_sec=5, rate_hz=30.0)
        fig.meta["scene_beats"] = {"a": 2}
        report = verify(fig)
        assert report.violations[0].beat == 2
