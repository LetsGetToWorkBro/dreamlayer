"""test_fs_watch_live.py — the folders react instead of being asked.

`orchestrator/fs_watch.py` was a complete watchdog wrapper with no caller, while
`Brain.start_watching` ran a 3-second timer that stat-walks every watched file —
twenty full sweeps a minute, forever, almost always to conclude nothing
happened — and the wearer still waited up to three seconds for a note they had
just saved.

watchdog is absent in CI, so the observer is a fake. What needs proving is
Brain-side and none of it is watchdog's behaviour: that a burst of events costs
ONE reindex, that the timer is kept rather than replaced, that stopping really
stops, and that the capability reports itself live on a delivered event rather
than on an observer having started.
"""
from __future__ import annotations

import logging
import tempfile
import time

import pytest

from dreamlayer.ai_brain.server.fs_watch_live import (
    DEBOUNCE_S, IDLE_INTERVAL_S, FolderWatchers, watchers)
from dreamlayer.ai_brain.server.server import Brain


@pytest.fixture
def brain(tmp_path):
    b = Brain(tempfile.mkdtemp())
    d = tmp_path / "notes"
    d.mkdir()
    b.config.folders = [str(d)]
    return b


class _FakeWatcher:
    """Stands in for `FolderWatcher`, and hands back the callback so a test can
    deliver events the way a real filesystem would."""

    made: list = []

    def __init__(self, path, on_change, starts=True):
        self.path = path
        self.on_change = on_change
        self.stopped = False
        self._starts = starts
        _FakeWatcher.made.append(self)

    def start(self):
        return self._starts

    def stop(self):
        self.stopped = True


@pytest.fixture
def fake(monkeypatch):
    import dreamlayer.orchestrator.fs_watch as fw
    _FakeWatcher.made = []
    monkeypatch.setattr(fw, "FolderWatcher", _FakeWatcher)
    return _FakeWatcher


def _settle():
    """Wait past the debounce for the deferred poll to run."""
    time.sleep(DEBOUNCE_S + 0.3)


class TestOneSaveIsOneReindex:
    """A save is many events — editors write a temp file, rename it, touch the
    directory; sync clients rewrite whole trees. `poll()` REINDEXES, so firing
    per event would turn one save into a burst of full rescans, which is
    strictly worse than the timer this replaces."""

    def _w(self, brain):
        seen = []
        return FolderWatchers(brain, on_change=lambda: seen.append(1)), seen

    def test_a_burst_collapses_into_one_poll(self, brain, fake):
        w, seen = self._w(brain)
        assert w.start() == 1
        for _ in range(20):
            fake.made[0].on_change("/notes/a.md")
        _settle()
        assert seen == [1], f"{len(seen)} reindexes for one burst"
        assert w.changes == 20, "the event count should still be honest"
        assert w.polls == 1

    def test_two_saves_far_apart_are_two_polls(self, brain, fake):
        w, seen = self._w(brain)
        w.start()
        fake.made[0].on_change("/notes/a.md")
        _settle()
        fake.made[0].on_change("/notes/b.md")
        _settle()
        assert len(seen) == 2

    def test_a_quiet_folder_costs_nothing(self, brain, fake):
        w, seen = self._w(brain)
        w.start()
        _settle()
        assert seen == []
        assert w.polls == 0

    def test_a_failing_reindex_does_not_kill_the_watcher(self, brain, fake):
        def _boom():
            raise RuntimeError("index locked")
        w = FolderWatchers(brain, on_change=_boom)
        w.start()
        fake.made[0].on_change("/notes/a.md")
        _settle()
        assert w.changes == 1
        assert w.polls == 0                      # it failed, and says so
        fake.made[0].on_change("/notes/b.md")    # …and still watching
        _settle()
        assert w.changes == 2


