"""test_pairing_ratelimit.py — the brute-force lockout limiter and the hardened
pairing-code decoder.

Audit 2026-07-14 (pairing +ratelimit, C+): `_buckets` could grow unbounded and
`decode_pairing` had no error handling / size cap / scheme validation. These
tests pin the fixes: a hard-bounded LRU table (revert-failing under a
within-window key-rotation flood), correct lockout-trip semantics, and a decoder
that raises one predictable ValueError on anything malformed.

Dependency-light on purpose (pairing + pairing_ratelimit only) so it stays
runnable while other modules churn.
"""
from __future__ import annotations

import base64
import json

import pytest

from dreamlayer.pairing import (
    PairingBundle, encode_pairing, decode_pairing, SCHEME, _MAX_CODE_LEN,
)
from dreamlayer.pairing_ratelimit import LockoutLimiter


class _Clock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t

    def tick(self, dt):
        self.t += dt


# --- lockout trip semantics --------------------------------------------------

def test_lockout_trips_on_the_nth_failure_and_recovers():
    clk = _Clock()
    lim = LockoutLimiter(max_attempts=3, window_s=60, lockout_s=300, now_fn=clk)
    assert lim.allow("ip")
    assert lim.record_failure("ip") is False        # 1
    assert lim.record_failure("ip") is False        # 2
    assert lim.record_failure("ip") is True         # 3 -> trips
    assert not lim.allow("ip")                       # locked out
    assert lim.retry_after("ip") == 300
    clk.tick(301)
    assert lim.allow("ip")                           # cooldown elapsed
    assert lim.retry_after("ip") == 0


def test_success_clears_the_slate():
    clk = _Clock()
    lim = LockoutLimiter(max_attempts=3, window_s=60, lockout_s=300, now_fn=clk)
    lim.record_failure("ip")
    lim.record_failure("ip")
    lim.record_success("ip")                         # a good attempt resets
    assert lim.record_failure("ip") is False         # counting restarts at 1
    assert lim.record_failure("ip") is False         # 2, still not tripped


def test_failures_outside_the_window_dont_accumulate():
    clk = _Clock()
    lim = LockoutLimiter(max_attempts=3, window_s=10, lockout_s=300, now_fn=clk)
    lim.record_failure("ip")
    clk.tick(11)                                     # first fail ages out
    lim.record_failure("ip")
    lim.record_failure("ip")
    assert lim.allow("ip")                           # only 2 within the window


# --- the table is HARD-bounded, not merely pruned ---------------------------

def test_buckets_hard_bounded_under_within_window_flood():
    """Revert-failing: a fresh key per attempt, all within one window (so the
    prune finds nothing expired), must NOT grow the table without bound. The
    prune-only predecessor grew to the full flood size here; the LRU hard bound
    caps it at _MAX_BUCKETS."""
    clk = _Clock()                                   # never advances -> nothing expires
    lim = LockoutLimiter(max_attempts=3, window_s=60, lockout_s=300, now_fn=clk)
    lim._MAX_BUCKETS = 32
    for i in range(2000):
        lim.record_failure(f"ip-{i}")
    assert len(lim._buckets) <= lim._MAX_BUCKETS


def test_lru_evicts_the_oldest_and_keeps_the_recently_touched():
    clk = _Clock()
    lim = LockoutLimiter(max_attempts=9, window_s=60, lockout_s=300, now_fn=clk)
    lim._MAX_BUCKETS = 3
    lim.record_failure("a")
    lim.record_failure("b")
    lim.record_failure("c")
    lim.allow("a")                                   # touch 'a' -> most recent
    lim.record_failure("d")                          # table full -> evict LRU ('b')
    assert "a" in lim._buckets and "d" in lim._buckets
    assert "b" not in lim._buckets                   # least-recently-used, gone


def test_expired_buckets_are_pruned_before_eviction():
    clk = _Clock()
    lim = LockoutLimiter(max_attempts=3, window_s=10, lockout_s=10, now_fn=clk)
    lim._MAX_BUCKETS = 2
    lim.record_failure("old")
    clk.tick(100)                                    # 'old' fully expires
    lim.record_failure("x")
    lim.record_failure("y")
    assert "old" not in lim._buckets                 # reclaimed, not force-evicted
    assert len(lim._buckets) <= lim._MAX_BUCKETS


# --- pairing code: round-trip + hardened decode -----------------------------

def test_encode_decode_round_trip():
    b = PairingBundle(brain_url="http://mbp.local:7777", token="rune-birch",
                      glasses_id="HALO-9F2A", relay_url="https://relay.x/abc")
    back = decode_pairing(encode_pairing(b))
    assert back.brain_url == b.brain_url and back.token == b.token
    assert back.glasses_id == "HALO-9F2A" and back.relay_url == b.relay_url


def test_decode_tolerates_bare_base64():
    code = encode_pairing(PairingBundle(brain_url="http://x", token="t"))
    bare = code.split(":", 1)[1]
    assert decode_pairing(bare).brain_url == "http://x"


def test_decode_rejects_oversized_input():
    with pytest.raises(ValueError):
        decode_pairing("x" * (_MAX_CODE_LEN + 1))


def test_decode_rejects_garbage():
    with pytest.raises(ValueError):
        decode_pairing(SCHEME + ":not-valid-base64-!!!")
    with pytest.raises(ValueError):
        # valid base64 but not JSON
        decode_pairing(base64.urlsafe_b64encode(b"\xff\xfe").decode("ascii"))


def test_decode_rejects_non_json_object():
    payload = base64.urlsafe_b64encode(b'"just a string"').decode("ascii")
    with pytest.raises(ValueError):
        decode_pairing(payload)


def test_decode_rejects_a_non_http_brain_url():
    # a crafted code must not smuggle a file:// / javascript: scheme into HTTP
    raw = json.dumps({"brain_url": "file:///etc/passwd", "token": "t"})
    code = base64.urlsafe_b64encode(raw.encode()).decode("ascii")
    with pytest.raises(ValueError):
        decode_pairing(code)
