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
        self._mean = None
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
