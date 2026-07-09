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


def test_discovery_fallback_noop():
    from dreamlayer.orchestrator.discovery_zeroconf import Discovery, SERVICE
    d = Discovery()
    assert SERVICE == "_dreamlayer._tcp.local."
    assert d.advertise(7777, token="rune-birch") is False
    assert d.discover(timeout=0.01) == []
    d.stop()


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
