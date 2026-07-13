"""testkit/dst.py — DST-lite: seeded, replayable interleaving for the hub.

The problem: the orchestrator's background workers (message polling, the
context pulse, the capture pipeline — see docs/CONCURRENCY.md) all call into
hub state while the main thread ticks and mutates it. Concurrency bugs are the
least-tested class of bug in the system, and a plain threaded test that fails
once in a hundred runs is worse than no test — you can't reproduce it, so you
can't fix it or know you fixed it.

The marquee deterministic-simulation tools (madsim, shuttle, turmoil) are
Rust-only. This is the pragmatic Python equivalent, in two honest layers:

1. **Seeded interleaving (deterministic).** Model each concurrent party as an
   *actor* — an ordered queue of operations (the very calls its real thread
   makes: `ingest_caption`, `poll_messages_once`, `tick`, `set_incognito`…).
   The Interleaver merges the queues into ONE serial schedule chosen by a
   seeded RNG: per-actor order is preserved (a thread never reorders its own
   work), cross-actor order is the explored variable. Every run is a `Trace`;
   the same seed gives the same schedule; a failing schedule replays exactly.
   This explores every interleaving *at operation granularity* — which is the
   granularity that matters for the hub, whose ops are short synchronous
   methods under the GIL.

2. **True-thread stress (non-deterministic, labelled as such).** The same
   actor queues run on real threads behind a start barrier. This cannot be
   replayed — it exists to smoke out races *below* operation granularity
   (torn state inside one method). A failure here says "there is a real race";
   the seeded layer is where you then bisect the schedule.

SimClock completes the rig: a thread-safe virtual clock so cooldowns and
session windows are advanced, not slept — swap it over `orch._clock` (the
monotonic seam every duration in the hub reads) and a scenario that spans
"60 seconds" runs in microseconds, identically every time.
"""
from __future__ import annotations

import random
import threading
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence


class SimClock:
    """A thread-safe virtual clock. `monotonic()` is the drop-in for the
    orchestrator's `_clock` seam; `advance(dt)` moves time forward; `sleep(dt)`
    advances instead of blocking (so scheduled work can be driven, fast)."""

    def __init__(self, start: float = 0.0):
        self._now = float(start)
        self._lock = threading.Lock()

    def monotonic(self) -> float:
        with self._lock:
            return self._now

    # aliases so the clock can stand in for time.time / time.monotonic
    time = monotonic
    now = monotonic

    def advance(self, dt: float) -> float:
        with self._lock:
            self._now += float(dt)
            return self._now

    def sleep(self, dt: float) -> None:
        self.advance(dt)

    def install(self, orch) -> "SimClock":
        """Point the hub's monotonic seam at this clock. Every `_clock()`
        duration/cooldown in the orchestrator now runs on virtual time."""
        orch._clock = self.monotonic
        return self


@dataclass
class Trace:
    """One explored schedule: the seed that chose it and the exact order of
    (actor, op_index) steps. Feed it back to Interleaver.replay to reproduce a
    failure precisely."""
    seed: int
    steps: list[tuple[str, int]] = field(default_factory=list)

    def __str__(self) -> str:
        path = " ".join(f"{a}[{i}]" for a, i in self.steps)
        return f"Trace(seed={self.seed}: {path})"


class InterleavingFailure(AssertionError):
    """An op raised, or an invariant failed, under a specific schedule. Carries
    the trace so the exact failing interleaving is one replay() away."""

    def __init__(self, message: str, trace: Trace):
        super().__init__(f"{message}\n  reproduce with: {trace}")
        self.trace = trace


Actors = Mapping[str, Sequence[Callable[[], object]]]


class Interleaver:
    """Seeded, replayable interleaving of actor op-queues (layer 1 above)."""

    def run(self, actors: Actors, seed: int,
            invariant: Callable[[], object] | None = None) -> Trace:
        """Execute one seeded schedule. Per-actor order is preserved; the
        cross-actor merge is chosen by `seed`. `invariant` (if given) is
        checked after EVERY step — a violation names the exact prefix that
        caused it, not just the end state. Raises InterleavingFailure with the
        trace on any op exception or invariant failure."""
        rng = random.Random(seed)
        queues = {name: list(ops) for name, ops in actors.items()}
        progress = {name: 0 for name in queues}
        trace = Trace(seed=seed)
        while any(progress[n] < len(q) for n, q in queues.items()):
            ready = sorted(n for n, q in queues.items() if progress[n] < len(q))
            name = ready[rng.randrange(len(ready))]
            i = progress[name]
            trace.steps.append((name, i))
            try:
                queues[name][i]()
                progress[name] += 1
                if invariant is not None:
                    invariant()
            except Exception as exc:
                raise InterleavingFailure(
                    f"step {name}[{i}] failed: {exc!r}", trace) from exc
        return trace

    def replay(self, actors: Actors, trace: Trace,
               invariant: Callable[[], object] | None = None) -> None:
        """Re-execute the exact schedule a previous run produced — the
        reproduce-then-fix half of the workflow. The actors must be a fresh
        scenario with the same shape (same names, same op counts)."""
        queues = {name: list(ops) for name, ops in actors.items()}
        for name, i in trace.steps:
            try:
                queues[name][i]()
                if invariant is not None:
                    invariant()
            except Exception as exc:
                raise InterleavingFailure(
                    f"replayed step {name}[{i}] failed: {exc!r}", trace) from exc

    def explore(self, make_scenario: Callable[[], tuple],
                seeds: Sequence[int]) -> int:
        """Run a FRESH scenario per seed (make_scenario returns
        (actors, invariant) — a new hub each time, so schedules can't bleed
        into each other). Any failure carries its seed+trace. Returns the
        number of schedules that held."""
        for seed in seeds:
            actors, invariant = make_scenario()
            self.run(actors, seed, invariant)
        return len(seeds)


def run_threads(actors: Actors, joins_after: float = 10.0) -> None:
    """Layer 2: the same actor queues on REAL threads behind a start barrier.
    Non-deterministic by nature (the OS schedules) — a smoke test for races
    below operation granularity. Exceptions from any thread are collected and
    re-raised, so a torn read inside one method fails the test instead of
    dying silently on a daemon thread."""
    barrier = threading.Barrier(len(actors))
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(ops: Sequence[Callable[[], object]]):
        barrier.wait()
        for op in ops:
            try:
                op()
            except BaseException as exc:  # noqa: BLE001 - re-raised below
                with lock:
                    errors.append(exc)
                return

    threads = [threading.Thread(target=worker, args=(ops,), daemon=True)
               for ops in actors.values()]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=joins_after)
    alive = [t for t in threads if t.is_alive()]
    if alive:
        raise AssertionError(f"{len(alive)} actor thread(s) hung")
    if errors:
        raise errors[0]
