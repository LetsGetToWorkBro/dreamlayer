"""Differential privacy toolkit + the mesh group-summary seam (D9).

A small circle that releases an EXACT aggregate leaks each member: in a group of
three, a mean that jumps the instant you join has told everyone your value
(refute 2026-07-18: the confluence aggregate seam had no DP at all). These pin
the ε-DP toolkit (Laplace mechanism, budget accountant, privatized aggregates)
and that the mesh group summary actually spends a bounded budget and refuses
once it's exhausted.
"""
from __future__ import annotations

import random
import statistics

import pytest

from dreamlayer.differential_privacy import (
    DPAggregator, LaplaceMechanism, PrivacyAccountant, PrivacyBudgetExceeded,
    laplace_noise,
)


def _rng(seed=1234):
    return random.Random(seed).random


# --- the mechanism -----------------------------------------------------------

def test_laplace_noise_is_zero_scale_safe():
    assert laplace_noise(0.0, _rng()) == 0.0


def test_laplace_noise_survives_boundary_draws():
    """random() CAN return exactly 0.0 (range [0,1)); the naive ln(1-2|u|) form
    hits ln(0) there and crashes a release. Every boundary draw must yield a
    finite number, not raise (refute 2026-07-18)."""
    import math
    for draw in (0.0, 1e-18, 0.5, 1.0 - 1e-16):
        v = laplace_noise(1.0, lambda d=draw: d)
        assert math.isfinite(v)


def test_laplace_mechanism_is_unbiased_and_scales_with_epsilon():
    # Averaged over many draws the noise cancels (mean ≈ the true value), and a
    # smaller epsilon => larger spread (stronger privacy, noisier).
    rand = _rng()
    tight = LaplaceMechanism(epsilon=5.0, sensitivity=1.0, rand=rand)
    loose = LaplaceMechanism(epsilon=0.5, sensitivity=1.0, rand=rand)
    tight_draws = [tight.add_noise(10.0) for _ in range(4000)]
    loose_draws = [loose.add_noise(10.0) for _ in range(4000)]
    assert abs(statistics.fmean(tight_draws) - 10.0) < 0.3
    assert statistics.pstdev(loose_draws) > statistics.pstdev(tight_draws)


def test_mechanism_rejects_bad_params():
    with pytest.raises(ValueError):
        LaplaceMechanism(epsilon=0)
    with pytest.raises(ValueError):
        LaplaceMechanism(epsilon=1.0, sensitivity=-1)


# --- the accountant (composition budget) -------------------------------------

def test_accountant_tracks_and_refuses_overspend():
    acct = PrivacyAccountant(total_epsilon=1.0)
    acct.spend(0.4)
    acct.spend(0.5)
    assert acct.spent == pytest.approx(0.9)
    assert acct.remaining == pytest.approx(0.1)
    assert acct.can_spend(0.1) is True
    assert acct.can_spend(0.2) is False
    with pytest.raises(PrivacyBudgetExceeded):
        acct.spend(0.2)          # would exceed the budget → refused


def test_accountant_rejects_nonpositive_budget():
    with pytest.raises(ValueError):
        PrivacyAccountant(0)


# --- privatized aggregates ---------------------------------------------------

def test_dp_count_is_nonnegative_and_near_true():
    acct = PrivacyAccountant(1e9)
    agg = DPAggregator(acct, rand=_rng())
    draws = [agg.count(50, epsilon=1.0) for _ in range(500)]
    assert all(d >= 0 for d in draws)
    assert abs(statistics.fmean(draws) - 50) < 3


def test_dp_sum_clamps_outliers():
    # An outlier beyond [lo,hi] is clamped, so it can't dominate: the clamped sum
    # of [1, 1, 1000] under hi=2 is ~4, not ~1002 (before noise).
    acct = PrivacyAccountant(1e9)
    agg = DPAggregator(acct, rand=_rng())
    vals = [1.0, 1.0, 1000.0]
    draws = [agg.dp_sum(vals, lo=0.0, hi=2.0, epsilon=2.0) for _ in range(400)]
    assert abs(statistics.fmean(draws) - 4.0) < 1.0


def test_dp_mean_bounded_and_none_on_empty():
    acct = PrivacyAccountant(1e9)
    agg = DPAggregator(acct, rand=_rng())
    assert agg.mean([], lo=0, hi=1, epsilon=1.0) is None
    # a noisy count can occasionally round to <=0 (mean → None); that's valid DP.
    draws = [agg.mean([0.2, 0.4, 0.6, 0.8], lo=0.0, hi=1.0, epsilon=2.0)
             for _ in range(300)]
    vals = [d for d in draws if d is not None]
    assert len(vals) > 250                          # the vast majority resolve
    assert all(0.0 <= d <= 1.0 for d in vals)       # always clamped in range
    assert abs(statistics.fmean(vals) - 0.5) < 0.15


