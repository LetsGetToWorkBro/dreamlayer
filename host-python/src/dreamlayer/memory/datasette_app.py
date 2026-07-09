"""Datasette memory explorer — turn the memory SQLite into a browsable local web
UI, zero-code, local-first.

ADD-alongside: new module. Lazy-imports datasette (extras group `infra`); when
absent, `command()` still returns the exact CLI a user can run once they install
it, and `available` is False — no behaviour change to the memory engine.
"""
from __future__ import annotations
import logging

log = logging.getLogger("dreamlayer.datasette_app")

try:
    import datasette  # type: ignore  # noqa: F401
    _HAS_DATASETTE = True
except ImportError:
    _HAS_DATASETTE = False


class MemoryExplorer:
    available = _HAS_DATASETTE

    def __init__(self, db_path: str):
        self.db_path = db_path

    def command(self, port: int = 8001) -> str:
        """The local-only launch command (host 127.0.0.1 by design)."""
        return f"datasette serve {self.db_path} --host 127.0.0.1 --port {port}"

    def serve(self, port: int = 8001):
        """Return a configured Datasette app instance, or None with no dep."""
        if not _HAS_DATASETTE:
            log.info("[datasette] not installed; run: %s", self.command(port))
            return None
        try:
            from datasette.app import Datasette  # type: ignore
            return Datasette([self.db_path])
        except Exception as exc:
            log.error("[datasette] init failed: %s", exc)
            return None
