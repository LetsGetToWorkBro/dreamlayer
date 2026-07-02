"""test_object_lens_integrations.py — PolledSource + the laptop companion.

Covers the production plumbing (cache/background/stale-not-blank) and a full
round-trip over real localhost HTTP: companion server -> data_source ->
PolledSource -> LaptopProvider -> ObjectLens panel."""
from __future__ import annotations

import threading

import numpy as np
import pytest

from dreamlayer.object_lens import (
    PolledSource, humanize_age, ObjectLens, ObjectRecognizer,
    ProviderRegistry, LaptopProvider, CarProvider, ObjectSighting,
)
from dreamlayer.object_lens.integrations import (
    laptop_data_source, serve_companion, CONTEXT_PATH, TOKEN_HEADER,
)


class Clock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


def frame():
    a = np.full((16, 16), 0.6, dtype=np.float32)
    a[::2] += 0.15
    return a


# ---------------------------------------------------------------------------
# PolledSource
# ---------------------------------------------------------------------------

class TestPolledSource:
    def test_first_call_is_cold_then_fills(self):
        calls = {"n": 0}
        def fetch():
            calls["n"] += 1
            return {"battery": 80}
        src = PolledSource(fetch, ttl=10, now_fn=Clock())
        snap = src()                              # cold: kicks a fetch
        src.wait_idle()
        assert snap["_ok"] is False               # nothing yet on the first glance
        assert src()["battery"] == 80             # the fetch landed in cache
        assert src.ok() is True

    def test_ttl_caches_within_window(self):
        calls = {"n": 0}
        clock = Clock()
        def fetch():
            calls["n"] += 1
            return {"v": calls["n"]}
        src = PolledSource(fetch, ttl=30, now_fn=clock)
        src.refresh(block=True)                   # n=1
        clock.t = 10
        src(); src.wait_idle()                     # within ttl: no refetch
        assert calls["n"] == 1
        clock.t = 40                               # past ttl
        src(); src.wait_idle()
        assert calls["n"] == 2

    def test_slow_fetch_does_not_block_the_glance(self):
        gate = threading.Event()
        def fetch():
            gate.wait(2.0)
            return {"battery": 42}
        src = PolledSource(fetch, ttl=5, now_fn=Clock())
        snap = src()                              # returns immediately, still cold
        assert snap["_ok"] is False
        gate.set()
        src.wait_idle()
        assert src()["battery"] == 42

    def test_failure_keeps_last_good_and_marks_stale(self):
        state = {"ok": True}
        clock = Clock()
        def fetch():
            if not state["ok"]:
                raise RuntimeError("dongle gone")
            return {"tire_pressure": 34}
        src = PolledSource(fetch, ttl=20, now_fn=clock)
        src.refresh(block=True)
        assert src()["tire_pressure"] == 34
        state["ok"] = False
        clock.t = 25                               # stale -> refetch fails
        src.refresh(block=True)
        snap = src()
        assert snap["tire_pressure"] == 34         # last good retained
        assert snap["_stale"] is True and snap["_ok"] is True
        assert src.error() is not None

    def test_humanize_age(self):
        assert humanize_age(None) == ""
        assert humanize_age(10) == "just now"
        assert humanize_age(300) == "5m ago"
        assert humanize_age(7200) == "2h ago"


# ---------------------------------------------------------------------------
# Laptop companion — real localhost HTTP round-trip
# ---------------------------------------------------------------------------

class TestLaptopCompanion:
    def test_fetch_over_real_http(self):
        data = {"recent_files": ["notes.md", "budget.xlsx"], "battery": 82}
        comp = serve_companion(lambda: data, token="rune-birch")
        try:
            fetch = laptop_data_source(comp.url, token="rune-birch")
            got = fetch()
            assert got["battery"] == 82
            assert got["recent_files"][0] == "notes.md"
        finally:
            comp.stop()

    def test_wrong_token_is_rejected(self):
        comp = serve_companion(lambda: {"battery": 1}, token="right")
        try:
            fetch = laptop_data_source(comp.url, token="wrong")
            with pytest.raises(Exception):
                fetch()
        finally:
            comp.stop()

    def test_end_to_end_panel(self):
        """companion -> data_source -> PolledSource -> provider -> panel."""
        comp = serve_companion(
            lambda: {"recent_files": ["Q3-plan.md"], "battery": 77},
            token="tok")
        try:
            src = PolledSource(laptop_data_source(comp.url, token="tok"), ttl=30)
            src.refresh(block=True)                # fill the cache once
            lens = ObjectLens(
                recognizer=ObjectRecognizer(classify_fn=lambda _f: ("laptop", 0.9, {})),
                registry=ProviderRegistry([LaptopProvider(src)]))
            panel = lens.look(frame())
            assert panel is not None and panel.title == "laptop"
            assert any(r.detail == "Q3-plan.md" for r in panel.rows)
            assert any(r.value == "77%" for r in panel.rows)
        finally:
            comp.stop()

    def test_stale_snapshot_shows_age(self):
        clock = Clock()
        state = {"ok": True}
        def fetch():
            if not state["ok"]:
                raise RuntimeError("dongle gone")
            return {"tire_pressure": 30}
        src = PolledSource(fetch, ttl=60, now_fn=clock)
        src.refresh(block=True)                    # fresh at t=0
        clock.t = 7200                             # 2h later
        state["ok"] = False                        # refetch can't succeed -> stays stale
        rows = CarProvider(src).build(ObjectSighting("car", 0.9))
        assert any(r.value == "30 psi" for r in rows)   # last good retained
        assert any(r.detail == "2h ago" for r in rows)  # ...marked stale
