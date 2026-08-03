"""The folders react instead of being asked — `fs_watch`, Brain-side.

WHAT WAS MISSING
----------------
`orchestrator/fs_watch.py` is a complete watchdog wrapper: start a recursive
observer on a path, get a callback per changed file, stop it cleanly. Nothing
constructed it. Its only intended consumer was the `Orchestrator` the shipped
Brain never builds (`decisions/0001`).

Meanwhile `Brain.start_watching` runs a 3-second timer that calls `poll()`,
which walks every watched folder and compares a signature. On a Brain watching a
few thousand files that is a full stat sweep twenty times a minute, forever,
almost always to conclude that nothing happened — and the wearer still waits up
to three seconds for a note they just saved to become answerable.

WHY THE TIMER STAYS
-------------------
Not as a fallback for "watchdog is missing" — that much is obvious — but because
a watcher that IS running can still miss things. Network mounts, some FUSE
filesystems and containerised bind-mounts deliver events unreliably or not at
all, and watchdog's own polling observer exists for exactly that reason. A
Brain that dropped the timer the moment an observer started would go silent on
precisely the setups where it was already weakest.

So the timer is kept and SLOWED: `IDLE_INTERVAL_S` while watchers are live,
which is a safety net rather than the mechanism. That is a deliberate trade —
the wearer's own advertised behaviour ("re-index the second a file changes")
comes from the watcher, and the sweep behind it is insurance nobody should be
paying twenty times a minute for.

DEBOUNCE
--------
One save is many events: editors write a temp file, rename it, touch the
directory, and some sync clients rewrite a whole tree. `poll()` reindexes, so
firing it per event would turn one save into a burst of full rescans — strictly
worse than the timer it replaces. Events are collapsed into a single deferred
poll, so a burst costs one reindex and a quiet folder costs nothing.
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("dreamlayer.fs_watch_live")

#: How long to wait after the last event before reindexing. Long enough that an
#: editor's write-rename-touch dance is one poll, short enough that "the second
#: a file changes" is still true from where the wearer sits.
DEBOUNCE_S = 0.4

#: The timer's cadence once watchers are live — insurance against a filesystem
#: that does not deliver events, not the mechanism. 5 minutes rather than 3
#: seconds is ~100x less stat traffic for a guarantee nobody should notice.
IDLE_INTERVAL_S = 300.0


class FolderWatchers:
    """One watchdog observer per watched folder, held for the session."""

    def __init__(self, brain, on_change=None, now_fn=None):
        self.brain = brain
        self._on_change = on_change or self._reindex
        self._watchers: list = []
        self._timer: threading.Timer | None = None
        self._lock = threading.RLock()
        #: Change events genuinely delivered by a watcher. The promotion proof:
        #: an observer that STARTED is not an observer that saw anything, and on
        #: a filesystem that does not deliver events it never will — which is
        #: the case the timer is kept for.
        self.changes = 0
        #: Reindexes actually triggered. Lower than `changes` by design; the gap
        #: is what the debounce saved.
        self.polls = 0

    # ------------------------------------------------------------------ start

    def start(self) -> int:
        """Watch every configured folder. Returns how many watchers started.

        Zero is the honest answer on a Brain with no folders, without watchdog,
        or on a path that cannot be watched — and in every one of those cases
        the timer keeps its original cadence, so nothing is lost.
        """
        with self._lock:
            if self._watchers:
                return len(self._watchers)
            try:
                from ...orchestrator.fs_watch import FolderWatcher
            except Exception as exc:                 # noqa: BLE001
                log.info("[fs_watch] unavailable: %s", type(exc).__name__)
                return 0
            for folder in self._folders():
                try:
                    w = FolderWatcher(folder, self._changed)
                    if w.start():
                        self._watchers.append(w)
                except Exception as exc:             # noqa: BLE001
                    # A single unwatchable folder — a vanished path, a mount
                    # that refuses inotify — must not cost the others their
                    # watcher. The COUNT is logged, never the path: a watched
                    # folder is a filesystem layout, which is a detail about
                    # the wearer's machine and not something a log needs.
                    log.info("[fs_watch] folder not watchable: %s",
                             type(exc).__name__)
            if self._watchers:
                log.info("[fs_watch] watching %d folder(s)", len(self._watchers))
            return len(self._watchers)

    def _folders(self) -> list:
        try:
            return [f for f in (self.brain.config.folders or []) if f]
        except Exception:                            # noqa: BLE001
            return []

    def stop(self) -> None:
        with self._lock:
            watchers, self._watchers = self._watchers, []
            timer, self._timer = self._timer, None
        for w in watchers:
            try:
                w.stop()
            except Exception:                        # noqa: BLE001
                pass
        if timer is not None:
            timer.cancel()

    # ----------------------------------------------------------------- events

    def _changed(self, path: str) -> None:
        """One filesystem event. Collapsed into a single deferred poll.

        `path` is accepted because watchdog hands it over and is deliberately
        NOT used: `poll()` re-derives the signature across every folder, and
        reindexing "just this file" would be a second, divergent code path for
        something the Brain already does correctly in one place.
        """
        with self._lock:
            self.changes += 1
            if self._timer is not None:
                self._timer.cancel()               # a burst is still one poll
            self._timer = threading.Timer(DEBOUNCE_S, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        with self._lock:
            self._timer = None
        try:
            self._on_change()
            self.polls += 1
        except Exception:                            # noqa: BLE001
            log.warning("[fs_watch] reindex failed", exc_info=True)

    def _reindex(self) -> None:
        self.brain.poll()

    # ----------------------------------------------------------------- report

    def watching(self) -> int:
        return len(self._watchers)

    def driving(self) -> bool:
        """A delivered EVENT, not a started observer.

        The distinction is the whole capability here. Starting an observer on a
        network mount that never emits is indistinguishable from starting one
        that works, right up until the wearer saves a file and waits — and the
        thing that has to keep working in that case is the timer, so reporting
        the watcher live would be describing the wrong mechanism.
        """
        return self.changes > 0

    def status(self) -> dict:
        return {"watching": self.watching(), "changes": self.changes,
                "polls": self.polls, "live": self.driving()}


def watchers(brain) -> FolderWatchers:
    got = getattr(brain, "_fs_watchers", None)
    if got is None:
        got = FolderWatchers(brain)
        brain._fs_watchers = got
    return got
