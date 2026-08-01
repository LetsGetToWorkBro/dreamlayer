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
    `failed_at` unconditionally, with pydantic_ai absent.
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
    @pytest.mark.parametrize("key", ["typed_pipeline", "persona_tuning"])
    def test_it_no_longer_calls_the_baseline_absent(self, key):
        gain = _cap(key).gain.lower()
        for lie in ("has no trace", "is a no-op"):
            assert lie not in gain, (
                f"{key} describes its own working baseline as missing: {gain!r}")

    @pytest.mark.parametrize("key", ["typed_pipeline", "persona_tuning"])
    def test_it_says_what_installing_actually_buys(self, key):
        """Naming the real delta is the whole job — "it already works, and here
        is the specific thing you get on top" is an honest upgrade prompt; "the
        baseline is broken" is not."""
        gain = _cap(key).gain.lower()
        assert "already" in gain
        assert "yet" in gain, (
            f"{key} does not say the delta is unclaimed by anything in the tree")

    @pytest.mark.parametrize("key", ["typed_pipeline", "persona_tuning"])
    def test_the_score_does_not_promise_a_jump_nothing_delivers(self, key):
        """`before`/`after` drive the panel's impact ordering, so a capability
        that changes nothing today must not sort above one that does."""
        c = _cap(key)
        assert c.after == c.before, (
            f"{key} claims {c.before}→{c.after} for an install that changes "
            "no behaviour in this tree")

    def test_structured_output_stayed_the_model_for_the_others(self):
        gain = _cap("structured_output").gain.lower()
        assert "already" in gain
        assert "at generation" in gain, (
            "the one honest gain of the three lost the specific delta it names")

    def test_the_deleted_one_is_not_back(self):
        assert "causal_fusion" not in _BY_KEY, (
            "causal_fusion is declared again — read decisions/0006 first; it "
            "could not return a number on any input, with or without dowhy")
