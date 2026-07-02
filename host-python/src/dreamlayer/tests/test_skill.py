"""test_skill.py — Instant Skill Overlay compiles to a Figment that runs."""
from __future__ import annotations

import pytest

from dreamlayer.reality_compiler.v2 import (
    compile_skill, parse_skill, Step, Stage,
)
from dreamlayer.reality_compiler.v2.figment import END, MAX_TEXT_LEN, MAX_SCENES


PASTA = """
1. Salt the boiling water
2. Boil for 8 minutes
3. Drain and plate
"""


class TestParse:
    def test_numbered_list_becomes_steps(self):
        steps = parse_skill(PASTA)
        assert [s.text for s in steps] == [
            "Salt the boiling water", "Boil for 8 minutes", "Drain and plate"]

    def test_duration_in_a_line_becomes_a_timer(self):
        steps = parse_skill(PASTA)
        assert steps[0].hold_sec is None            # no time named
        assert steps[1].hold_sec == 8 * 60          # "8 minutes"
        assert steps[2].hold_sec is None

    def test_bullets_and_seconds(self):
        steps = parse_skill("- rest 30s\n* go")
        assert steps[0].hold_sec == 30
        assert steps[1].text == "go"

    def test_blank_lines_ignored(self):
        assert len(parse_skill("\n\n  \nonly one\n")) == 1


class TestCompile:
    def test_scene_per_step_and_budget_ok(self):
        fig, report = compile_skill("Pasta", parse_skill(PASTA))
        assert len(fig.scenes) == 3
        assert fig.initial == "s0"
        assert report.ok, str(report)

    def test_lines_fit_the_display(self):
        long_step = "This is a deliberately very long instruction that must wrap"
        fig, _ = compile_skill("Long", [Step(long_step)])
        for line in fig.scenes["s0"].lines:
            assert len(line.content) <= MAX_TEXT_LEN

    def test_empty_rejected(self):
        with pytest.raises(ValueError):
            compile_skill("Nope", [])

    def test_too_many_steps_rejected(self):
        with pytest.raises(ValueError):
            compile_skill("Huge", [Step(f"step {i}") for i in range(MAX_SCENES + 1)])


class TestRun:
    def test_tap_advances_through_the_steps(self):
        fig, _ = compile_skill("Pasta", parse_skill(PASTA))
        st = Stage(fig)
        assert st.frame().scene == "s0"
        assert st.counters["step"] == 1
        assert st.inject("single") is True
        assert st.frame().scene == "s1"
        assert st.counters["step"] == 2
        st.inject("single")                          # -> s2 (last)
        assert st.frame().scene == "s2"
        st.inject("single")                          # -> @end
        assert st.frame().ended is True

    def test_timed_step_advances_itself_hands_free(self):
        fig, _ = compile_skill("Pasta", parse_skill(PASTA))
        st = Stage(fig)
        st.inject("single")                          # -> s1, the 8-min boil
        assert st.frame().scene == "s1"
        st.step(8 * 60)                              # the clock advances it
        assert st.frame().scene == "s2"
        assert st.counters["step"] == 3

    def test_tap_skips_a_timed_step_early(self):
        fig, _ = compile_skill("Pasta", parse_skill(PASTA))
        st = Stage(fig)
        st.inject("single")                          # -> s1 (timed)
        st.step(5)                                   # nowhere near 8 min
        assert st.frame().scene == "s1"
        st.inject("single")                          # skip early
        assert st.frame().scene == "s2"

    def test_long_press_bails_out(self):
        fig, _ = compile_skill("Pasta", parse_skill(PASTA))
        st = Stage(fig)
        st.inject("single")                          # somewhere in the middle
        assert st.inject("long") is True
        assert st.frame().scene == END
        assert st.frame().ended is True

    def test_non_timed_step_waits_for_the_tap(self):
        fig, _ = compile_skill("Pasta", parse_skill(PASTA))
        st = Stage(fig)                              # s0 is untimed
        st.step(3600)                                # an hour passes
        assert st.frame().scene == "s0"              # still waiting on you
