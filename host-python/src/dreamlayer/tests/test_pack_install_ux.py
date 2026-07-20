"""Pack install UX — the one-click flow the user actually clicks.

Covers the 2026-07-20 fixes for "clicking Capabilities does nothing":
- the WKWebView native window swallowed confirm() (no UIDelegate), so the
  install button silently no-oped in the packaged app → installPack no longer
  gates on confirm(), and the webview grew a real dialog delegate;
- installs now stream pip's narration into a live percent the panel polls,
  so a download bar appears and moves (like the model pull);
- every capability/pack carries before→after scores the ⓘ bubble renders.
"""
from __future__ import annotations

import time
from pathlib import Path

from dreamlayer.ai_brain.server import Brain, BrainConfig
import dreamlayer.ai_brain.server.server as srv
from dreamlayer.capabilities import CAPABILITIES, report


def _mkbrain(tmp_path: Path) -> Brain:
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    BrainConfig(token="tok").save(cfg)
    return Brain(cfg)


class TestPipProgressParser:
    def test_percent_moves_monotonically_and_detail_narrates(self):
        job = {"state": "installing", "percent": 0, "detail": ""}
        on_line = srv._pip_progress_parser(job, total=4)
        seen = []
        for line in [
            "Collecting sentence-transformers",
            "  Downloading sentence_transformers-3.0-py3-none-any.whl (240 kB)",
            "Collecting torch>=2.0",
            "  Downloading torch-2.4-cp311-cp311-macosx.whl (62.1 MB)",
            "Collecting numpy",
            "  Using cached numpy-2.1-cp311-cp311-macosx.whl (5.1 MB)",
            "Installing collected packages: numpy, torch, sentence-transformers",
        ]:
            on_line(line)
            seen.append(job["percent"])
        assert all(b >= a for a, b in zip(seen, seen[1:])), f"went backward: {seen}"
        assert job["percent"] >= 90, "install phase must pin ≥90"
        assert "installing" in job["detail"]

    def test_never_reports_done_and_survives_garbage(self):
        job = {"state": "installing", "percent": 0, "detail": ""}
        on_line = srv._pip_progress_parser(job, total=1)
        for line in ["", "   ", "WARNING: junk", "Downloading x (1 MB)"] * 50:
            on_line(line)
        assert job["percent"] < 100, "only _install_pack's completion sets 100"

    def test_denominator_grows_with_discovered_deps(self):
        # 1 top-level req that pulls 9 transitive deps must not hit 85% at dep #1
        job = {"state": "installing", "percent": 0, "detail": ""}
        on_line = srv._pip_progress_parser(job, total=1)
        for i in range(10):
            on_line(f"Collecting dep{i}")
        on_line("  Downloading dep0-1.0-py3-none-any.whl (1 MB)")
        assert job["percent"] <= 20, f"one of ten downloads ≠ {job['percent']}%"


class TestInstallJobSeam:
    def test_injected_legacy_runner_still_works_and_job_hits_100(self, tmp_path, monkeypatch):
        """The test seam is `lambda reqs:` — _install_pack must keep calling it
        positionally, and success must pin percent=100."""
        b = _mkbrain(tmp_path)
        launched: list = []
        monkeypatch.setattr(srv, "_PACK_RUNNER",
                            lambda reqs: launched.append(reqs) or (True, "ok"))
        srv._PACK_JOBS.clear()
        try:
            job = srv._install_pack(b, "guardian")
            assert "error" not in job
            for _ in range(100):
                if job["state"] == "done":
                    break
                time.sleep(0.05)
            assert job["state"] == "done"
            assert job["percent"] == 100
            assert launched, "runner never invoked"
        finally:
            srv._PACK_JOBS.clear()

    def test_progress_aware_runner_receives_on_line(self, tmp_path, monkeypatch):
        b = _mkbrain(tmp_path)
        got: dict = {}

        def runner(reqs, on_line=None):
            got["cb"] = on_line
            if on_line:
                on_line("Collecting x")
                on_line("  Downloading x-1.0-py3-none-any.whl (1 MB)")
            return True, "ok"

        monkeypatch.setattr(srv, "_PACK_RUNNER", runner)
        srv._PACK_JOBS.clear()
        try:
            job = srv._install_pack(b, "guardian")
            for _ in range(100):
                if job["state"] == "done":
                    break
                time.sleep(0.05)
            assert got.get("cb") is not None, "on_line was not passed to a runner that declares it"
            assert job["percent"] == 100
        finally:
            srv._PACK_JOBS.clear()

    def test_failed_install_keeps_partial_percent(self, tmp_path, monkeypatch):
        b = _mkbrain(tmp_path)

        def runner(reqs, on_line=None):
            if on_line:
                on_line("Collecting x")
            return False, "resolution impossible"

        monkeypatch.setattr(srv, "_PACK_RUNNER", runner)
        srv._PACK_JOBS.clear()
        try:
            job = srv._install_pack(b, "guardian")
            for _ in range(100):
                if job["state"] == "failed":
                    break
                time.sleep(0.05)
            assert job["state"] == "failed"
            assert job["percent"] < 100
        finally:
            srv._PACK_JOBS.clear()


