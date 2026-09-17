"""The safety core's reports say their verdict in words, and nothing read them.

Found 2026-09-17, by mutmut 3.8.0 widening its net: its changelog entry "Fix
methods of decorated classes (for example ``@dataclass``) not being mutated"
(#480/#539) made ``__str__`` on ``FlashReport``, ``BudgetReport`` and
``Violation`` mutable for the first time. Seventeen new mutants appeared, seven
of them ``no tests`` — mutmut's way of saying no selected test ever executes
that line.

The reason is the shape this repository keeps meeting (CLAUDE.md #1), in a new
disguise. ``test_flash_safety.py`` contains, and has always contained:

    assert isinstance(rep, FlashReport) and rep.ok, str(rep)

which reads exactly like coverage of ``__str__``. It is not: Python evaluates
an assert's message **only when the assertion fails**, so on every green run
that ``str(rep)`` was never called. The one apparent reader of these methods
was a reader that never ran.

What that left unguarded is not cosmetic. ``FlashReport.__str__`` renders

    "FLASH-SAFE" if self.ok else "FLASH RISK"

— the eye-safety verdict, in the words a human actually reads — and a mutant
that inverts it prints FLASH-SAFE over a figment the analyzer rejected.
``BudgetReport.__str__`` has the same conditional head plus the lines that
enumerate the violations, so a mutant dropping them prints a violated report
as a clean one.

These tests execute the three ``__str__`` methods for real and assert both
directions of every verdict, so the mutants die and the text keeps meaning what
it says. They only count because ``test_report_strings.py`` is listed in
``[tool.mutmut] pytest_add_cli_args_test_selection``: a killer suite mutmut is
not told to run cannot kill anything.
"""
from __future__ import annotations

from dreamlayer.reality_compiler.v2.budgets import BudgetReport, Violation
from dreamlayer.reality_compiler.v2.flash_safety import FLASH_LIMIT, FlashReport


class TestTheFlashVerdictReadsCorrectly:
    """``FlashReport.__str__`` is what a human is shown for an eye-safety
    call. Both heads are asserted, and each excludes the other: an inverted
    conditional has to fail one of them."""

    def test_a_safe_report_says_safe_and_never_says_risk(self):
        text = str(FlashReport(ok=True, general_hz=1.0, red_hz=0.5))
        # `startswith`, not `in`: an `in` check passes on a head mutmut has
        # wrapped to "[XXFLASH-SAFEXX]", which is not a verdict anyone can
        # read. The head is the one token this whole report exists to carry,
        # so it is pinned exactly.
        assert text.startswith("[FLASH-SAFE]")
        assert "RISK" not in text

    def test_an_unsafe_report_says_risk_and_never_says_safe(self):
        text = str(FlashReport(ok=False, general_hz=9.0, red_hz=4.0))
        assert text.startswith("[FLASH RISK]")
        assert "SAFE" not in text

    def test_it_reports_the_rates_it_measured_and_the_limit_it_used(self):
        text = str(FlashReport(ok=False, general_hz=9.0, red_hz=4.0))
        # A report that drops its numbers, or prints one rate in place of the
        # other, is a report nobody can act on.
        assert "general<=9/s" in text
        assert "red<=4/s" in text
        assert f"(limit {FLASH_LIMIT:g}/s)" in text


class TestTheBudgetVerdictReadsCorrectly:
    def test_a_passing_report_says_ok_and_never_says_violated(self):
        text = str(BudgetReport(ok=True, scene_count=3))
        assert text.startswith("[BUDGETS OK]")
        assert "VIOLATED" not in text

    def test_a_failing_report_says_violated(self):
        text = str(BudgetReport(ok=False, scene_count=3))
        assert text.startswith("[BUDGETS VIOLATED]")

    def test_the_violations_are_actually_printed(self):
        """The head alone is not the report. A mutant that drops the
        violation lines leaves a failing verdict with nothing under it."""
        rep = BudgetReport(
            ok=False,
            violations=[Violation(code="pulse_rate", message="too fast")],
            warnings=[Violation(code="scene_len", message="long scene")],
            scene_count=2,
        )
        lines = str(rep).splitlines()
        # Exact lines, not `in`: the separator is mutable too, and a report
        # joined on "XX\nXX" still *contains* every violation while rendering
        # "XX  ✗ pulse_rate: too fast". Pinning the line pins the join.
        assert len(lines) == 3
        assert lines[0].startswith("[BUDGETS VIOLATED]")
        assert lines[1] == "  ✗ pulse_rate: too fast"
        assert lines[2] == "  ⚠ scene_len: long scene"

    def test_it_reports_the_proof_numbers(self):
        text = str(BudgetReport(ok=True, scene_count=7,
                                worst_display_hz=30.0, worst_emit_per_sec=2.5))
        assert "scenes=7" in text
        assert "display<=30Hz" in text
        assert "emit<=2.5/s" in text


class TestAViolationNamesItselfAndItsPlace:
    def test_code_and_message_both_survive_to_the_text(self):
        text = str(Violation(code="pulse_rate", message="12Hz exceeds 3Hz"))
        assert text == "pulse_rate: 12Hz exceeds 3Hz"

    def test_a_scene_is_named_when_there_is_one(self):
        text = str(Violation(code="scene_len", message="too long",
                             scene="intro"))
        assert text == "scene_len [scene intro]: too long"

    def test_no_empty_scene_brackets_when_there_is_none(self):
        """The `if self.scene` guard is the whole point: without it a
        sceneless violation renders a dangling `[scene None]`."""
        assert "[scene" not in str(Violation(code="c", message="m"))
        assert "None" not in str(Violation(code="c", message="m"))
