"""human-learn interactive classifier — auditable, hand-labelled rules over past
moments that improve the persona/self-model over time.

ADD-alongside: new module (persona.py untouched). Lazy-imports human-learn
(extras group `intelligence`); when absent it falls back to an identity
classifier that returns the configured default label.

WHAT WAS MISSING, AND WHAT THIS IS FOR
--------------------------------------
`HumanLearnClassifier` applies any rule callable you hand it. Nothing in the
tree ever BUILT one, which is what left the capability dormant — and its own
catalogue entry said so: *"installing this is what lets you build that rule by
example … nothing in the tree builds one yet."*

`tune()` is that missing half, and it is deliberately not "learn a rule". What
human-learn provides headlessly is `FunctionClassifier`, which wraps a rule YOU
WROTE into the scikit-learn API so it can be scored and grid-searched. The
human writes the shape; the wearer's own labelled moments choose the
thresholds. That is the point of this library over a black box: the answer is
still a rule you can read out loud.

    def cautious(rows, min_confidence=0.85):
        return [r["confidence"] >= min_confidence for r in rows]

    best = tune(cautious, rows, labels, {"min_confidence": [0.7, 0.8, 0.9]})
    best.params           # {"min_confidence": 0.9}
    best.score            # measured, not asserted
    best.cross_validated  # True only when sklearn actually did k-fold

WITHOUT THE DEPENDENCY it still tunes — the same exhaustive search over the
same grid — but scores on the whole set instead of k-folding it, which
overfits a short history. `cross_validated` says which happened, so a caller
can tell a measured answer from an optimistic one rather than being quietly
handed the weaker one. That is the floor an optional dependency owes: never
less than the fallback, and never a silent difference in kind.
"""
from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

log = logging.getLogger("dreamlayer.persona_humanlearn")

try:
    import hulearn  # type: ignore  # noqa: F401
    _HAS_HULEARN = True
except ImportError:
    _HAS_HULEARN = False

#: Folds for the cross-validated path. Small on purpose: a wearer's labelled
#: history is tens of cards, not thousands.
CV_FOLDS = 3

#: Below this many labelled rows, tuning is refused outright. A "best" chosen
#: from six examples is noise wearing a number, and the caller must be able to
#: tell that apart from a real answer.
MIN_EXAMPLES = 12


@dataclass
class Tuned:
    """The outcome of a tuning run — and an honest one when it did not happen."""
    params: dict = field(default_factory=dict)
    score: float = 0.0
    #: True only when the score came from k-fold. False means it was measured
    #: on the same rows it was chosen from, which flatters it.
    cross_validated: bool = False
    #: Empty when tuning succeeded; otherwise why it did not.
    refused: str = ""
    examples: int = 0

    def __bool__(self) -> bool:
        return not self.refused


def _grid_points(grid: dict) -> list:
    """Every combination in the grid, as a list of param dicts."""
    if not grid:
        return [{}]
    names = sorted(grid)
    return [dict(zip(names, combo))
            for combo in itertools.product(*(list(grid[n]) for n in names))]


def _accuracy(rule: Callable, rows: Sequence, labels: Sequence,
              params: dict) -> float:
    """How often the rule agrees with the labels. -1.0 when it could not be
    asked at all, so a broken grid point loses to every working one."""
    try:
        got = list(rule(rows, **params))
    except Exception as exc:                             # noqa: BLE001
        log.debug("[persona_humanlearn] rule raised while scoring: %s",
                  type(exc).__name__)
        return -1.0
    if len(got) != len(labels):
        return -1.0
    hits = sum(1 for g, want in zip(got, labels) if bool(g) == bool(want))
    return hits / len(labels) if labels else 0.0


def _tune_plain(rule, rows, labels, grid) -> "Tuned":
    """The dependency-free tuner: the same exhaustive search, scored on the
    whole set. Honest about it — `cross_validated` stays False."""
    best: dict = {}
    best_score = -1.0
    for params in _grid_points(grid):
        score = _accuracy(rule, rows, labels, params)
        if score > best_score:
            best, best_score = params, score
    if best_score < 0:
        return Tuned(refused="the rule could not score any grid point",
                     examples=len(rows))
    return Tuned(params=best, score=best_score, cross_validated=False,
                 examples=len(rows))


