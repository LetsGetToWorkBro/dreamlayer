"""object_lens/polled.py — make a real data source safe to glance at.

An Object Lens provider's data_source is called every time you look at the
object — many times a minute. A real source (a laptop over the network, an
OBD dongle, a cloud API) must never be hit on that path, or a slow read
stalls the HUD. PolledSource is the wrapper that fixes this for *any*
fetch_fn, so every integration gets the same production behaviour:

  instant           calling it returns the last cached snapshot immediately
  background        a stale cache triggers a refresh off the glance path;
                    the result lands in the cache when it arrives
  stale, not blank  a failed or slow fetch keeps the last good data and
                    marks it stale (age in seconds), so the panel can say
                    "34 psi (2h ago)" instead of freezing or blanking

Wrap once, use anywhere:

    src = PolledSource(read_obd_dongle, ttl=60)
    registry.register(CarProvider(src))

The snapshot carries three meta keys the provider may read: `_age_s` (float
or None), `_stale` (bool), `_ok` (bool — has any fetch ever succeeded).
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional


class PolledSource:
    def __init__(self, fetch_fn: Callable[[], dict], ttl: float = 30.0,
                 timeout: float = 2.0, now_fn: Optional[Callable[[], float]] = None):
        self._fetch = fetch_fn
        self.ttl = ttl
        self.timeout = timeout
        self._now = now_fn or time.monotonic
        self._lock = threading.Lock()
        self._snapshot: Optional[dict] = None    # last good data
        self._fetched_at: Optional[float] = None
        self._error: Optional[Exception] = None
        self._thread: Optional[threading.Thread] = None

    # -- freshness -------------------------------------------------------

    def age(self) -> Optional[float]:
        with self._lock:
            if self._fetched_at is None:
                return None
            return self._now() - self._fetched_at

    def is_stale(self) -> bool:
        a = self.age()
        return a is None or a >= self.ttl

    def ok(self) -> bool:
        with self._lock:
            return self._snapshot is not None

    def error(self) -> Optional[Exception]:
        with self._lock:
            return self._error

    # -- fetching --------------------------------------------------------

    def _run_fetch(self) -> None:
        try:
            data = self._fetch()
            with self._lock:
                self._snapshot = dict(data) if data else {}
                self._fetched_at = self._now()
                self._error = None
        except Exception as e:                    # keep last good data
            with self._lock:
                self._error = e
        finally:
            with self._lock:
                self._thread = None

    def refresh(self, block: bool = False) -> None:
        """Kick a refresh. block=True (tests/first-fill) waits up to timeout;
        block=False returns at once and the result lands in the cache later."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                t = self._thread
            else:
                t = threading.Thread(target=self._run_fetch, daemon=True)
                self._thread = t
                t.start()
        if block:
            t.join(self.timeout)

    def wait_idle(self, timeout: float = 2.0) -> None:
        """Join any in-flight refresh (test helper)."""
        t = self._thread
        if t is not None:
            t.join(timeout)

    def snapshot(self) -> dict:
        with self._lock:
            snap = dict(self._snapshot) if self._snapshot is not None else {}
            age = (None if self._fetched_at is None
                   else self._now() - self._fetched_at)
            snap["_age_s"] = None if age is None else round(age, 1)
            snap["_stale"] = age is None or age >= self.ttl
            snap["_ok"] = self._snapshot is not None
        return snap

    # -- the data_source callable ---------------------------------------

    def __call__(self) -> dict:
        """What you pass as a provider's data_source. Never blocks."""
        if self.is_stale():
            self.refresh(block=False)
        return self.snapshot()


def humanize_age(seconds: Optional[float]) -> str:
    """"just now" / "5m ago" / "2h ago" for a snapshot's _age_s."""
    if seconds is None:
        return ""
    s = max(0.0, seconds)
    if s < 45:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)}m ago"
    if s < 86400:
        return f"{int(s // 3600)}h ago"
    return f"{int(s // 86400)}d ago"
