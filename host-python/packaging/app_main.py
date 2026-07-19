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

import logging
import os
import platform
import secrets
import sys
import threading
import time
import webbrowser
from pathlib import Path

# The single-instance lock lives in the state dir; holding it is what makes a
# 2nd launch back off instead of racing the busy port.
LOCK_FILE = "dreamlayer.lock"
_INSTANCE_LOCK: list = []          # keeps the live lock handle for process life


def _cfg_dir(argv: list[str] | None = None) -> str:
    return (_flag(argv or [], "--dir")
            or os.environ.get("DREAMLAYER_DIR", str(Path.home() / ".dreamlayer")))


def acquire_single_instance_lock(lock_dir: str):
    """Acquire an exclusive OS lock on ``<lock_dir>/dreamlayer.lock``.

    Returns an opaque handle (the lock is held only while the handle stays
    open) when this is the sole running instance, or ``None`` ONLY when another
    instance already HOLDS the lock (the contended/would-block case). POSIX uses
    ``fcntl.flock``, Windows uses ``msvcrt.locking`` — both non-blocking, so a
    second launch fails fast instead of waiting.

    A failure to create/open the lock file itself (permission denied, read-only
    mount) is a DISTINCT failure and propagates as ``OSError`` — it must NOT be
    mistaken for "already running". Conflating the two made an unwritable state
    dir look like a second instance, so the app printed "already running", opened
    a URL to a server that never came up, and exited 0 — masking the real failure
    (audit 2026-07-17). The lock dir is injected so the guard is unit-testable."""
    # mkdir/open failures propagate as OSError (create/open failure), which the
    # caller handles distinctly from a held lock — do NOT swallow them to None.
    Path(lock_dir).mkdir(parents=True, exist_ok=True)
    fh = open(Path(lock_dir) / LOCK_FILE, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None                 # the lock is genuinely HELD → back off
    return fh


def _flag(argv: list[str], name: str) -> str | None:
    """A tolerant `--flag value` reader — the app must also swallow launcher
    noise like Finder's -psn_… argument, so no argparse here."""
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def _serve(cfg_dir: str, port: int, status: dict | None = None) -> None:
    """Build the Brain and serve forever (runs on a background daemon thread).

    A bind failure (port already in use, etc.) must NOT die silently on this
    daemon thread: a windowed build has ``sys.stderr is None``, so the traceback
    goes nowhere and the UI would keep authenticating against a server that
    never came up. Catch the startup/bind failure, log it, and record it in
    ``status`` so the main thread can surface it and exit instead of running the
    UI against a dead server (audit 2026-07-17)."""
    from dreamlayer.ai_brain.server.server import Brain, make_brain_server
    brain = Brain(cfg_dir)
    if not brain.config.token:                     # first run — mint a pairing token
        # 128-bit, matching ai_brain.server.__main__ (which mints token_hex(16)
        # before a non-loopback bind). This appliance binds 0.0.0.0 below, so
        # the token is network-exposed and must not be weaker than the
        # launcher's — the prior 64-bit mint was brute-forceable by comparison
        # (audit 2026-07-17).
        brain.config.token = secrets.token_hex(16)
        brain.save()
    brain.start_watching()                         # reindex watched folders on change
    brain.start_brief_scheduler()                  # morning brief at brief_hour
    brain.start_calendar_sync()                    # calendar → agenda (per-platform source)
    # Auto-start the https sibling the Live Lens camera needs. This appliance
    # binds 0.0.0.0 (the phone must reach it), and a phone browser opens its
    # camera only on a SECURE context — so http-only made scanning the Live Lens
    # QR appear to "do nothing" (the page loaded, the camera never started). The
    # bundled app ships `cryptography`, so this normally succeeds; if it ever
    # can't, it degrades to http-only rather than failing to launch.
    tls_port = 0
    try:
        from dreamlayer.ai_brain.server.tls import start_tls_sibling
        _tls_server, tls_port = start_tls_sibling(brain, "0.0.0.0", cfg_dir, port)
    except Exception as exc:                        # noqa: BLE001 — never block launch
        logging.getLogger("dreamlayer.appliance").warning(
            "Live Lens https listener not started (%s); serving http only.", exc)
    try:
        server = make_brain_server(brain, host="0.0.0.0", port=port,
                                   tls_port=tls_port or None)
    except Exception as exc:                        # bind failed (port in use, …)
        logging.getLogger("dreamlayer.appliance").error(
            "Brain server failed to start on port %s: %s", port, exc)
        if status is not None:
            status["error"] = exc
        return
    if status is not None:
        status["bound"] = True
        status["tls_port"] = tls_port
    server.serve_forever()


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
                time.sleep(0.5)      # 2xx-non-200 (e.g. 204): don't spin tight
        except Exception:
            time.sleep(0.5)
    return 1


def _wait_ready(port: int, status: dict | None = None,
                timeout: float = 20.0) -> bool:
    """Poll loopback until the server answers (socket bound AND the pairing
    token minted/persisted), the serve thread reports a startup error, or the
    timeout elapses. This replaces a fixed 1.0s sleep that raced the token
    mint — on a slow first run the UI launched before the token was persisted,
    cached an empty token, and showed a permanently grey dot. Returns True when
    the server is ready."""
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        if status is not None and status.get("error") is not None:
            return False
        try:
            with opener.open(f"http://127.0.0.1:{port}/", timeout=1) as r:
                if r.status == 200:
                    return True
                time.sleep(0.1)      # 2xx-non-200 (e.g. 204): don't spin tight
        except Exception:
            time.sleep(0.1)
    return False


def _focus_existing(port: int) -> None:
    """Best-effort: bring the already-running instance's panel forward by
    opening its local URL (the OS focuses the existing window/tab)."""
    try:
        webbrowser.open(f"http://127.0.0.1:{port}/")
    except Exception:
        pass


def _already_running(port: int) -> None:
    logging.getLogger("dreamlayer.appliance").warning(
        "DreamLayer is already running — focusing the existing instance and "
        "exiting instead of starting a second server.")
    _focus_existing(port)


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

    # Put the pack sidecar (<cfg>/site-packages) on sys.path BEFORE the server
    # builds, so a capability pack the wearer installed one-click into the sealed
    # bundle (which can't modify itself) is importable this run.
    try:
        from dreamlayer.capabilities import enable_pack_site
        enable_pack_site(cfg_dir)
    except Exception:                              # never block launch on this
        pass

    # Single-instance guard: take an exclusive OS lock BEFORE starting a server.
    # Without it a 2nd launch hits the busy port :7777, its _serve daemon thread
    # dies SILENTLY (windowed build → sys.stderr is None), yet the tray/menubar
    # still comes up as a 2nd icon talking to the 1st instance. If the lock is
    # already held the appliance is running: surface it, focus the existing
    # window, and exit cleanly (audit 2026-07-17).
    try:
        lock = acquire_single_instance_lock(cfg_dir)
    except OSError as exc:
        # DISTINCT failure: the lock file couldn't be created/opened (permission
        # denied, read-only mount) — this is NOT "already running". A false
        # "already running" here would focus a nonexistent instance and exit 0,
        # masking an unwritable state dir. Log it and fail OPEN — start the server
        # anyway (without the guard) so the app still runs (audit 2026-07-17).
        logging.getLogger("dreamlayer.appliance").error(
            "Single-instance lock unavailable in %s (%s); starting without it.",
            cfg_dir, exc)
        lock = None
    else:
        if lock is None:                           # the lock is genuinely HELD
            _already_running(port)
            return 0
        _INSTANCE_LOCK.append(lock)                # hold the lock for process life

    status: dict = {}
    threading.Thread(target=_serve, args=(cfg_dir, port, status),
                     daemon=True).start()
    if "--smoke" in argv:
        return _smoke(port)
    # Wait for readiness instead of a fixed sleep, so the UI never launches
    # before the token is minted. If the server failed to bind, surface it and
    # exit rather than running the UI against a dead server.
    if not _wait_ready(port, status):
        if status.get("error") is not None:
            logging.getLogger("dreamlayer.appliance").error(
                "Not starting the UI: the Brain server did not come up (%s).",
                status["error"])
            return 1
        logging.getLogger("dreamlayer.appliance").warning(
            "Brain server slow to answer; starting the UI anyway.")
    if platform.system() == "Windows":
        from dreamlayer.ai_brain.tray_windows import run_tray
        return run_tray(cfg_dir, port)
    from dreamlayer.ai_brain.menubar import run_menubar
    return run_menubar(cfg_dir, port)


if __name__ == "__main__":
    raise SystemExit(main())
