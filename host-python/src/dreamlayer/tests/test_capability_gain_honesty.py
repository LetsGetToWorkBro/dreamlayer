"""A capability's `gain` is the sentence a wearer reads before installing.

`capabilities.py` is not documentation — the panel and the phone's Capabilities
screen render `gain` verbatim next to an install button. So a `gain` that
describes an upgrade the install does not deliver is a false promise made at the
exact moment someone is deciding to spend disk, bandwidth and trust.

Three of them were false in the same shape: they described the BASELINE as
missing something the adapter already does without any dependency at all.

  * `causal_fusion` — "baseline fuses credibility channels with fixed weights;
    this infers causally". It inferred nothing; deleted (decisions/0006).
  * `typed_pipeline` — "baseline pipeline has no trace; this records what ran
    and where it failed". `StagePipeline.run` builds `trace` and sets
    `failed_at` unconditionally, with the wheel absent. Reworded once, then
    dropped outright (#577): the seam's only use of the dependency was the
    availability probe, so there was no honest sentence left to write — the
    runner is dependency-free and complete, and the capability row was
    offering an install that bought nothing. The behaviour test below stays,
    because the sequential runner is now the ONLY claim this file makes about
    that seam.
  * `persona_tuning` — "baseline persona filter is a no-op; this lets you tune
    it by example". `HumanLearnClassifier.classify` applies whatever rule
    callable it was given, with hulearn absent.

`structured_output` is the model for what these should say: it states plainly
that a wired local model already does the job, and names exactly what the
libraries add on top ("constrain the model AT GENERATION").
"""
from __future__ import annotations

import pytest

from dreamlayer.capabilities import CAPABILITIES

_BY_KEY = {c.key: c for c in CAPABILITIES}


def _cap(key):
    c = _BY_KEY.get(key)
    if c is None:
        pytest.skip(f"{key} is no longer declared")
    return c


class TestTheBaselineIsDescribedHonestly:
    def test_the_traced_pipeline_traces_without_its_dependency(self):
        """The claim under test is about behaviour, so it is checked by running
        the thing rather than by reading the sentence."""
        from dreamlayer.reality_compiler.pipeline_pydanticai import StagePipeline
        out = StagePipeline([("a", lambda _v: 1), ("b", lambda v: v + 1)]).run()
        assert out.ok and out.value == 2
        assert out.trace == ["a", "b"], "the baseline already records what ran"

        bad = StagePipeline([("a", lambda _v: 1),
                             ("boom", lambda _v: 1 / 0)]).run()
        assert bad.ok is False and bad.failed_at == "boom"
        assert bad.trace == ["a"], "…and where it failed"

    def test_the_traced_pipeline_has_no_optional_dependency_to_probe(self):
        """The claim went with the probe (#577), so the probe must not come
        back under another name.

        Read through the AST rather than grepped, for the reason
        `scripts/capability_dependency.py` gives: a mention in a comment or a
        docstring is not an import, and this module's docstring explains at
        length what it no longer imports. The assertion is the strong form —
        the runner imports the standard library and nothing else — because
        "dependency-free" is the whole of what the module now claims.
        """
        import ast
        import pathlib
        from dreamlayer.reality_compiler import pipeline_pydanticai as mod

        tree = ast.parse(pathlib.Path(mod.__file__).read_text(encoding="utf-8"))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                roots.add((node.module or "").split(".")[0])
        assert roots <= {"__future__", "logging", "dataclasses", "typing"}, (
            f"the runner imports something optional again: {sorted(roots)}")
        assert not hasattr(mod, "available"), (
            "the capability-meter flag is back on a module no capability "
            "declares — see #577")

    def test_the_persona_classifier_applies_a_rule_without_its_dependency(self):
        from dreamlayer.orchestrator.persona_humanlearn import HumanLearnClassifier
        c = HumanLearnClassifier(default="neutral",
                                 rule=lambda f: "warm" if f.get("smiles") else "cool")
        assert c.classify({"smiles": 1}) == "warm"
        assert c.classify({"smiles": 0}) == "cool"

    def test_a_rule_that_raises_falls_back_rather_than_propagating(self):
        from dreamlayer.orchestrator.persona_humanlearn import HumanLearnClassifier
        c = HumanLearnClassifier(default="neutral",
                                 rule=lambda f: 1 / 0)
        assert c.classify({}) == "neutral"


class TestTheGainMatchesTheBaseline:
    @pytest.mark.parametrize("key", ["persona_tuning"])
    def test_it_no_longer_calls_the_baseline_absent(self, key):
        gain = _cap(key).gain.lower()
        for lie in ("has no trace", "is a no-op"):
            assert lie not in gain, (
                f"{key} describes its own working baseline as missing: {gain!r}")

    @pytest.mark.parametrize("key", ["persona_tuning"])
    def test_it_says_what_installing_actually_buys(self, key):
        """Naming the real delta is the whole job — "it already works, and here
        is the specific thing you get on top" is an honest upgrade prompt; "the
        baseline is broken" is not."""
        gain = _cap(key).gain.lower()
        assert "already" in gain
        assert "yet" in gain, (
            f"{key} does not say the delta is unclaimed by anything in the tree")

    @pytest.mark.parametrize("key,floor", [("persona_tuning", 3.0)])
    def test_the_baseline_is_not_scored_as_if_it_were_absent(self, key, floor):
        """`before` was the actual lie, not the delta.

        These were scored 2.5 and 0 — "barely there" and "does not exist" —
        for baselines that trace a pipeline and apply a classification rule with
        no dependency installed. The pipeline one is not scored at all any
        more: it was dropped rather than re-scored a second time (#577),
        leaving the classifier as the live case here.

        `after` staying strictly greater is correct and
        is the catalogue's own invariant (test_pack_install_ux): the pair scores
        the POTENTIAL once wired, which is how every dormant entry is scored.
        Setting them equal to signal "changes nothing today" broke that, and
        said something the numbers are not for.
        """
        c = _cap(key)
        assert c.before >= floor, (
            f"{key} scores its working baseline at {c.before}, as if absent")
        assert c.before < c.after <= 5

    def test_structured_output_no_longer_sells_what_it_cannot_deliver(self):
        """It used to promise these libraries "constrain the model AT
        GENERATION so a malformed suggestion can't be produced in the first
        place". That is now true and delivered by the MODEL SERVER's own schema
        field, with no dependency — so the sentence described a benefit the
        install cannot add. See decisions/0007."""
        gain = _cap("structured_output").gain.lower()
        assert "already" in gain, "it must name what the baseline already does"
        assert "adds nothing here" in gain, (
            "the gain still reads as a benefit installing the extras provides")

    def test_the_deleted_one_is_not_back(self):
        assert "causal_fusion" not in _BY_KEY, (
            "causal_fusion is declared again — read decisions/0006 first; it "
            "could not return a number on any input, with or without dowhy")

    def test_the_dropped_one_is_not_back(self):
        """The other way a gain can be honest is not to exist.

        `typed_pipeline` was reworded once — and the reworded sentence still
        ended in "which nothing in the tree asks for yet", under an install
        button. Declaring it again needs a caller first: a path that hands the
        stages to something typed, and a fallback test showing both runners
        agree on the same stage list (#577 spells out what that would take).
        """
        assert "typed_pipeline" not in _BY_KEY, (
            "typed_pipeline is declared again — the seam still has to USE what "
            "the entry asks the wearer to install; see #577")
