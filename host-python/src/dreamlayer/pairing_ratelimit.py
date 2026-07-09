"""pairing_ratelimit.py — a small brute-force lockout limiter for pairing.

The brief suggested django-axes here, but `pairing.py` is not a Django app, so
axes does not fit. This is an in-house substitute delivering the same intent:
after N failed attempts within a window, lock a key (an IP, a device id, a code
prefix) out for a cooldown so a bad actor cannot grind pairing codes.

ADD-alongside: `pairing.py` (encode/decode_pairing, connect_all) is untouched.
Pure stdlib, no dependency, deterministic clock injectable for tests.

    lim = LockoutLimiter(max_attempts=5, window_s=60, lockout_s=300)
    if not lim.allow(ip):        # locked out — refuse before checking the code
        return reject()
    ok = verify_pairing(code)
    lim.record_success(ip) if ok else lim.record_failure(ip)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List


@dataclass
class _Bucket:
    fails: List[float] = field(default_factory=list)
    locked_until: float = 0.0


class LockoutLimiter:
    """Sliding-window failure counter with a cooldown lock, keyed by any string."""

    def __init__(self, max_attempts: int = 5, window_s: float = 60.0,
                 lockout_s: float = 300.0, now_fn: Callable[[], float] | None = None):
        self.max_attempts = max_attempts
        self.window_s = window_s
        self.lockout_s = lockout_s
        self._now = now_fn or time.monotonic
        self._buckets: Dict[str, _Bucket] = {}

    def _bucket(self, key: str) -> _Bucket:
        return self._buckets.setdefault(key, _Bucket())

    def allow(self, key: str) -> bool:
        """True if `key` may attempt now (not currently locked out)."""
        b = self._bucket(key)
        return self._now() >= b.locked_until

    def record_failure(self, key: str) -> bool:
        """Register a failed attempt. Returns True if this trips a lockout."""
        now = self._now()
        b = self._bucket(key)
        b.fails = [t for t in b.fails if now - t < self.window_s]
        b.fails.append(now)
        if len(b.fails) >= self.max_attempts:
            b.locked_until = now + self.lockout_s
            b.fails.clear()
            return True
        return False

    def record_success(self, key: str) -> None:
        """A good attempt clears the slate for that key."""
        self._buckets.pop(key, None)

    def retry_after(self, key: str) -> float:
        """Seconds until `key` may try again (0 if not locked)."""
        b = self._bucket(key)
        return max(0.0, b.locked_until - self._now())

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._buckets.clear()
        else:
            self._buckets.pop(key, None)
