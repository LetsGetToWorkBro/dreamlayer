"""test_recipes.py — worked example figments for the Sous (4.2) and Kiln (4.3)
lenses. They're content, not engine code: budget-verified, runnable, and the
committed examples/figments/*.json stay valid."""
from __future__ import annotations

import json
from pathlib import Path

from dreamlayer.reality_compiler.v2.budgets import verify
from dreamlayer.reality_compiler.v2.figment import END, Figment
from dreamlayer.reality_compiler.v2.interpreter import Stage
from dreamlayer.reality_compiler.v2.recipes import kiln_figment, sous_sear_figment

EXAMPLES = Path(__file__).resolve().parents[4] / "examples" / "figments"


def test_both_recipes_pass_the_budget_gate():
    assert verify(sous_sear_figment()).ok
    assert verify(kiln_figment()).ok


def test_sous_runs_sear_then_rest_to_end():
    st = Stage(sous_sear_figment(sear_sec=10, rest_sec=5))
    st.step(20)                    # crosses sear(10) → rest(5) → end
    assert st.ended


def test_sous_double_nod_advances_to_rest():
    st = Stage(sous_sear_figment())
    st.inject("imu:double_nod")
    assert st.current == "rest"


def test_kiln_chains_all_three_stages_and_counts_the_print():
    st = Stage(kiln_figment())
    st.step(1000)                  # 30 + 300 + 600 = 930s → past WASH → end
    assert st.ended
    assert st.counters["print"] == 2     # started at 1, WASH increments


def test_kiln_double_nod_advances_and_low_battery_escapes():
    st = Stage(kiln_figment())
    st.inject("imu:double_nod")
    assert st.current == "fix"
    st.inject("battery_low")
    assert st.current == "low"


def test_committed_example_json_stays_valid():
    for name in ("sous-sear", "kiln-darkroom"):
        data = json.loads((EXAMPLES / f"{name}.json").read_text())
        fig = Figment.from_dict(data)
        assert verify(fig).ok, name
