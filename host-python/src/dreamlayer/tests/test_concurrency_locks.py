"""Concurrency-safety regressions (audit 2026-07-14 §7).

Two live sites used to bypass a lock:

  1. ``ops_world_lenses.ember()`` read the shared ``db.conn`` with no
     ``db._lock`` — racing the off-thread capture writer on one SQLite
     connection, the exact interleaved-commit hazard the MemoryDB RLock
     exists to serialize.
  2. ``HostState`` toggled Memory<->Dream as a split check-then-act
     (``is_dream()`` then ``enter_dream()``/``exit_dream()``); run from the
     button callback thread and an HTTP/simulator thread, two toggles could
     interleave and silently drop one.

These stress tests hammer both locked paths from many threads and assert no
exception surfaces and the resulting state stays consistent.
"""
from __future__ import annotations

import threading

from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.orchestrator.state import HostState
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


# ---------------------------------------------------------------------------
# 1. ember() reads db.conn under db._lock while the writer hammers add_memory
# ---------------------------------------------------------------------------

def test_ember_read_is_serialized_against_concurrent_writes():
    orc = Orchestrator(FakeBridge())
    assert orc.privacy.allow_capture(), "ember needs an unveiled gate to reach db"

    writers, reads_per, writes_per = 4, 120, 60
    errors: list[BaseException] = []

    def writer(tag: int):
        try:
            for i in range(writes_per):
                orc.db.add_memory(kind="taught", summary=f"m{tag}-{i}",
                                  confidence=0.5)
        except BaseException as exc:            # noqa: BLE001 - collect & assert
            errors.append(exc)

    def reader():
        try:
            for _ in range(reads_per):
                # ember() runs the guarded SELECT on the shared connection;
                # unlocked it raced the writer's execute/commit on that conn.
                orc.ember()
        except BaseException as exc:            # noqa: BLE001 - collect & assert
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(writers)]
    threads += [threading.Thread(target=reader) for _ in range(writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert all(not t.is_alive() for t in threads), "a locked path deadlocked/hung"
    assert not errors, f"shared-connection access raced: {errors}"
    # every write landed exactly once — the lock serialized readers and writers
    assert len(orc.db.memories()) == writers * writes_per


# ---------------------------------------------------------------------------
# 2. HostState.toggle_dream() is an atomic compound flip
# ---------------------------------------------------------------------------

def test_host_state_toggle_dream_is_atomic_under_threads():
    st = HostState()
    assert not st.is_dream()

    threads_n, toggles_per = 8, 500        # total is even -> ends back in MEMORY
    total = threads_n * toggles_per
    assert total % 2 == 0

    collected: list[bool] = []
    guard = threading.Lock()

    def worker():
        local = [st.toggle_dream() for _ in range(toggles_per)]
        with guard:
            collected.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert all(not t.is_alive() for t in threads)
    assert len(collected) == total
    # Serialized by the lock, the atomic flips strictly alternate T,F,T,F...
    # from MEMORY: exactly half enter Dream (True), half leave it (False).
    # A lost update from a non-atomic check-then-act would skew these counts
    # and leave a torn final mode.
    assert collected.count(True) == total // 2
    assert collected.count(False) == total // 2
    assert not st.is_dream()               # even # of atomic flips -> MEMORY
    assert st.mode in ("MEMORY", "DREAM")


def test_host_state_equality_ignores_lock_field():
    # the injected _lock must not break HostState's value semantics
    assert HostState() == HostState()
    a, b = HostState(), HostState()
    a.enter_dream()
    assert a != b
    a.exit_dream()
    assert a == b
