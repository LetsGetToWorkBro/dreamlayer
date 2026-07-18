"""differential_privacy.py — bounded-disclosure aggregates for shared views.

When many wearers' private values collapse into ONE released number — the mood of
a room, how many in the circle feel storm-grey — that number leaks information
about each contributor unless it is deliberately fuzzed. A circle of three where
the "average" jumps the instant you join has just told everyone your value.
Differential privacy is the formal bound: add calibrated noise so the released
statistic is nearly the same whether or not any single person took part, and
TRACK a privacy budget so repeated queries can't average the noise away.

A small, self-contained, dependency-free ε-DP toolkit:

  * LaplaceMechanism(epsilon, sensitivity) — the classic ε-DP mechanism: noise
    scaled to sensitivity/epsilon.
  * PrivacyAccountant — sequential-composition budget. Every query spends ε; once
    the budget is spent, further queries are REFUSED, because the DP guarantee
    only holds if you actually stop.
  * DPAggregator — privatized count / sum / mean / histogram with input clamping,
    so a single outlier can't blow up the noise scale (bounded sensitivity).

Determinism: the RNG is injectable. Production seeds it from `secrets` (the noise
must be unpredictable, or an attacker subtracts it back off); tests pass a seeded
`random.Random` for reproducibility.
"""
from __future__ import annotations

import math
import secrets
from typing import Callable, Iterable, Optional


class PrivacyBudgetExceeded(RuntimeError):
    """A query would spend more of the ε-budget than remains — refused, because
    the DP guarantee only holds if querying stops at the budget."""


def _system_rng() -> Callable[[], float]:
    """A cryptographically-seeded uniform(0,1) source. The noise must be
    unpredictable: a guessable PRNG lets an observer estimate and subtract it,
    collapsing the privacy guarantee."""
    sr = secrets.SystemRandom()
    return sr.random


def laplace_noise(scale: float, rand: Callable[[], float]) -> float:
    """A Laplace(0, scale) sample via inverse-CDF of a uniform draw. scale =
    sensitivity/epsilon. rand() must return a uniform in [0, 1)."""
    if scale <= 0:
        return 0.0
    u = rand() - 0.5                         # (-0.5, 0.5)
    # 1 - 2|u| ∈ (0, 1], so the log is always finite (rand()<1 → |u|<0.5)
    return -scale * math.copysign(1.0, u) * math.log(1.0 - 2.0 * abs(u))


class LaplaceMechanism:
    """Add Laplace noise calibrated to (sensitivity / epsilon). Larger epsilon =
    less noise = weaker privacy; smaller sensitivity = less noise."""

    def __init__(self, epsilon: float, sensitivity: float = 1.0,
                 rand: Optional[Callable[[], float]] = None):
        if epsilon <= 0:
            raise ValueError("epsilon must be > 0")
        if sensitivity < 0:
            raise ValueError("sensitivity must be >= 0")
        self.epsilon = float(epsilon)
        self.sensitivity = float(sensitivity)
        self._rand = rand or _system_rng()

    @property
    def scale(self) -> float:
        return self.sensitivity / self.epsilon

    def add_noise(self, value: float) -> float:
        return float(value) + laplace_noise(self.scale, self._rand)


class PrivacyAccountant:
    """A sequential-composition ε-budget. Under composition the ε's of successive
    queries ADD, so a fixed budget caps total disclosure across a session. Once
    spent, queries are refused rather than silently continuing to leak."""

    def __init__(self, total_epsilon: float):
        if total_epsilon <= 0:
            raise ValueError("total_epsilon must be > 0")
        self.total = float(total_epsilon)
        self._spent = 0.0

    @property
    def spent(self) -> float:
        return self._spent

    @property
    def remaining(self) -> float:
        return max(0.0, self.total - self._spent)

    def can_spend(self, epsilon: float) -> bool:
        return epsilon > 0 and self._spent + epsilon <= self.total + 1e-12

    def spend(self, epsilon: float) -> None:
        if epsilon <= 0:
            raise ValueError("epsilon must be > 0")
        if not self.can_spend(epsilon):
            raise PrivacyBudgetExceeded(
                f"query needs ε={epsilon:g} but only {self.remaining:g} of the "
                f"ε={self.total:g} budget remains; refusing to over-spend privacy")
        self._spent += epsilon


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


class DPAggregator:
    """Privatized aggregates over a set of contributors, drawing from one shared
    ε-budget. Each release clamps inputs to a declared range (bounding one
    contributor's influence = the sensitivity) then adds Laplace noise."""

    def __init__(self, accountant: PrivacyAccountant,
                 rand: Optional[Callable[[], float]] = None):
        self._acct = accountant
        self._rand = rand or _system_rng()

    @property
    def accountant(self) -> PrivacyAccountant:
        return self._acct

    def _mech(self, epsilon: float, sensitivity: float) -> LaplaceMechanism:
        return LaplaceMechanism(epsilon, sensitivity, self._rand)

    def count(self, n: int, epsilon: float) -> int:
        """A DP count of a population of size *n*. One person's presence changes a
        count by 1 → sensitivity 1. Never returns negative."""
        self._acct.spend(epsilon)
        noisy = self._mech(epsilon, 1.0).add_noise(float(n))
        return max(0, int(round(noisy)))

    def dp_sum(self, values: Iterable[float], lo: float, hi: float,
               epsilon: float) -> float:
        """A DP sum of values clamped to [lo, hi]. Add/remove of one clamped
        record moves the sum by at most max(|lo|, |hi|) → that is the
        sensitivity."""
        self._acct.spend(epsilon)
        total = sum(_clamp(float(v), lo, hi) for v in values)
        sensitivity = max(abs(lo), abs(hi))
        return self._mech(epsilon, sensitivity).add_noise(total)

    def mean(self, values, lo: float, hi: float, epsilon: float) -> Optional[float]:
        """A DP mean via a noisy sum and a noisy count, splitting the ε between
        them (composition). Returns None for an empty population."""
        values = list(values)
        if not values:
            return None
        half = epsilon / 2.0
        noisy_sum = self.dp_sum(values, lo, hi, half)
        noisy_n = self.count(len(values), half)
        if noisy_n <= 0:
            return None
        return _clamp(noisy_sum / noisy_n, lo, hi)

    def histogram(self, labels: Iterable[str], categories: Iterable[str],
                  epsilon: float) -> dict:
        """A DP histogram: the count in each of *categories*. Each contributor
        falls in exactly one bin, so the whole release has sensitivity 1 — each
        bin gets independent Laplace(1/epsilon) noise. Labels outside
        *categories* are ignored (a fixed public category set avoids leaking the
        domain itself)."""
        self._acct.spend(epsilon)
        cats = list(categories)
        counts = {c: 0 for c in cats}
        for lab in labels:
            if lab in counts:
                counts[lab] += 1
        mech = self._mech(epsilon, 1.0)
        return {c: max(0, int(round(mech.add_noise(float(counts[c]))))) for c in cats}
