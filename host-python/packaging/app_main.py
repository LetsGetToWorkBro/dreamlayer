"""app_main.py — the bundled entry for the double-click DreamLayer Brain app.

One entry, two shells: bundled by ``host-python/packaging/setup_app.py``
(py2app → the macOS menu-bar app) and by
``host-python/packaging/windows/DreamLayer.spec`` (PyInstaller → the Windows
system-tray app). A single process that:
  1. starts the Brain HTTP server on a background daemon thread, then
  2. runs the platform appliance UI on the main thread (rumps menu bar on
     macOS, pystray tray on Windows — each must own main).

State lives in ``~/.dreamlayer`` exactly like ``python -m dreamlayer.ai_brain.server``
— the bundle ships no user data and writes nothing inside itself, so it works
read-only from /Applications or Program Files. On first run it mints a pairing
token if none is set.

Extra Windows-only entry modes (dispatched before the server starts):
  --panel-window <url>   run the native WebView2 panel window (the tray
                         re-invokes the exe with this; see
                         ai_brain/webview_window_windows.py)
  --smoke                start the server, wait until it answers, exit 0 —
                         the CI smoke launch (works on every platform)
"""
from __future__ import annotations

import os
import platform
import secrets
import sys
import threading
import time
from pathlib import Path


def _cfg_dir(argv: list[str] | None = None) -> str:
    return (_flag(argv or [], "--dir")
            or os.environ.get("DREAMLAYER_DIR", str(Path.home() / ".dreamlayer")))


def _flag(argv: list[str], name: str) -> str | None:
    """A tolerant `--flag value` reader — the app must also swallow launcher
    noise like Finder's -psn_… argument, so no argparse here."""
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def _serve(cfg_dir: str, port: int) -> None:
    """Build the Brain and serve forever (runs on a background daemon thread)."""
    from dreamlayer.ai_brain.server.server import Brain, make_brain_server
    brain = Brain(cfg_dir)
    if not brain.config.token:                     # first run — mint a pairing token
        brain.config.token = secrets.token_hex(8)
        brain.save()
    brain.start_watching()                         # reindex watched folders on change
    brain.start_brief_scheduler()                  # morning brief at brief_hour
    brain.start_calendar_sync()                    # calendar → agenda (per-platform source)
    make_brain_server(brain, host="0.0.0.0", port=port).serve_forever()


def _smoke(port: int) -> int:
    """Wait until the server answers on loopback, then exit — the CI
    approximation of 'double-click → panel reachable'."""
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with opener.open(f"http://127.0.0.1:{port}/", timeout=2) as r:
                if r.status == 200:
                    return 0
        except Exception:
            time.sleep(0.5)
    return 1


def main() -> int:
    argv = sys.argv[1:]
    # Windows panel-window child: the tray re-invokes this exe to host the
    # WebView2 window in its own process. Dispatch before anything else so a
    # second server never starts.
    if "--panel-window" in argv:
        from dreamlayer.ai_brain.webview_window_windows import run_panel_window
        return run_panel_window(_flag(argv, "--panel-window") or "")
    # windowed apps have no console — this routes logs to <state>/brain.log
    # there and is a formatting no-op where a console exists (logging_setup)
    from dreamlayer.logging_setup import configure_logging
    configure_logging()
    cfg_dir = _cfg_dir(argv)
    port = int(_flag(argv, "--port") or os.environ.get("DREAMLAYER_PORT", "7777"))
    Path(cfg_dir).mkdir(parents=True, exist_ok=True)
    threading.Thread(target=_serve, args=(cfg_dir, port), daemon=True).start()
    if "--smoke" in argv:
        return _smoke(port)
    time.sleep(1.0)                                # let the socket bind before polling
    if platform.system() == "Windows":
        from dreamlayer.ai_brain.tray_windows import run_tray
        return run_tray(cfg_dir, port)
    from dreamlayer.ai_brain.menubar import run_menubar
    return run_menubar(cfg_dir, port)


if __name__ == "__main__":
    raise SystemExit(main())
