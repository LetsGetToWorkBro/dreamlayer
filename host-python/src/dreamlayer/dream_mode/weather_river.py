"""River streaming "inner weather" — learns your personal rhythm/mood one
observation at a time.

ADD-alongside: new sibling to inner_weather.py (untouched). Lazy-imports river
(extras group `intelligence`); when absent it keeps an exponential running mean,
so `sample()` still adapts without the dep.
"""
from __future__ import annotations
import logging

log = logging.getLogger("dreamlayer.weather_river")

try:
    from river import stats  # type: ignore
    _HAS_RIVER = True
except ImportError:
    _HAS_RIVER = False


class RiverWeather:
    available = _HAS_RIVER

    def __init__(self, alpha: float = 0.2):
        self._alpha = alpha
        self._mean: float | None = None
        self._roll = None
        if _HAS_RIVER:
            try:
                self._roll = stats.EWMean(fading_factor=1 - alpha)
            except Exception as exc:
                log.error("[weather_river] init failed: %s; running-mean", exc)
                self._roll = None

    def update(self, value: float) -> float:
        if self._roll is not None:
            try:
                self._roll.update(value)
                return float(self._roll.get())
            except Exception:
                pass
        self._mean = value if self._mean is None else self._mean + self._alpha * (value - self._mean)
        return self._mean

    def sample(self) -> float:
        if self._roll is not None:
            try:
                return float(self._roll.get())
            except Exception:
                pass
        return self._mean if self._mean is not None else 0.0


class WeatherBaseline:
    """Learns your personal weather baseline so "storm" means stormy *for you*.

    Inner Weather's raw state is an absolute restlessness scalar — good for
    painting the core, wrong for deciding when to *warn*: a naturally fidgety
    person would trip a fixed threshold all day, and a very still person's real
    agitation might never reach it. This tracks the running mean of your state
    and its spread (mean absolute deviation), and answers one question:
    "is this moment unusually restless *for you*, right now?"

    Two `RiverWeather` trackers under the hood (EWMean when river is installed,
    an exponential running mean otherwise) — so it learns online, needs no dep,
    and stays deterministic. Until it has seen `warmup` samples it defers to the
    caller's fixed threshold, so cold-start behaviour is unchanged.
    """

    def __init__(self, alpha: float = 0.05, warmup: int = 20,
                 min_spread: float = 0.04, k: float = 1.5):
        self._mean = RiverWeather(alpha)
        self._spread = RiverWeather(alpha)
        self._warmup = warmup
        self._min_spread = min_spread
        self._k = k
        self._n = 0

    def observe(self, state: float) -> None:
        """Fold one state reading into the baseline. Call once per tick, only
        when capture is allowed (a veiled tick teaches it nothing)."""
        state = max(0.0, min(1.0, float(state)))
        m = self._mean.update(state)
        self._spread.update(abs(state - m))
        self._n += 1

    def mean(self) -> float:
        return self._mean.sample()

    def is_elevated(self, state: float, fallback: float) -> bool:
        """True when `state` sits above your personal normal by more than your
        usual spread — the personalised storm condition. Before warmup, falls
        back to the fixed `fallback` threshold."""
        if self._n < self._warmup:
            return state > fallback
        margin = max(self._min_spread, self._k * self._spread.sample())
        return (state - self._mean.sample()) > margin
