"""test_world_check.py — the world check made fast: cache, deadline, off-path.

WorldChecker never blocks the caption pipeline, never asks twice, and gives a
slow tier a hard deadline. These tests pin all three, plus the Veritas
`world=False` / `world_result` split and the orchestrator's async delivery.
"""
from __future__ import annotations

import threading
import time

from dreamlayer.ai_brain.world_check import WorldChecker
from dreamlayer.orchestrator.veritas import Veritas
from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


DISPUTED = "VERDICT: DISPUTED — Canberra is the capital of Australia."


def _factcards(br):
    return [f for f in br.raw if f.get("t") == "card" and f.get("type") == "FactCheckCard"]


# -- the cache ----------------------------------------------------------------

def test_second_ask_is_served_from_cache():
    calls = {"n": 0}

    def ask(_q):
        calls["n"] += 1
        return DISPUTED

    wc = WorldChecker()
    a = wc.check_sync("Sydney is the capital of Australia.", ask)
    b = wc.check_sync("sydney is the capital of australia", ask)   # normalised
    assert a and a["verdict"] == "disputed"
    assert b == a
    assert calls["n"] == 1                     # asked once, cached the rest


def test_cache_respects_ttl():
    clock = {"t": 1000.0}
    wc = WorldChecker(cache_ttl_s=10.0, now_fn=lambda: clock["t"])
    wc.check_sync("The tower is 330 meters.", lambda q: "VERDICT: SUPPORTED — yes")
    clock["t"] += 11.0                          # past the TTL
    calls = {"n": 0}

    def ask(_q):
        calls["n"] += 1
        return "VERDICT: SUPPORTED — yes"

    wc.check_sync("The tower is 330 meters.", ask)
    assert calls["n"] == 1                      # stale entry was re-fetched


def test_blank_claim_is_ignored():
    wc = WorldChecker()
    assert wc.check_sync("   ", lambda q: DISPUTED) is None


# -- async delivery -----------------------------------------------------------

def test_async_delivers_a_verdict_off_thread():
    got = []
    done = threading.Event()

    def ask(_q):
        time.sleep(0.02)
        return DISPUTED

    wc = WorldChecker(timeout_s=2.0)
    from_cache = wc.check_async("Sydney is the capital of Australia.", ask,
                                lambda v: (got.append(v), done.set()))
    assert from_cache is False                  # queued, not cached
    assert done.wait(2.0)
    assert got and got[0]["verdict"] == "disputed"


def test_async_second_call_is_cache_hit_inline():
    wc = WorldChecker()
    wc.check_sync("Sydney is the capital of Australia.", lambda q: DISPUTED)  # warm
    got = []
    from_cache = wc.check_async("Sydney is the capital of Australia.",
                                lambda q: DISPUTED, got.append)
    assert from_cache is True                   # served inline from cache
    assert got and got[0]["verdict"] == "disputed"


def test_deadline_drops_a_slow_answer():
    delivered = []
    done = threading.Event()

    def slow_ask(_q):
        time.sleep(0.3)
        return DISPUTED

    wc = WorldChecker(timeout_s=0.05)           # tighter than the ask
    wc.check_async("Sydney is the capital of Australia.", slow_ask,
                   lambda v: delivered.append(v))
    # give the worker time to finish and hit the deadline check
    time.sleep(0.5)
    assert delivered == []                      # too late — not delivered


def test_a_none_verdict_delivers_nothing():
    delivered = []
    wc = WorldChecker()
    wc.check_async("Let's grab lunch.", lambda q: "no verdict here",
                   lambda v: delivered.append(v))
    time.sleep(0.2)
    assert delivered == []


# -- Veritas world/offline split ----------------------------------------------

def test_world_false_takes_only_the_offline_pass():
    calls = {"n": 0}

    def verify(_c):
        calls["n"] += 1
        return {"verdict": "disputed", "basis": "no", "confidence": 0.9}

    v = Veritas(verify_fn=verify)
    # world=False must not touch the verifier at all
    res = v.check("Sydney is the capital of Australia.", speaker="Dana",
                  now=1.0, world=False)
    assert not res.fired
    assert calls["n"] == 0
    # but it still catches a self-contradiction offline
    res2 = v.check("The deal closed at 3 million.", speaker="M",
                   prior=["The deal closed at 2 million."], now=1.0, world=False)
    assert res2.fired and res2.verdict == "self_contradiction"


def test_world_result_applies_worth_and_cooldown():
    v = Veritas(per_speaker_cooldown_s=45.0)
    disputed = {"verdict": "disputed", "basis": "Canberra", "confidence": 0.95}
    a = v.world_result("Sydney is the capital.", "Dana", disputed, now=1.0)
    assert a.fired and a.verdict == "disputed"
    b = v.world_result("The moon is cheese.", "Dana", disputed, now=5.0)
    assert not b.fired                          # cooling
    assert v.world_result("x", "Dana", None, now=100.0).fired is False
    weak = {"verdict": "supported", "basis": "ok", "confidence": 0.5}
    assert v.world_result("y", "Sol", weak, now=100.0).fired is False


# -- end to end: async world check through the orchestrator -------------------

def test_orchestrator_delivers_a_world_verdict_asynchronously():
    br = FakeBridge()
    orc = Orchestrator(br)
    orc.set_factcheck(True)
    # a general-knowledge tier that disputes the claim
    orc.world_check.timeout_s = 2.0

    def ask(_q):
        class A:
            text = DISPUTED
            tier = "cloud"
            confidence = 0.9
        return A()

    orc.brain.ask = ask                         # inject a disputing tier
    orc.ingest_caption("Sydney is the capital of Australia.",
                       speaker="Dana", ts=100.0)
    # the verdict arrives off-thread; wait briefly for the worker
    for _ in range(50):
        if _factcards(br):
            break
        time.sleep(0.02)
    cards = _factcards(br)
    assert cards and cards[-1]["verdict"] == "disputed"
