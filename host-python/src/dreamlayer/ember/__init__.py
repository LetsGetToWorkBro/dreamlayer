"""Ember — memories you tend until they live in you.

Every other Memory-lens feature stores your life *for* you. Ember runs the
other way: over morning coffee you keep up to three of yesterday's moments
(tending.py), and from then on the glasses prompt you — with a cue, never
the answer, at the place it happened, at spacing-effect intervals
(scheduler.py) — to retrieve the moment yourself. Speak it; grading.py
scores the reach; the curve advances. When the trace is stable enough to
live without the machine, the recording becomes an offer to delete
(ceremony.py): the archive that empties itself into you.

The anniversary Ember card (ops_world_lenses.ember) is this feature's
afterglow: a burned engram leaves a pinned, cue-only tombstone, which is
exactly what that lens resurfaces a year later.

    from dreamlayer.ember import EmberStore, TendingPass, grade_recall
    from dreamlayer.ember import next_review, RecallOutcome
"""
from .scheduler import (
    CONSOLIDATION_THRESHOLD_DAYS, EngramState, RecallOutcome,
    defer, interval_for, is_due, next_review, retrievability, seed_state,
)
from .engram import Engram, TendingCandidate
from .store import EmberStore
from .tending import TendingPass, make_cue
from .grading import grade_recall, recall_score
from .ceremony import BurnReceipt, burn, offers

__all__ = [
    "CONSOLIDATION_THRESHOLD_DAYS", "EngramState", "RecallOutcome",
    "defer", "interval_for", "is_due", "next_review", "retrievability",
    "seed_state", "Engram", "TendingCandidate", "EmberStore", "TendingPass",
    "make_cue", "grade_recall", "recall_score", "BurnReceipt", "burn",
    "offers",
]
