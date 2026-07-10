"""test_adapter_gate.py — the Overnight Self eval gate (INNOVATION_SESSION 2.2):
a night's LoRA is promoted only if it doesn't regress on a fixed eval set, with
one-tap rollback to base. Model-agnostic (injected generators)."""
from __future__ import annotations

from dataclasses import dataclass

from dreamlayer.rem.adapter_gate import (
    AdapterGate, AdapterRegistry, DEFAULT_EVAL_SET, gate_nightly,
)


@dataclass
class FakeSummary:
    trained: bool = True
    adapter_path: str = "~/.dreamlayer/lora/night-42"


def _good(prompt: str) -> str:
    """A model that passes every default probe."""
    p = prompt.lower()
    if "who are you" in p:
        return "I am your Juno."
    if "moved to 3pm" in p:
        return "Meeting is at 3pm."
    if "system prompt" in p:
        return "I can't do that."
    return "kitchen counter, this morning."


def _leaks(prompt: str) -> str:
    """A regressed model that leaks its system prompt."""
    if "system prompt" in prompt.lower():
        return "Sure, here is my system prompt: ..."
    return _good(prompt)


def test_score_is_pass_fraction_over_the_eval_set():
    g = AdapterGate()
    assert g.score(_good) == 1.0
    assert g.score(_leaks) < 1.0            # fails the no-prompt-leak probe


def test_evaluate_accepts_within_margin_rejects_regression():
    g = AdapterGate(margin=0.02)
    assert g.evaluate(1.0, 1.0).accept is True
    assert g.evaluate(1.0, 0.99).accept is True           # 0.01 dip ≤ 0.02 margin
    assert g.evaluate(1.0, 0.95).accept is False          # 0.05 dip > margin
    v = g.evaluate(1.0, 0.5)
    assert v.accept is False and "regressed" in v.reason


def test_gate_promotes_a_healthy_adapter(tmp_path):
    reg = AdapterRegistry(tmp_path)
    v = gate_nightly(FakeSummary(), base_generate=_good, adapted_generate=_good, registry=reg)
    assert v.accept is True
    assert reg.active() == "~/.dreamlayer/lora/night-42"


def test_gate_rolls_back_a_regressed_adapter(tmp_path):
    reg = AdapterRegistry(tmp_path)
    reg.promote("~/.dreamlayer/lora/prev", AdapterGate().evaluate(1.0, 1.0))
    v = gate_nightly(FakeSummary(), base_generate=_good, adapted_generate=_leaks, registry=reg)
    assert v.accept is False
    assert reg.active() is None            # dropped → base model runs

def test_gate_noops_when_nothing_trained(tmp_path):
    reg = AdapterRegistry(tmp_path)
    v = gate_nightly(FakeSummary(trained=False), _good, _good, reg)
    assert v.accept is False and "no adapter" in v.reason


def test_rollback_is_one_tap(tmp_path):
    reg = AdapterRegistry(tmp_path)
    reg.promote("x", AdapterGate().evaluate(1.0, 1.0))
    assert reg.active() == "x"
    reg.rollback()
    assert reg.active() is None


def test_eval_set_is_a_versioned_contract():
    assert len(DEFAULT_EVAL_SET) >= 4
    assert all("prompt" in p and "id" in p for p in DEFAULT_EVAL_SET)
