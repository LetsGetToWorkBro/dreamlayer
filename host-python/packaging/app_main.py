"""app_main.py — py2app entry for the double-click DreamLayer Brain menu-bar app.

Bundled by ``host-python/packaging/setup_app.py``. A single process that:
  1. starts the Brain HTTP server on a background daemon thread, then
  2. runs the rumps menu-bar UI on the main thread (rumps must own main).

State lives in ``~/.dreamlayer`` exactly like ``python -m dreamlayer.ai_brain.server``
— the bundle ships no user data and writes nothing inside itself, so it works
read-only from /Applications. On first run it mints a pairing token if none is set.
"""
from __future__ import annotations

import os
import secrets
import threading
import time
from pathlib import Path


def _cfg_dir() -> str:
    return os.environ.get("DREAMLAYER_DIR", str(Path.home() / ".dreamlayer"))


def _serve(cfg_dir: str, port: int) -> None:
    """Build the Brain and serve forever (runs on a background daemon thread)."""
    from dreamlayer.ai_brain.server.server import Brain, make_brain_server
    brain = Brain(cfg_dir)
    if not brain.config.token:                     # first run — mint a pairing token
        brain.config.token = secrets.token_hex(8)
        brain.save()
    brain.start_watching()                         # reindex watched folders on change
    brain.start_brief_scheduler()                  # morning brief at brief_hour
    brain.start_calendar_sync()                    # pull macOS Calendar into the agenda
    make_brain_server(brain, host="0.0.0.0", port=port).serve_forever()


def main() -> int:
    cfg_dir = _cfg_dir()
    port = int(os.environ.get("DREAMLAYER_PORT", "7777"))
    Path(cfg_dir).mkdir(parents=True, exist_ok=True)
    threading.Thread(target=_serve, args=(cfg_dir, port), daemon=True).start()
    time.sleep(1.0)                                # let the socket bind before polling
    from dreamlayer.ai_brain.menubar import run_menubar
    return run_menubar(cfg_dir, port)


if __name__ == "__main__":
    raise SystemExit(main())