def _tune_cv(rule, rows, labels, grid) -> Optional["Tuned"]:
    """k-fold through `FunctionClassifier`, or None when the real machinery is
    not usable — in which case the caller falls back rather than failing.

    `FunctionClassifier` is what human-learn provides for this headlessly: it
    puts a hand-written rule behind the scikit-learn estimator API, so the same
    scoring and search that grade a model can grade a rule you can read.
    """
    if not _HAS_HULEARN:
        return None
    try:
        import numpy as np
        from hulearn.classification import FunctionClassifier
        from sklearn.model_selection import GridSearchCV
    except Exception as exc:                             # noqa: BLE001
        log.info("[persona_humanlearn] cross-validated tuning unavailable: %s",
                 type(exc).__name__)
        return None
    folds = min(CV_FOLDS, len(rows))
    if folds < 2:
        return None

    def _predict(X, **params):
        # `X` arrives as the array sklearn split; the rule reads the rows it
        # was written for, so hand it back the list it expects.
        return np.asarray([1 if v else 0 for v in rule(list(X), **params)])

    try:
        search = GridSearchCV(FunctionClassifier(_predict), grid or {},
                              cv=folds, scoring="accuracy", error_score=0.0)
        search.fit(np.asarray(rows, dtype=object),
                   np.asarray([1 if v else 0 for v in labels]))
    except Exception as exc:                             # noqa: BLE001
        # A rule that will not survive being split is a fallback case, not a
        # crash: the plain tuner still answers, and says it did not k-fold.
        log.info("[persona_humanlearn] grid search failed: %s; scoring whole",
                 type(exc).__name__)
        return None
    best_score = float(search.best_score_)
    if not best_score > 0.0:
        # Every fold scored zero (or NaN): `error_score=0.0` turns a rule that
        # cannot be fitted into a silent 0, and returning that as a confident
        # answer would be worse than the fallback's honest refusal. Hand it
        # over instead.
        return None
    return Tuned(params=dict(search.best_params_), score=best_score,
                 cross_validated=True, examples=len(rows))


def tune(rule: Callable, rows: Sequence, labels: Sequence,
         grid: Optional[dict] = None) -> Tuned:
    """Choose a readable rule's thresholds from labelled examples.

    `rule(rows, **params) -> sequence of truthy` is yours to write and yours to
    read back; `grid` names the values each parameter may take. The answer is
    the grid point that best matches `labels`, the measured score, and whether
    it was cross-validated.

    Refuses — rather than guessing — on too few examples or a single label. A
    threshold picked from a handful of all-dismissed cards is not a preference,
    it is a coincidence, and returning it with a confident 1.0 would be exactly
    the failure this repo keeps finding.
    """
    rows, labels = list(rows), [bool(v) for v in labels]
    if len(rows) != len(labels):
        return Tuned(refused="rows and labels differ in length",
                     examples=len(rows))
    if len(rows) < MIN_EXAMPLES:
        return Tuned(refused=f"only {len(rows)} labelled examples "
                             f"(need {MIN_EXAMPLES})", examples=len(rows))
    if len(set(labels)) < 2:
        return Tuned(refused="every example carries the same label",
                     examples=len(rows))
    return _tune_cv(rule, rows, labels, grid or {}) \
        or _tune_plain(rule, rows, labels, grid or {})


class HumanLearnClassifier:
    available = _HAS_HULEARN

    def __init__(self, default: str = "neutral", rule=None):
        self.default = default
        self._rule = rule  # a callable(dict)->label, e.g. a FunctionClassifier

    def classify(self, features: dict) -> str:
        if self._rule is not None:
            try:
                out = self._rule(features)
                return str(out)
            except Exception as exc:
                log.warning("[persona_humanlearn] rule failed: %s; default", exc)
        return self.default

    @classmethod
    def from_tuned(cls, rule: Callable, tuned: Tuned, *,
                   default: str = "neutral",
                   labels: Sequence = ("no", "yes")) -> Any:
        """A classifier that applies `rule` with the tuned parameters bound.

        A REFUSED tuning yields the plain default classifier: the rule is not
        applied with guessed parameters, which would be worse than not applying
        it at all.
        """
        if not tuned:
            return cls(default=default)

        def _bound(features: dict) -> str:
            got = list(rule([features], **tuned.params))
            return labels[1] if (got and got[0]) else labels[0]

        return cls(default=default, rule=_bound)