class TestTheTimerIsKeptNotReplaced:
    """Not because watchdog might be missing — that case never reaches here —
    but because a watcher that IS running can still miss things. Network
    mounts, some FUSE filesystems and containerised bind-mounts deliver events
    unreliably or not at all, which is why watchdog ships a polling observer of
    its own."""

    def _intervals(self, brain, monkeypatch):
        """Every timeout the sweep loop waited on.

        Read off `Event.wait` rather than by inspecting source, because the
        interval is a LOCAL that `start_watching` rebinds — the thing under
        test is which value the loop actually runs at. Other Events in the
        process wait too, so this collects them all and the assertions name the
        value they want rather than an index."""
        import threading as _th
        waits = []
        real_event = _th.Event

        class _Ev(real_event):
            def wait(self, timeout=None):
                waits.append(timeout)
                return True                      # end the loop immediately
        monkeypatch.setattr(_th, "Event", _Ev)
        brain.start_watching()
        time.sleep(0.1)
        monkeypatch.setattr(_th, "Event", real_event)
        return waits

    def test_it_slows_down_when_watchers_are_live(self, brain, fake,
                                                  monkeypatch):
        waits = self._intervals(brain, monkeypatch)
        assert IDLE_INTERVAL_S in waits, (
            f"the sweep never slowed with watchers live; waited on {waits}")
        assert 3.0 not in waits, "it is still sweeping every three seconds"

    def test_it_keeps_its_original_cadence_with_no_watchers(self, brain,
                                                            monkeypatch):
        import dreamlayer.orchestrator.fs_watch as fw
        monkeypatch.setattr(
            fw, "FolderWatcher",
            lambda p, cb: _FakeWatcher(p, cb, starts=False))
        waits = self._intervals(brain, monkeypatch)
        assert 3.0 in waits, (
            "the sweep slowed down without a watcher behind it — the wearer "
            f"now waits five minutes for a saved note; waited on {waits}")
        assert IDLE_INTERVAL_S not in waits

    def test_the_insurance_is_much_slower_than_the_mechanism(self):
        assert IDLE_INTERVAL_S >= 60 * 3.0


class TestStartingAndStopping:
    def test_a_watcher_per_configured_folder(self, brain, fake, tmp_path):
        second = tmp_path / "more"
        second.mkdir()
        brain.config.folders = list(brain.config.folders) + [str(second)]
        assert FolderWatchers(brain).start() == 2
        assert len(fake.made) == 2

    def test_a_folder_that_cannot_be_watched_costs_only_itself(self, brain,
                                                               monkeypatch,
                                                               tmp_path):
        second = tmp_path / "more"
        second.mkdir()
        brain.config.folders = list(brain.config.folders) + [str(second)]
        import dreamlayer.orchestrator.fs_watch as fw
        made = []

        def _mk(path, cb):
            if not made:
                made.append(path)
                raise OSError("inotify limit reached")
            return _FakeWatcher(path, cb)
        monkeypatch.setattr(fw, "FolderWatcher", _mk)
        assert FolderWatchers(brain).start() == 1

    def test_no_folders_is_no_watchers_and_not_a_fault(self, brain, fake):
        brain.config.folders = []
        assert FolderWatchers(brain).start() == 0

    def test_starting_twice_does_not_double_the_observers(self, brain, fake):
        w = FolderWatchers(brain)
        assert w.start() == 1
        assert w.start() == 1
        assert len(fake.made) == 1

    def test_stop_stops_every_observer(self, brain, fake):
        w = FolderWatchers(brain)
        w.start()
        w.stop()
        assert all(x.stopped for x in fake.made)
        assert w.watching() == 0

    def test_stop_cancels_a_pending_reindex(self, brain, fake):
        """A debounce timer outliving `stop_watching` would reindex after the
        wearer asked us to stop."""
        seen = []
        w = FolderWatchers(brain, on_change=lambda: seen.append(1))
        w.start()
        fake.made[0].on_change("/notes/a.md")
        w.stop()
        _settle()
        assert seen == []

    def test_the_brain_stops_them_too(self, brain, fake):
        brain.start_watching()
        assert watchers(brain).watching() == 1
        brain.stop_watching()
        assert watchers(brain).watching() == 0

    def test_stop_on_a_brain_that_never_started_is_safe(self, brain):
        brain.stop_watching()

    def test_an_absent_watchdog_is_not_a_fault(self, brain, monkeypatch):
        import dreamlayer.orchestrator.fs_watch as fw

        def _boom(path, cb):
            raise ImportError("no watchdog")
        monkeypatch.setattr(fw, "FolderWatcher", _boom)
        assert FolderWatchers(brain).start() == 0
        brain.start_watching()                       # must not raise


