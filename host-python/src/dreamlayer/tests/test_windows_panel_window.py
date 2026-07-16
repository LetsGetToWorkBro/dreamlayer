"""test_windows_panel_window.py — the Windows native panel window contract.

Mirrors the macOS webview_window contract: guarded imports, loads-and-no-ops
off-platform, any failure returns False so the caller falls back to the
browser. The window spec (title, size, minimum size) is pinned to the macOS
panel window's values so the product feels identical on both.
"""
from __future__ import annotations

import sys

import pytest

from dreamlayer.ai_brain import webview_window_windows as ww


def test_window_spec_matches_the_macos_panel_window():
    # webview_window.py builds NSMakeRect(0, 0, 940, 760) with a 560x480
    # minimum and the title "DreamLayer" — the twins must not drift.
    assert ww.WINDOW_TITLE == "DreamLayer"
    assert ww.WINDOW_SIZE == (940, 760)
    assert ww.WINDOW_MIN_SIZE == (560, 480)


def test_open_panel_window_noops_off_windows():
    if sys.platform == "win32":
        pytest.skip("this asserts the off-Windows no-op")
    assert ww.open_panel_window("http://127.0.0.1:7777/") is False


def test_panel_window_command_source_and_frozen():
    src = ww.panel_window_command("http://x/", executable="py", frozen=False)
    assert src == ["py", "-m", "dreamlayer.ai_brain.webview_window_windows",
                   "http://x/"]
    frz = ww.panel_window_command("http://x/", executable="DreamLayer.exe",
                                  frozen=True)
    assert frz == ["DreamLayer.exe", "--panel-window", "http://x/"]


def test_run_panel_window_builds_the_shared_window_spec():
    calls = {}

    class FakeWebview:
        @staticmethod
        def create_window(title, url, width=0, height=0, min_size=None):
            calls.update(title=title, url=url, width=width, height=height,
                         min_size=min_size)

        @staticmethod
        def start():
            calls["started"] = True

    rc = ww.run_panel_window("http://127.0.0.1:7777/",
                             webview_module=FakeWebview)
    assert rc == 0 and calls["started"] is True
    assert calls["title"] == "DreamLayer"
    assert (calls["width"], calls["height"]) == (940, 760)
    assert calls["min_size"] == (560, 480)
    assert calls["url"] == "http://127.0.0.1:7777/"


def test_run_panel_window_returns_1_when_webview_fails():
    class Boom:
        @staticmethod
        def create_window(*a, **k):
            raise RuntimeError("no WebView2 runtime")

        @staticmethod
        def start():                              # pragma: no cover
            pass

    assert ww.run_panel_window("http://x/", webview_module=Boom) == 1


def test_run_panel_window_returns_1_without_pywebview(monkeypatch):
    # simulate pywebview being absent (it isn't a dependency on CI/Linux)
    import builtins
    real_import = builtins.__import__

    def no_webview(name, *a, **kw):
        if name == "webview":
            raise ImportError("no pywebview here")
        return real_import(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", no_webview)
    assert ww.run_panel_window("http://x/") == 1