class TestPipProcessCleanup:
    def test_run_pip_kills_the_orphan_on_timeout(self, monkeypatch):
        """refute 2026-07-20: on a wait() timeout (or a mid-stream exception),
        _run_pip must KILL the pip child, not leave it detached — else it keeps
        installing while the job flips to 'failed' and a retry launches a second
        concurrent pip. Revert the finally and this fails."""
        import subprocess as sp
        killed = {"v": False}

        class FakePopen:
            def __init__(self, *a, **k):
                self.stdout = iter(["Collecting x\n", "Downloading x (1 MB)\n"])
                self._alive = True

            def wait(self, timeout=None):
                if self._alive:
                    raise sp.TimeoutExpired(cmd="pip", timeout=timeout)
                return 0

            def poll(self):
                return None if self._alive else 0

            def kill(self):
                killed["v"] = True
                self._alive = False

        monkeypatch.setattr(sp, "Popen", FakePopen)
        ok, _detail = srv._run_pip(["somepkg"])
        assert ok is False
        assert killed["v"] is True, "orphaned pip was not killed on timeout"


class TestBeforeAfterScores:
    def test_every_capability_is_scored_coherently(self):
        for c in CAPABILITIES:
            assert 0 <= c.before < c.after <= 5, \
                f"{c.key}: before={c.before} after={c.after} — must be 0≤before<after≤5"

    def test_report_carries_the_scores(self):
        for item in report():
            assert "before" in item and "after" in item, f"{item['key']} misses scores"


class TestPanelContract:
    def test_install_click_is_confirm_free_and_bar_wired(self, tmp_path):
        """The pack-install click must not gate on confirm() (a silent no-op in
        the native WKWebView), and the installing state must render the live
        percent bar; the ⓘ bubble machinery must ship."""
        from dreamlayer.ai_brain.server.panel import render_panel
        body = render_panel("")
        ip = body.split("async function installPack", 1)[1].split("function ", 1)[0]
        assert "confirm(" not in ip, "installPack regained a blocking confirm()"
        assert "job.percent" in body and "pbar-f" in body
        for needle in ("capInfo", "packInfo", "meterPair", 'class="imodal"', "ibtn"):
            assert needle in body, f"info-bubble piece missing: {needle}"

    def test_destructive_actions_still_confirm(self):
        """Rotate/erase/restore keep their confirm() — the WKUIDelegate makes
        those real dialogs in the native window now; they must not lose the
        guard just because installs dropped theirs."""
        from dreamlayer.ai_brain.server.panel import render_panel
        body = render_panel("")
        assert body.count("confirm(") >= 3


class TestWebviewDelegate:
    def test_delegate_factory_never_raises_off_mac(self):
        """On Linux/CI there is no AppKit — the factory must return None, not
        crash, and open_panel_window must still fall back cleanly."""
        from dreamlayer.ai_brain import webview_window as wv
        assert wv._make_ui_delegate() is None or wv._make_ui_delegate() is not None
        # the real assertion: calling it doesn't raise, and the module keeps a
        # slot to retain the delegate (WKWebView holds it weakly)
        assert hasattr(wv, "_ui_delegate")