class TestThePromotionFollowsADeliveredEvent:
    def _env(self, brain, monkeypatch) -> dict:
        import dreamlayer.capabilities as caps
        seen = {}
        real = caps.report

        def _spy(env=None, **kw):
            seen.update(env or {})
            return real(env=env, **kw)
        monkeypatch.setattr(caps, "report", _spy)
        from dreamlayer.ai_brain.server.server import _capability_payload
        _capability_payload(brain)
        return seen

    def test_a_started_observer_is_not_a_working_one(self, brain, fake,
                                                     monkeypatch):
        """The distinction that matters. Starting an observer on a mount that
        emits nothing looks identical to starting one that works, right up
        until the wearer saves a file and waits — and what keeps working there
        is the timer, so reporting the watcher live names the wrong mechanism.
        """
        monkeypatch.delenv("DL_WIRED_FS_WATCH", raising=False)
        w = watchers(brain)
        assert w.start() == 1
        assert w.driving() is False
        assert "DL_WIRED_FS_WATCH" not in self._env(brain, monkeypatch)

    def test_a_delivered_event_promotes_it(self, brain, fake, monkeypatch):
        monkeypatch.delenv("DL_WIRED_FS_WATCH", raising=False)
        w = watchers(brain)
        w.start()
        fake.made[0].on_change("/notes/a.md")
        assert w.driving() is True
        assert self._env(brain, monkeypatch)["DL_WIRED_FS_WATCH"] == "1"

    def test_the_report_does_not_build_watchers_to_ask(self, brain,
                                                       monkeypatch):
        monkeypatch.delenv("DL_WIRED_FS_WATCH", raising=False)
        assert "DL_WIRED_FS_WATCH" not in self._env(brain, monkeypatch)
        assert getattr(brain, "_fs_watchers", None) is None

    def test_they_are_built_once_and_held(self, brain):
        assert watchers(brain) is watchers(brain)

    def test_status_reports_the_same_thing_it_promotes_on(self, brain, fake):
        w = watchers(brain)
        w.start()
        fake.made[0].on_change("/notes/a.md")
        assert w.status()["live"] is w.driving()
        assert w.status()["changes"] == 1


class TestAFailedWatchDoesNotNameTheFolder:
    """A watched folder is the wearer's filesystem layout, and a refusal is
    exactly when it would get written down.

    `fs_watch_live` logs the folder COUNT and never the path, deliberately.
    `fs_watch.start()` was contradicting it one module along: an inotify
    OSError carries the offending path in its message —
    `[Errno 28] inotify watch limit reached: '/home/user/Documents/…'` — and
    that message went straight into `log.error("… %s", exc)`.

    A comment saying "never the path" is a comment (CLAUDE.md #7). This drives
    a real refusal carrying a real path and asserts it appears nowhere.
    """

    FOLDER = "/home/user/Documents/Divorce Papers"

    def _refuse(self, monkeypatch, caplog):
        from dreamlayer.orchestrator import fs_watch as F

        class _Refusing:
            def schedule(self, *a, **k):
                raise OSError(28, "inotify watch limit reached", self.path)
            path = "/home/user/Documents/Divorce Papers"

            def start(self):                          # pragma: no cover
                raise AssertionError("schedule() should have refused first")

        monkeypatch.setattr(F, "_HAS_WATCHDOG", True)
        monkeypatch.setattr(F, "Observer", _Refusing, raising=False)
        monkeypatch.setattr(F, "_Handler", lambda cb: object(), raising=False)
        w = F.FolderWatcher(self.FOLDER, on_change=lambda *_: None)
        with caplog.at_level(logging.DEBUG, logger="dreamlayer.fs_watch"):
            started = w.start()
        return w, started, caplog.text

    def test_the_path_reaches_neither_the_log_nor_last_error(self, monkeypatch,
                                                             caplog):
        w, started, text = self._refuse(monkeypatch, caplog)
        assert started is False
        assert self.FOLDER not in text, "the refusal named the watched folder"
        assert self.FOLDER not in w.last_error
        assert "Divorce" not in text and "Divorce" not in w.last_error

    def test_it_still_says_enough_to_diagnose(self, monkeypatch, caplog):
        """Redaction that removes the reason is not a win — the whole point of
        `last_error` is telling an OS refusal from an absent dependency."""
        w, _, text = self._refuse(monkeypatch, caplog)
        assert "OSError" in w.last_error and "28" in w.last_error
        assert "OSError" in text

    def test_the_refusal_actually_happened(self, monkeypatch, caplog):
        """Without this the two above pass on a watcher that never ran: no log
        output and an empty last_error contain no path either."""
        w, started, text = self._refuse(monkeypatch, caplog)
        assert started is False
        assert w.last_error, "start() recorded no reason — it did not refuse"
        assert text.strip(), "nothing was logged — the assertions read nothing"
