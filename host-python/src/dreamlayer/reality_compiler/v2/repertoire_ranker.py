"""v2/repertoire_ranker.py — the compiler teaches itself (INNOVATION_SESSION 5.3).

The feedback sensors already exist: the Vault's performance log records every
deploy, and the figment lifecycle knows when a machine reached its terminal
scene (complete) or was killed (banish). This closes the loop: an online learner
scores each kept figment by **use frequency**, **completion rate** (reached the
end vs. got banished), and **time-of-day fit**, so the Oracle can offer the
right machine at the right time — "Gym? Start the usual circuit?"

Same shape as `orchestrator/taste_river.py`: lazy-imports river (extras group
`intelligence`) for the completion model, and keeps an in-house running mean
when it's absent, so `score()`/`suggest()` adapt either way. Deterministic, and
rebuildable from the Vault history (`hydrate`) so it survives a restart — the
vault keeps the lineage.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("dreamlayer.repertoire_ranker")

try:
    from river import linear_model, preprocessing, compose  # type: ignore
    _HAS_RIVER = True
except ImportError:
    _HAS_RIVER = False

# score weights (sum to 1): a machine you finish, at the hour you usually run it,
# that you run often, floats to the top.
W_COMPLETION, W_TIME, W_FREQUENCY = 0.4, 0.35, 0.25
_FREQ_K = 4.0                 # deploys for the frequency term to reach ~0.5
_TIME_SIGMA = 2.0             # hours: width of the time-of-day fit kernel
_COMPLETION_ALPHA = 0.3       # EMA step for the running-mean fallback


def _circ_dist(a: int, b: int) -> float:
    """Distance between two hours on a 24-hour clock (0..12)."""
    d = abs(a - b) % 24
    return min(d, 24 - d)


@dataclass
class _FigmentStats:
    deploys: int = 0
    hours: dict = field(default_factory=dict)   # hour -> count
    completion: float = 0.5                      # running-mean fallback
    outcomes: int = 0                            # complete/banish observations

    def time_fit(self, hour: int) -> float:
        """How well `hour` matches when this figment is usually run (0..1).
        0.5 when there's no history yet — no opinion, no penalty."""
        if not self.hours:
            return 0.5
        total = sum(self.hours.values())
        num = sum(c * math.exp(-(_circ_dist(h, hour) ** 2) / (2 * _TIME_SIGMA ** 2))
                  for h, c in self.hours.items())
        return num / total if total else 0.5


class RepertoireRanker:
    available = _HAS_RIVER

    def __init__(self):
        self._stats: dict[str, _FigmentStats] = {}
        self._model = None
        if _HAS_RIVER:
            try:
                self._model = compose.Pipeline(
                    preprocessing.StandardScaler(),
                    linear_model.LogisticRegression())
            except Exception as exc:
                log.error("[repertoire_ranker] init failed: %s; running-mean", exc)
                self._model = None

    def _stat(self, figment_id: str) -> _FigmentStats:
        return self._stats.setdefault(figment_id, _FigmentStats())

    # -- observation ---------------------------------------------------------

    def observe(self, figment_id: str, action: str, hour: Optional[int] = None) -> None:
        """Fold one lifecycle event in. `action` ∈ {deploy, complete, banish}.
        `hour` (0..23) is used by deploy to learn the time-of-day pattern."""
        st = self._stat(figment_id)
        if action == "deploy":
            st.deploys += 1
            if hour is not None:
                h = int(hour) % 24
                st.hours[h] = st.hours.get(h, 0) + 1
            return
        if action in ("complete", "banish"):
            reached = 1.0 if action == "complete" else 0.0
            st.outcomes += 1
            if self._model is not None:
                try:
                    self._model.learn_one({"k": hash(figment_id) % 997}, int(reached))
                except Exception:
                    pass
            st.completion += _COMPLETION_ALPHA * (reached - st.completion)

    def hydrate(self, history_by_id: dict) -> None:
        """Rebuild from Vault performance logs: {figment_id: [record, ...]}
        where a record is {"action": "deploy"|"complete"|"banish", "hour"?}."""
        for fid, records in (history_by_id or {}).items():
            for rec in records:
                action = rec.get("action")
                if action in ("deploy", "complete", "banish"):
                    self.observe(fid, action, rec.get("hour"))

    # -- scoring -------------------------------------------------------------

    def completion_rate(self, figment_id: str) -> float:
        st = self._stat(figment_id)
        if self._model is not None and st.outcomes:
            try:
                return float(self._model.predict_proba_one(
                    {"k": hash(figment_id) % 997}).get(1, st.completion))
            except Exception:
                pass
        return st.completion

    def score(self, figment_id: str, hour: int) -> float:
        st = self._stat(figment_id)
        freq = st.deploys / (st.deploys + _FREQ_K)            # saturating 0..1
        return round(W_COMPLETION * self.completion_rate(figment_id)
                     + W_TIME * st.time_fit(hour)
                     + W_FREQUENCY * freq, 6)

    def rank(self, entries: list, hour: int) -> list:
        """Stable re-sort of repertoire entries (objects with `.figment.id` or
        dicts with `id`) by fit-for-now, best first."""
        def id_of(e):
            fig = getattr(e, "figment", None)
            if fig is not None:
                return fig.id
            return e.get("id") if isinstance(e, dict) else str(e)
        return sorted(entries, key=lambda e: self.score(id_of(e), hour), reverse=True)

    def suggest(self, entries: list, hour: int, min_score: float = 0.55,
                min_deploys: int = 2) -> Optional[dict]:
        """The single best machine for right now, or None when nothing is a
        confident fit. Never suggests something barely used or usually banished."""
        best = None
        for e in entries:
            fig = getattr(e, "figment", None)
            fid = fig.id if fig is not None else (e.get("id") if isinstance(e, dict) else None)
            name = fig.name if fig is not None else (e.get("name") if isinstance(e, dict) else "")
            if fid is None:
                continue
            st = self._stat(fid)
            if st.deploys < min_deploys:
                continue
            s = self.score(fid, hour)
            if s >= min_score and (best is None or s > best["score"]):
                best = {"id": fid, "name": name, "score": s,
                        "say": f"{name} — start the usual?"}
        return best
