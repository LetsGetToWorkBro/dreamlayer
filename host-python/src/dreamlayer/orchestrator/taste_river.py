"""River online-learning taste ranker — nudges TasteLens ranking toward what you
actually pick, updating one observation at a time (no retraining).

ADD-alongside: new module (taste.py untouched). Lazy-imports river (extras group
`intelligence`); when absent it keeps a simple in-house running-average of
per-label preference, so `rerank()` still adapts without the dep.
"""
from __future__ import annotations
import logging

log = logging.getLogger("dreamlayer.taste_river")

try:
    from river import linear_model, preprocessing, compose  # type: ignore
    _HAS_RIVER = True
except ImportError:
    _HAS_RIVER = False


class RiverTasteRanker:
    available = _HAS_RIVER

    def __init__(self):
        self._prefs: dict[str, float] = {}   # fallback running mean per key
        self._model = None
        if _HAS_RIVER:
            try:
                self._model = compose.Pipeline(preprocessing.StandardScaler(),
                                               linear_model.LogisticRegression())
            except Exception as exc:
                log.error("[taste_river] init failed: %s; running-mean fallback", exc)
                self._model = None

    def observe(self, key: str, chosen: bool) -> None:
        """Record that item `key` was chosen (True) or passed over (False)."""
        if self._model is not None:
            try:
                self._model.learn_one({"k": hash(key) % 997}, int(chosen))
                return
            except Exception as exc:
                log.warning("[taste_river] learn failed: %s; running-mean", exc)
        cur = self._prefs.get(key, 0.5)
        self._prefs[key] = cur + 0.2 * (float(chosen) - cur)

    def score(self, key: str) -> float:
        if self._model is not None:
            try:
                return float(self._model.predict_proba_one({"k": hash(key) % 997}).get(1, 0.5))
            except Exception:
                pass
        return self._prefs.get(key, 0.5)

    def rerank(self, ranked: list) -> list:
        """Stable re-sort of a TasteLens ranking by learned preference. Accepts a
        list of (key, item) or objects with `.key`/`.label`; unknown → 0.5."""
        def key_of(x):
            if isinstance(x, (tuple, list)) and x:
                return str(x[0])
            return str(getattr(x, "key", None) or getattr(x, "label", None) or x)
        return sorted(ranked, key=lambda x: self.score(key_of(x)), reverse=True)
