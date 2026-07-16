"""Native panel window (Windows) — a WebView2 window showing the Brain control
panel, so the app has a real window (like a VPN app) instead of opening the
browser. The Windows twin of webview_window.py (macOS).

Uses pywebview, which on Windows drives Microsoft Edge WebView2 — the
OS-provided engine (ships with Windows 11, auto-repairable on 10) — so the
dependency is one small package with no bundled browser; that's the lightest
option that gives a real native window (the raw WebView2 COM bindings need
pythonnet + hand-rolled window plumbing for no gain here).

Unlike the macOS version — which rides the AppKit run loop rumps already owns —
pywebview's event loop must own a main thread, and the tray (pystray) owns
ours. So the window runs in its OWN child process: no second event loop to
fight, and a crashed window can't take the appliance down. Windows-only: every
import and call is guarded so this module loads (and no-ops) on macOS/Linux/CI,
and any failure returns False so the caller can fall back to the browser.
"""
from __future__ import annotations

import subprocess
import sys
import time
from importlib.util import find_spec

# same window contract as the macOS panel window (webview_window.py), so the
# product feels identical on both: title, size, minimum size.
WINDOW_TITLE = "DreamLayer"
WINDOW_SIZE = (940, 760)
WINDOW_MIN_SIZE = (560, 480)

# A module-level handle so "open" is idempotent: while the child window lives,
# a second click focuses it instead of stacking windows (the macOS twin keeps
# the NSWindow around for the same reason).
_child: subprocess.Popen | None = None


def panel_window_command(url: str, executable: str | None = None,
                         frozen: bool | None = None) -> list[str]:
    """The argv that opens the panel window in its own process (pure).

    Bundled app (PyInstaller): re-invoke the exe with ``--panel-window`` —
    packaging/app_main.py dispatches that flag here before starting a second
    server. Source install: run this module.
    """
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    exe = executable or sys.executable
    if frozen:
        return [exe, "--panel-window", url]
    return [exe, "-m", "dreamlayer.ai_brain.webview_window_windows", url]


def _focus_existing(title: str) -> bool:
    """Bring the already-open panel window to the front (best-effort)."""
    if sys.platform != "win32":            # pragma: no cover — win32 only
        return True
    try:
        import ctypes
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 9)          # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return True     # the window exists; failing to raise it is cosmetic


def open_panel_window(url: str, title: str = WINDOW_TITLE) -> bool:
    """Open — or focus, if already open — a native window showing `url`.

    Returns True on success, False if native windowing isn't available (the
    caller should then fall back to opening a browser). Same contract as the
    macOS open_panel_window.
    """
    global _child
    if sys.platform != "win32":
        return False
    try:
        # already open → bring to front (the URL never changes underneath it)
        if _child is not None and _child.poll() is None:
            return _focus_existing(title)
        if find_spec("webview") is None:            # pywebview not installed
            return False
        cmd = panel_window_command(url)
        # CREATE_NO_WINDOW: never flash a console; the child is a GUI process
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        _child = subprocess.Popen(cmd, creationflags=flags,
                                  close_fds=True)
        # If the window process dies immediately (WebView2 runtime missing,
        # display-less session), report failure so the caller falls back to
        # the browser instead of silently showing nothing.
        deadline = time.time() + 1.5
        while time.time() < deadline:
            if _child.poll() is not None:
                ok = _child.returncode == 0
                _child = None
                return ok
            time.sleep(0.1)
        return True
    except Exception:
        _child = None
        return False


def run_panel_window(url: str, title: str = WINDOW_TITLE,
                     webview_module=None) -> int:
    """The child process's main: one WebView2 window, blocking until closed.

    `webview_module` is an injectable seam so the window spec (title, size,
    minimum size — the parts shared with macOS) is unit-testable without a
    display; None means the real pywebview.
    """
    wv = webview_module
    if wv is None:
        try:
            import webview
        except Exception:
            return 1
        wv = webview
    try:
        w, h = WINDOW_SIZE
        wv.create_window(title, url, width=w, height=h,
                         min_size=WINDOW_MIN_SIZE)
        wv.start()
        return 0
    except Exception:
        return 1


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="DreamLayer Brain panel window (Windows / WebView2)")
    ap.add_argument("url")
    ap.add_argument("--title", default=WINDOW_TITLE)
    args = ap.parse_args(argv)
    return run_panel_window(args.url, args.title)


if __name__ == "__main__":
    raise SystemExit(main())
