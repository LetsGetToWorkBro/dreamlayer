"""Filesystem watcher (watchdog) — re-index a folder the second a file changes
instead of waiting for the next cron tick.

ADD-alongside: new module. Lazy-imports watchdog (extras group `infra`); when
absent, `start()` returns False and callers keep their existing periodic scan
(no behaviour change).
"""
from __future__ import annotations
import logging
from typing import Any

log = logging.getLogger("dreamlayer.fs_watch")

try:
    from watchdog.observers import Observer  # type: ignore
    from watchdog.events import FileSystemEventHandler  # type: ignore
    _HAS_WATCHDOG = True
except ImportError:
    _HAS_WATCHDOG = False


class FolderWatcher:
    available = _HAS_WATCHDOG

    def __init__(self, path: str, on_change):
        self.path = path
        self._on_change = on_change
        self._observer: Any = None       # watchdog Observer (untyped optional dep)

    def start(self) -> bool:
        """Begin watching. Returns True if a real watcher started, False when the
        dep is absent (caller falls back to polling)."""
        if not _HAS_WATCHDOG:
            return False
        try:
            handler = _Handler(self._on_change)
            self._observer = Observer()
            self._observer.schedule(handler, self.path, recursive=True)
            self._observer.start()
            return True
        except Exception as exc:
            log.error("[fs_watch] start failed: %s", exc)
            self._observer = None
            return False

    def stop(self) -> None:
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=2)
            except Exception:
                pass
            self._observer = None


if _HAS_WATCHDOG:
    class _Handler(FileSystemEventHandler):  # type: ignore[misc]
        def __init__(self, cb):
            self._cb = cb

        def on_any_event(self, event):
            if not event.is_directory:
                try:
                    self._cb(event.src_path)
                except Exception as exc:
                    log.warning("[fs_watch] callback failed: %s", exc)
