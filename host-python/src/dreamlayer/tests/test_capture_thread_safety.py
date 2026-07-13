"""P0-2: a spoken commitment is never confirmed unless it was actually saved.

Capture runs on a daemon thread (mic -> VAD -> ASR -> ingest_caption), so the
commitment write happens off the thread that built the DB. The old code opened
SQLite with the default check_same_thread=True and swallowed the resulting
ProgrammingError with a bare `except: pass`, then *still* flashed the
"commitment captured" card — the wearer was told a promise was kept while zero
rows were written. These tests pin: (1) the write survives the thread hop, and
(2) a failed write yields no card and a health-ledger record instead.
"""
from __future__ import annotations

import threading

from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.tests.test_integration_dream_suite import FakeBridge

PROMISE = "I'll send Jordan the invoice by Friday"


def _commitment_cards(bridge):
    return [f for f in bridge.raw
            if f.get("t") == "card" and f.get("type") == "CommitmentRecallCard"]


def test_commitment_captured_off_thread_actually_persists():
    orc = Orchestrator(FakeBridge())
    err = []

    def worker():
        try:
            orc.ingest_caption(PROMISE, speaker="me")
        except Exception as exc:            # the old bug raised here (swallowed)
            err.append(exc)

    t = threading.Thread(target=worker)
    t.start(); t.join(timeout=5)
    assert not t.is_alive()
    assert not err, f"capture raised across the thread boundary: {err}"

    rows = orc.db.commitments()
    assert any("invoice" in r["task"] for r in rows), "the promise was lost"
    assert _commitment_cards(orc.bridge), "no confirmation for a real capture"


def test_failed_write_yields_no_card_and_records_health():
    orc = Orchestrator(FakeBridge())

    def boom(*a, **k):
        raise RuntimeError("disk full")
    orc.db.add_commitment = boom          # force the write to fail

    before = orc.health.failures("capture:commitment")
    orc.ingest_caption(PROMISE, speaker="me")

    # the honest outcome: no "captured" card, and the failure is on the ledger
    assert _commitment_cards(orc.bridge) == []
    assert orc.health.failures("capture:commitment") == before + 1
    assert orc.db.commitments() == []


def test_concurrent_captures_all_land():
    # many promises from many threads — the lock must serialize every write
    orc = Orchestrator(FakeBridge())
    people = [f"P{i}" for i in range(12)]

    def worker(who):
        orc.ingest_caption(f"I'll send {who} the report by Monday", speaker="me")

    threads = [threading.Thread(target=worker, args=(w,)) for w in people]
    for t in threads: t.start()
    for t in threads: t.join(timeout=5)
    assert all(not t.is_alive() for t in threads)
    assert len(orc.db.commitments()) == len(people)