def test_dp_histogram_over_fixed_categories():
    acct = PrivacyAccountant(1e9)
    agg = DPAggregator(acct, rand=_rng())
    labels = ["a", "a", "b", "c", "zzz-not-a-category"]
    draws = [agg.histogram(labels, ["a", "b", "c"], epsilon=1.0)
             for _ in range(400)]
    assert set(draws[0]) == {"a", "b", "c"}          # only the public cats
    mean_a = statistics.fmean(d["a"] for d in draws)
    assert abs(mean_a - 2) < 1.0                       # "a" occurred twice


def test_every_query_spends_budget():
    acct = PrivacyAccountant(total_epsilon=1.0)
    agg = DPAggregator(acct, rand=_rng())
    agg.count(10, epsilon=0.6)
    with pytest.raises(PrivacyBudgetExceeded):
        agg.histogram(["a"], ["a"], epsilon=0.6)      # 0.6+0.6 > 1.0


# --- the mesh group-summary seam ---------------------------------------------

@pytest.fixture(autouse=True)
def _clean_group_budgets():
    from dreamlayer.confluence import mesh
    mesh._reset_group_budgets()
    yield
    mesh._reset_group_budgets()


def _mesh_pair():
    from dreamlayer.confluence.mesh import MeshManager, InMemoryBus
    bus = InMemoryBus()
    a = MeshManager(now_fn=lambda: 1000.0, me="A")
    b = MeshManager(now_fn=lambda: 1000.0, me="B")
    gid, code = a.form()
    b.join(gid, code)
    bus.attach("A")
    bus.attach("B")
    return a, b, bus


def test_group_summary_is_dp_and_budget_bounded():
    from dreamlayer.confluence import mesh
    a, b, bus = _mesh_pair()
    # B reports a "storm" weather to A
    pkt = b.emit("weather", {"state": -0.9, "colors": []})
    a.receive(pkt.to_wire())
    summary = a.dp_group_summary(epsilon=1.0, my_state=0.5)
    assert summary is not None
    assert set(summary["bands"]) == set(mesh.WEATHER_BANDS)
    assert summary["members"] >= 0
    assert 0.0 <= summary["epsilon_remaining"] <= mesh.MESH_DP_BUDGET


def test_group_summary_refuses_once_budget_spent():
    a, b, bus = _mesh_pair()
    pkt = b.emit("weather", {"state": 0.9, "colors": []})
    a.receive(pkt.to_wire())
    # spend the whole per-group budget in big gulps
    refused = False
    for _ in range(20):
        if a.dp_group_summary(epsilon=1.0) is None:
            refused = True
            break
    assert refused, "the DP budget must eventually refuse further summaries"


def test_group_summary_none_when_group_not_live():
    from dreamlayer.confluence.mesh import MeshManager
    m = MeshManager(now_fn=lambda: 1000.0)
    assert m.dp_group_summary() is None       # never bound → not live


def test_budget_survives_rejoin_and_second_instance():
    """The decisive privacy fix (refute 2026-07-18): the ε-budget is keyed on the
    group_id, so re-joining the same circle — or a second manager instance for it
    — CANNOT reset it and average the noise away."""
    from dreamlayer.confluence.mesh import MeshManager, MESH_DP_BUDGET
    a, b, bus = _mesh_pair()
    gid = a.group_id
    code_summaries = 0
    while a.dp_group_summary(epsilon=1.0) is not None:
        code_summaries += 1
        if code_summaries > 10:
            break
    assert code_summaries == int(MESH_DP_BUDGET)      # exhausted at the budget
    # re-join the SAME circle → must NOT get a fresh budget
    a.join(gid, "irrelevant-code")
    assert a.dp_group_summary(epsilon=1.0) is None
    # a brand-new manager for the same group_id shares the spent budget too
    c = MeshManager(now_fn=lambda: 1000.0, me="C")
    c.join(gid, "irrelevant-code")
    assert c.dp_group_summary(epsilon=1.0) is None


def test_group_summary_rejects_nonpositive_epsilon():
    a, b, bus = _mesh_pair()
    assert a.dp_group_summary(epsilon=0.0) is None
    assert a.dp_group_summary(epsilon=-1.0) is None
