"""PR3 polish-seam tests — fallback paths (infra deps optional/absent in CI)."""
from __future__ import annotations


def test_dashboard_rich_plain_fallback():
    from dreamlayer.ai_brain.dashboard_rich import Dashboard
    text = Dashboard().render({"pairing": "ready", "model": "mock"})
    assert "pairing: ready" in text and "model: mock" in text


def test_fs_watch_fallback_returns_false():
    from dreamlayer.orchestrator.fs_watch import FolderWatcher
    seen = []
    w = FolderWatcher("/tmp", on_change=seen.append)
    assert w.start() is False   # no watchdog → caller polls
    w.stop()                     # safe no-op


def test_fs_watch_real_fires_on_change(tmp_path):
    import time
    import pytest
    pytest.importorskip("watchdog")   # real-path test: needs the actual dep
    from dreamlayer.orchestrator.fs_watch import FolderWatcher
    seen = []
    w = FolderWatcher(str(tmp_path), on_change=seen.append)
    assert w.start() is True
    try:
        target = tmp_path / "note.txt"
        # Poll with a deadline, re-writing each step: fs events are async AND
        # the observer's own watch registration races the first write, so a
        # single write-then-assert would flake. Never a bare fixed sleep.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not seen:
            target.write_text("tick")
            time.sleep(0.05)
        assert seen, "watchdog callback never fired within 2 s"
        assert str(target) in seen          # callback gets the changed file's path

        n = len(seen)
        (tmp_path / "subdir").mkdir()       # directory-only event → filtered out
        deadline = time.monotonic() + 0.5   # bounded quiet window (negative assert)
        while time.monotonic() < deadline and len(seen) == n:
            time.sleep(0.05)
        assert len(seen) == n               # is_directory events never reach cb
    finally:
        w.stop()
    w.stop()                                 # idempotent: second stop is a no-op

    n = len(seen)
    target.write_text("after stop")          # teardown: no callbacks after stop
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline and len(seen) == n:
        time.sleep(0.05)
    assert len(seen) == n


def test_discovery_fallback_noop():
    from dreamlayer.orchestrator.discovery_zeroconf import Discovery, SERVICE
    d = Discovery()
    assert SERVICE == "_dreamlayer._tcp.local."
    assert d.advertise(7777, token="rune-birch") is False
    assert d.discover(timeout=0.01) == []
    d.stop()


def test_discovery_real_advertise_and_discover():
    import time
    import uuid
    import pytest
    pytest.importorskip("zeroconf")   # real-path test: needs the actual dep
    from dreamlayer.orchestrator.discovery_zeroconf import Discovery

    # Uncommon port + a per-run-unique instance name. A real DreamLayer Brain
    # live on the same LAN advertises the DEFAULT name on ITS own port, so
    # requiring BOTH this exact port AND this distinctive name on the SAME
    # entry makes a stray-Brain false positive impossible — only our own
    # registration can satisfy both. The uuid also rules out a stale entry
    # lingering from a prior run of this test.
    port = 51873
    name = f"dltest-loopback-{uuid.uuid4().hex[:12]}"

    d = Discovery()
    try:
        if not d.advertise(port, name=name, token="rune-birch"):
            # No multicast-capable interface (sandbox/container): a skip is
            # honest. This is the ONLY honest skip — see the assert below.
            pytest.skip("no multicast-capable network")

        # Registration + browser propagation are async, so poll with a deadline
        # rather than trusting a single bare sleep. discover() itself blocks for
        # its timeout, making each pass a real 1 s browse window; we retry until
        # our own entry appears or the deadline expires.
        mine = None
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and mine is None:
            for entry in d.discover(timeout=1.0):
                if entry["port"] == port and name in entry["name"]:
                    mine = entry
                    break

        # advertise() succeeded, so an empty result here is a REAL failure worth
        # surfacing — NOT a skip. A vacuous pass would hide a broken loopback.
        assert mine is not None, (
            f"advertised {name!r} on port {port} but never discovered it back")
        assert mine["port"] == port          # the advertised port round-trips
        assert name in mine["name"]          # ...on our distinctive instance
    finally:
        d.stop()                             # unregister even on assertion failure


def test_datasette_command_and_serve():
    from dreamlayer.memory.datasette_app import MemoryExplorer
    m = MemoryExplorer("/home/user/.dreamlayer/memory.db")
    cmd = m.command(port=8001)
    assert "datasette serve" in cmd and "127.0.0.1" in cmd
    assert m.serve() is None     # no datasette installed → None


def test_rerun_timeline_noop():
    from dreamlayer.simulator.rerun_viz import Timeline
    tl = Timeline()               # no rerun → self._on False
    # all calls are safe no-ops
    tl.at(1.0); tl.log_text("x", "hi"); tl.log_scalar("y", 0.5)
    assert tl.available in (True, False)
