"""ai_brain/world_check.py — the world check, made fast.

Veritas decides *what* to check and `verify.py` decides *how* a single claim
becomes a verdict. This is the layer that makes the world check quick enough
to matter in a live conversation: it never blocks the caption pipeline, it
never asks the same thing twice, and it gives a slow tier a hard deadline.

Three levers, all here so the orchestrator's hot path stays a single
non-blocking call:

  cache     A short-TTL, bounded cache of claim -> verdict. Ask "is the capital
            of Australia Sydney" twice in a chat and the second answer is
            instant. Keyed on the normalised claim; evicts oldest first.

  deadline  A per-claim timeout. A tier that hasn't answered in `timeout_s`
            is abandoned (its late answer is dropped) so a verdict is either
            quick or nothing — Veritas is meant to inform in time to respond,
            not to arrive after the moment has passed.

  off-path  A single background worker runs the ask. `check_async` returns
            immediately; the verdict is delivered through a callback when (and
            only if) it lands in time. Self-contradiction — the offline pass —
            has already fired synchronously by the time we get here, so the
            wearer never waits on the network for the fast half.

Pure and injectable: the `ask_fn` is the brain router's `ask` (local model
first, cloud only when opted in), passed in by the caller. Nothing here
reaches the network on its own, and `check_sync` makes the whole thing
deterministic under test.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from .verify import verify_claim

AskFn = Callable[[str], object]
DeliverFn = Callable[[dict], None]


def _norm(claim: str) -> str:
    """Normalise a claim for cache keying: lowercase, collapse whitespace,
    drop trailing punctuation. 'Sydney is the capital.' and 'sydney is the
    capital' share a verdict."""
    return " ".join((claim or "").lower().split()).strip(" .!?\"'")


class _TTLCache:
    """A tiny bounded, time-to-live cache. Oldest-first eviction."""

    def __init__(self, maxsize: int = 256, ttl_s: float = 900.0):
        self.maxsize = int(maxsize)
        self.ttl_s = float(ttl_s)
        self._d: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str, now: float) -> Optional[dict]:
        with self._lock:
            hit = self._d.get(key)
            if hit is None:
                return None
            ts, val = hit
            if now - ts > self.ttl_s:
                self._d.pop(key, None)
                return None
            self._d.move_to_end(key)           # LRU touch
            return val

    def put(self, key: str, val: dict, now: float) -> None:
        with self._lock:
            self._d[key] = (now, val)
            self._d.move_to_end(key)
            while len(self._d) > self.maxsize:
                self._d.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()


class WorldChecker:
    """Fast, cached, non-blocking world checks over an injected `ask_fn`.

    Parameters
    ----------
    timeout_s : float
        A verdict that takes longer than this is abandoned (its late result is
        cached but not delivered). Keep it tight — the point is to be in time.
    cache_ttl_s : float
        How long a verdict stays fresh. A fact rarely changes within a chat.
    now_fn : callable
        Injectable clock for deterministic tests.
    """

    def __init__(self, timeout_s: float = 2.5, cache_ttl_s: float = 900.0,
                 cache_size: int = 256, now_fn: Optional[Callable[[], float]] = None):
        self.timeout_s = float(timeout_s)
        self._cache = _TTLCache(maxsize=cache_size, ttl_s=cache_ttl_s)
        self._now = now_fn or time.monotonic
        # one serial worker: verifies are cheap to queue and must not fan out
        # into a stampede of cloud calls from a fast-talking room.
        self._pool = ThreadPoolExecutor(max_workers=1,
                                        thread_name_prefix="worldcheck")
        self._inflight: set[str] = set()
        self._lock = threading.Lock()

    # -- fast paths ------------------------------------------------------

    def cached(self, claim: str) -> Optional[dict]:
        """The verdict for `claim` if it's already known and fresh, else None."""
        return self._cache.get(_norm(claim), self._now())

    def check_sync(self, claim: str, ask_fn: AskFn) -> Optional[dict]:
        """Verify now, on this thread, honouring the cache. Deterministic —
        used by tests and by callers that genuinely want to block."""
        key = _norm(claim)
        if not key:
            return None
        hit = self._cache.get(key, self._now())
        if hit is not None:
            return hit
        verdict = verify_claim(claim, ask_fn)
        if verdict is not None:
            self._cache.put(key, verdict, self._now())
        return verdict

    def check_async(self, claim: str, ask_fn: AskFn,
                    deliver: DeliverFn) -> bool:
        """Schedule a world check off the caption path.

        A cached verdict is delivered inline and True is returned. Otherwise
        the ask runs on the background worker and `deliver(verdict)` fires when
        it lands within the deadline. Returns True when a verdict was (or will
        be) produced from cache, False when the work was queued. `deliver` is
        never called for an unknown/None verdict or a deadline miss, so the
        caller only ever sees something worth surfacing.
        """
        key = _norm(claim)
        if not key:
            return False
        hit = self._cache.get(key, self._now())
        if hit is not None:
            deliver(hit)
            return True
        with self._lock:
            if key in self._inflight:          # someone's already asking
                return False
            self._inflight.add(key)
        started = self._now()
        fut = self._pool.submit(self._run, claim, key, ask_fn)

        def _done(f):
            with self._lock:
                self._inflight.discard(key)
            try:
                verdict = f.result()
            except Exception:
                verdict = None
            if verdict is None:
                return
            if (self._now() - started) > self.timeout_s:
                return                         # too late to be useful; cache kept
            deliver(verdict)

        fut.add_done_callback(_done)
        return False

    # -- internal --------------------------------------------------------

    def _run(self, claim: str, key: str, ask_fn: AskFn) -> Optional[dict]:
        verdict = verify_claim(claim, ask_fn)
        if verdict is not None:
            self._cache.put(key, verdict, self._now())
        return verdict

    def clear_cache(self) -> None:
        self._cache.clear()

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)
