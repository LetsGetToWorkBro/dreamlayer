"""human-learn interactive classifier — auditable, hand-labelled rules over past
moments that improve the persona/self-model over time.

ADD-alongside: new module (persona.py untouched). Lazy-imports human-learn
(extras group `intelligence`); when absent it falls back to an identity
classifier that returns the configured default label.
"""
from __future__ import annotations
import logging

log = logging.getLogger("dreamlayer.persona_humanlearn")

try:
    import hulearn  # type: ignore  # noqa: F401
    _HAS_HULEARN = True
except ImportError:
    _HAS_HULEARN = False


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
