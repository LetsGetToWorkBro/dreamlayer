"""ember/scheduler.py — the curve along which a machine's memory becomes yours.

Every other memory feature in DreamLayer stores things *for* you. Ember runs
the other direction: it schedules moments for you to retrieve *yourself*, at
the expanding intervals where retrieval practice does the most consolidating
work (the spacing effect), and prompts with a cue — never the answer — because
recalling strengthens a memory in a way that re-reading provably does not
(the testing effect).

The math is FSRS-shaped (the modern spaced-repetition model: memory state is
a (stability, difficulty) pair; retrievability decays along a power curve;
each review updates the state from the grade and how far the trace had
decayed). The constants here are FSRS's published defaults, lightly rounded —
Ember schedules a handful of life moments, not ten thousand flashcards, so
per-user parameter fitting would be fake precision.

Everything is a pure function of (state, outcome, now): no clock reads, no
randomness, no I/O. The same review history always produces the same curve,
which is what makes `ember log` a trustworthy readout of what your own memory
is doing.

Two outcomes deserve a note:

  MISSED  — the prompt fired and you walked past it. Not a lapse: nothing was
            tested, so nothing is penalised. The engram just comes due again.
            Forgetting deserves gentleness; so does being busy.
  FORGOT  — you reached and it wasn't there. Stability drops (a real lapse)
            and the rebuilt trace regrows faster than it grew the first time
            (relearning is cheaper than learning — the classic savings effect).

Graduation: when stability crosses CONSOLIDATION_THRESHOLD_DAYS the trace is
durable enough to live without the machine, and the store may *offer* the raw
recording for deletion (ceremony.py). The scheduler only ever raises the flag;
consent to burn is the wearer's alone.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum

# -- the contract ------------------------------------------------------------

DAY = 86400.0

# Stability (in days) at which the memory is judged to live in the wearer:
# ~3 months of projected 90% retrievability. A moment typically earns this in
# five to ten successful spaced recalls spread across half a year or more —
# deletion is earned slowly, on purpose (the offer is irreversible; the curve
# should not be in a hurry to make it).
CONSOLIDATION_THRESHOLD_DAYS = 90.0

# Review intervals are clamped to [same evening, one year]: shorter than half
# a day and the prompt nags; longer than a year and the product has quietly
# become an archive again.
MIN_INTERVAL_DAYS = 0.5
MAX_INTERVAL_DAYS = 365.0

# Scheduling targets 90% retrievability — prompts should arrive just before
# the forgetting curve predicts the moment slips, not while it's still easy.
TARGET_RETENTION = 0.90

# FSRS-shaped constants (defaults, rounded — see module docstring).
_S0 = {1: 0.4, 2: 1.2, 3: 3.2, 4: 16.0}   # first stability by grade, days
_D0_BASE, _D0_STEP = 5.0, 1.6             # first difficulty: 5 - (g-3)*1.6
_D_DRIFT = 0.6                            # difficulty step per later review
_D_ANCHOR = 4.0                           # ...mean-reverting toward this
_GROWTH = 3.0                             # success: base stability growth
_HARD_PENALTY = 0.35                      # HARD grows at 35% of GOOD's gain
_EASY_BONUS = 1.6                         # EASY grows at 160% of GOOD's gain
_LAPSE_FACTOR = 0.35                      # FORGOT: S' ~ 0.35 * S^0.6 ...
_LAPSE_POWER = 0.6                        # ...sublinear: hard falls fall far
_SAVINGS = 1.15                           # relearned traces regrow 15% faster


class RecallOutcome(Enum):
    """What happened when the ember glowed. Values are FSRS grades, with
    MISSED (no attempt was made) deliberately outside the graded range."""
    MISSED = 0
    FORGOT = 1
    HARD = 2
    GOOD = 3
    EASY = 4


@dataclass(frozen=True)
class EngramState:
    """The memory-model state of one kept moment. Times are epoch seconds;
    stability is in days (the FSRS convention), because the forgetting curve
    is a statement about days, not ticks."""
    stability: float          # days until retrievability decays to ~90%
    difficulty: float         # 1 (effortless) … 10 (slippery)
    due_ts: float             # when the next place-gated prompt may fire
    reps: int = 0             # successful recalls, lifetime
    lapses: int = 0           # honest forgets, lifetime
    last_review_ts: float = 0.0
    graduated: bool = False   # stability crossed the consolidation threshold


# -- the forgetting curve ----------------------------------------------------

def retrievability(state: EngramState, now: float) -> float:
    """Probability the wearer could still retrieve the moment unaided.

    FSRS power forgetting curve: R(t) = (1 + t / 9S)^-1, with t and S in
    days. R = 0.9 exactly when t = S — which is what "stability" means.
    """
    if state.last_review_ts <= 0:
        return 1.0
    t = max(0.0, (now - state.last_review_ts) / DAY)
    return (1.0 + t / (9.0 * state.stability)) ** -1.0


def interval_for(stability: float) -> float:
    """Days until retrievability decays to TARGET_RETENTION.

    From the curve: t = 9S(1/R - 1); at R = 0.9 that is exactly S. Clamped
    to the product's window (see MIN/MAX_INTERVAL_DAYS).
    """
    days = 9.0 * stability * (1.0 / TARGET_RETENTION - 1.0)
    return min(MAX_INTERVAL_DAYS, max(MIN_INTERVAL_DAYS, days))


# -- state transitions -------------------------------------------------------

def seed_state(kept_at: float, first_impression: RecallOutcome = RecallOutcome.GOOD) -> EngramState:
    """The state of a moment the instant the wearer chooses to keep it.

    The tending ritual itself is the first retrieval event — choosing a
    moment from the evening's candidates means re-encountering it — so the
    engram is born reviewed, with first-review FSRS initialisation.
    """
    g = first_impression.value if first_impression != RecallOutcome.MISSED else 3
    g = min(4, max(1, g))
    stability = _S0[g]
    difficulty = _clamp_d(_D0_BASE - (g - 3) * _D0_STEP)
    return EngramState(
        stability=stability,
        difficulty=difficulty,
        due_ts=kept_at + interval_for(stability) * DAY,
        reps=1 if g > 1 else 0,
        lapses=0 if g > 1 else 1,
        last_review_ts=kept_at,
        graduated=stability >= CONSOLIDATION_THRESHOLD_DAYS,
    )


def next_review(state: EngramState, outcome: RecallOutcome, now: float) -> EngramState:
    """Advance an engram through one place-gated recall attempt.

    Pure: returns the new state, never mutates. Sets `graduated` when
    stability crosses CONSOLIDATION_THRESHOLD_DAYS — the flag that unlocks
    the deletion ceremony. Graduation is a ratchet: a later lapse shrinks
    stability but never revokes it (the offer to burn was already earned;
    whether the recording still exists is the ceremony's business, and a
    revoked flag after the burn would be a lie).
    """
    if outcome == RecallOutcome.MISSED:
        return defer(state, now)

    r = retrievability(state, now)
    if outcome == RecallOutcome.FORGOT:
        stability = _lapse_stability(state, r)
        reps, lapses = state.reps, state.lapses + 1
    else:
        stability = _success_stability(state, r, outcome)
        reps, lapses = state.reps + 1, state.lapses

    difficulty = _next_difficulty(state.difficulty, outcome)
    return EngramState(
        stability=stability,
        difficulty=difficulty,
        due_ts=now + interval_for(stability) * DAY,
        reps=reps,
        lapses=lapses,
        last_review_ts=now,
        graduated=state.graduated or stability >= CONSOLIDATION_THRESHOLD_DAYS,
    )


def defer(state: EngramState, now: float) -> EngramState:
    """The prompt fired; the wearer walked on. No attempt, no judgement:
    memory state is untouched and the engram simply comes due again after
    a gentle beat (a quarter of its current interval, floor half a day).
    """
    pause = max(MIN_INTERVAL_DAYS, interval_for(state.stability) * 0.25)
    return replace(state, due_ts=now + pause * DAY)


def is_due(state: EngramState, now: float) -> bool:
    return now >= state.due_ts


# -- internals ---------------------------------------------------------------

def _clamp_d(d: float) -> float:
    return min(10.0, max(1.0, d))


def _next_difficulty(d: float, outcome: RecallOutcome) -> float:
    """Difficulty drifts with the grade and mean-reverts toward the anchor,
    so one bad night can't permanently mark a moment as slippery."""
    drifted = d - _D_DRIFT * (outcome.value - 3)
    reverted = drifted * 0.9 + _D_ANCHOR * 0.1
    return _clamp_d(reverted)


def _success_stability(state: EngramState, r: float, outcome: RecallOutcome) -> float:
    """FSRS-shaped growth: gains scale up for easy material (11 - D), shrink
    as stability saturates (S^-0.5), and grow the further the trace had
    decayed before the save (e^(1-R) - 1): a hard-won recall at the brink
    consolidates far more than an easy one made too soon.
    """
    gain = (
        _GROWTH
        * (11.0 - state.difficulty)
        * (state.stability ** -0.5)
        * (math.exp(1.0 - r) - 1.0)
    )
    if outcome == RecallOutcome.HARD:
        gain *= _HARD_PENALTY
    elif outcome == RecallOutcome.EASY:
        gain *= _EASY_BONUS
    if state.lapses > 0:
        gain *= _SAVINGS
    return state.stability * (1.0 + max(0.05, gain))


def _lapse_stability(state: EngramState, r: float) -> float:
    """An honest forget. Post-lapse stability is sublinear in what was lost
    (0.35 * S^0.6): a moment forgotten from great height falls far, but
    never below the floor a brand-new FORGOT would seed."""
    fallen = _LAPSE_FACTOR * (state.stability ** _LAPSE_POWER)
    return max(_S0[1], min(fallen, state.stability))
