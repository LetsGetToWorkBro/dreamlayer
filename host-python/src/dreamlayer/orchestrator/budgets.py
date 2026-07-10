"""orchestrator/budgets.py — the latency contract, per surface.

A wearable answer is only an answer if it lands inside a perceptual
budget; after that it's an interruption. These constants are the contract
(one place, named), and run_with_deadline() is the enforcement — the same
worker+deadline shape WorldChecker already proved on the caption path.

| surface                    | budget    |
|----------------------------|-----------|
| glance name (tier 0)       | 350 ms    |
| glance panel ("what is it")| 1.5 s     |
| juno ask                 | 2.5 s     |
| veritas world-check        | 2.5 s (world_check.py, unchanged) |
| answer-ahead               | 2.0 s or drop silently            |
| morning brief / REM        | unbounded, scheduled              |

A budget miss is not an error the wearer sees — it's a tier skipped (the
router moves on) and a failure recorded in the health ledger so the
builder sees the pattern.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

GLANCE_NAME_MS = 350
GLANCE_PANEL_MS = 1500
JUNO_ASK_MS = 2500
ANSWER_AHEAD_MS = 2000

# One small shared pool: deadline work is I/O-shaped (model/HTTP calls) and
# must not fan out into a thread stampede. Abandoned calls finish in the
# background and are dropped — same policy as WorldChecker.
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dl-deadline")

_MISS = object()


def run_with_deadline(fn, timeout_ms: float, health=None, seam: str = "",
                      default=None):
    """Run fn() with a hard deadline. On a miss: record to the health
    ledger (seam 'deadline' context) and return `default`. On an exception
    inside fn: re-raise (callers keep their own except-and-degrade
    semantics). timeout_ms <= 0 disables the deadline."""
    if timeout_ms is None or timeout_ms <= 0:
        return fn()
    fut = _POOL.submit(fn)
    try:
        return fut.result(timeout=timeout_ms / 1000.0)
    except FutureTimeout:
        if health is not None:
            health.record_failure(
                "deadline", f"{seam or 'call'} missed {timeout_ms:.0f}ms")
        return default
