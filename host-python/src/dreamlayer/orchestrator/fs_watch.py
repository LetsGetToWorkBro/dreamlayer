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
        #: Why the last start() returned False, or "" after a successful one.
        #: `start()` catches its own failure, so a caller sees only the bool and
        #: cannot tell "watchdog is not installed" (the designed fallback) from
        #: "the OS refused the watch" (a machine that has run out of inotify
        #: watches, an NFS mount, a vanished path). Both mean the same thing to
        #: the caller — keep polling — but they mean very different things to
        #: somebody reading a failure, and the only record of the difference was
        #: a log line nothing reads back.
        #:
        #: An exception TYPE and errno only, never the message and never the
        #: path. A watched folder is a detail of the wearer's filesystem layout;
        #: `fs_watch_live` already logs the folder COUNT and never the path for
        #: exactly that reason, and this module was contradicting it — an
        #: OSError from inotify carries the offending path in its message, and
        #: that message was going straight into log.error.
        self.last_error: str = ""

    def start(self) -> bool:
        """Begin watching. Returns True if a real watcher started, False when the
        dep is absent (caller falls back to polling). See `last_error` for why."""
        if not _HAS_WATCHDOG:
            self.last_error = "watchdog not installed"
            return False
        try:
            handler = _Handler(self._on_change)
            self._observer = Observer()
            self._observer.schedule(handler, self.path, recursive=True)
            self._observer.start()
            self.last_error = ""
            return True
        except Exception as exc:
            errno = getattr(exc, "errno", None)
            self.last_error = (f"{type(exc).__name__}"
                               + (f" (errno {errno})" if errno else ""))
            log.error("[fs_watch] start failed: %s", self.last_error)
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
