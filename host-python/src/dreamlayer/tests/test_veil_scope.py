"""test_veil_scope.py — one gesture, everything stops.

`orchestrator/concurrency_anyio.run_until_veil` had no caller, and unlike the
other re-hostings the fix was NOT "call it from the Brain": the shipped Brain is
threaded, so for most of it there is no event loop to put a scope in, and
standing one up to have somewhere to call this would be the resurrection mistake
in a different costume.

There is exactly one place that already runs a loop and also has an incomplete
Veil-stop: `live_dream.scene()` checks `veiled()` ONCE at the top and then runs
up to two VLM calls with the wearer's camera frame in them. Dropping the Veil
mid-beat — the exact gesture the guarantee is named for — left the in-flight
call running.

What is asserted here is the cancellation, not the plumbing: a beat that is
veiled halfway through returns nothing and stops waiting.
"""
from __future__ import annotations

import asyncio
import tempfile
import time

import pytest

from dreamlayer.ai_brain.server.server import Brain
from dreamlayer.ai_brain.server.veil_scope import (
    driving, run_guarded, scopes_run, veil_cancels)


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


class _Veil:
    """A posture switch a test can flip mid-beat, like a wearer would."""

    def __init__(self, veiled=False, boom=False, flip_after=None):
        self.veiled = veiled
        self.boom = boom
        self.flip_after = flip_after
        self.asked = 0

    def __call__(self):
        self.asked += 1
        if self.boom:
            raise RuntimeError("trust store unreadable")
        if self.flip_after is not None and self.asked >= self.flip_after:
            self.veiled = True
        return self.veiled


class TestTheBeatStopsWhenTheVeilDrops:
    def test_a_finished_beat_returns_its_value(self):
        async def _work():
            await asyncio.sleep(0)
            return {"description": "a warm room"}
        before = scopes_run()
        assert run_guarded(_work, _Veil()) == {"description": "a warm room"}
        assert scopes_run() == before + 1

    def test_veiling_mid_beat_cancels_it(self):
        """The whole point. A slow backend call gets cut the moment the wearer
        veils, rather than running to the backend's own timeout with their
        camera frame in it."""
        started = []

        async def _slow():
            started.append(1)
            await asyncio.sleep(30)              # a hung backend
            return {"description": "should never be seen"}

        veil = _Veil(flip_after=2)
        t0 = time.monotonic()
        before = veil_cancels()
        assert run_guarded(_slow, veil, poll_s=0.01) is None
        assert started == [1], "the work never even began"
        assert time.monotonic() - t0 < 5.0, "it waited for the backend anyway"
        assert veil_cancels() == before + 1

    def test_a_beat_that_was_already_veiled_returns_nothing(self):
        async def _work():
            await asyncio.sleep(5)
            return "drawn"
        assert run_guarded(_work, _Veil(veiled=True), poll_s=0.01) is None

    def test_an_unreadable_posture_cancels_rather_than_continues(self):
        """Fails CLOSED in the one direction that matters: an unreadable trust
        signal must never resolve to "keep sending frames to the model"."""
        async def _work():
            await asyncio.sleep(5)
            return "drawn"
        assert run_guarded(_work, _Veil(boom=True), poll_s=0.01) is None

    def test_a_quick_beat_does_not_wait_for_the_wearer_to_veil(self):
        """Setting the stop event on COMPLETION as well as on the Veil is what
        makes this a scope rather than a leak — without it a beat that finished
        in 200ms would hold its worker until the wearer happened to veil."""
        async def _fast():
            return "done"
        t0 = time.monotonic()
        assert run_guarded(_fast, _Veil(), poll_s=5.0) == "done"
        assert time.monotonic() - t0 < 2.0, (
            "a finished beat sat waiting on the veil watcher")

    def test_a_failing_beat_yields_nothing_rather_than_raising(self):
        """Identical whichever path `run_until_veil` takes. anyio propagates an
        ExceptionGroup and plain asyncio swallows the failure into
        `gather(return_exceptions=True)`; normalising to "no value" is what
        keeps the guarantee the same with and without the optional wheel."""
        async def _boom():
            raise RuntimeError("the model returned nonsense")
        assert run_guarded(_boom, _Veil(), poll_s=0.01) is None

    def test_a_failing_beat_runs_EXACTLY_ONCE(self):
        """A real bug in the seam, found by wiring it. `run_until_veil` caught
        the task group's re-raised child exception, read it as "anyio is
        broken", logged, and fell through to the asyncio path — RE-RUNNING every
        factory. For the Brain's only caller that meant two VLM requests
        carrying the wearer's camera frame instead of one, and the failure was
        then swallowed so the caller saw a clean return."""
        runs = []

        async def _boom():
            runs.append(1)
            raise RuntimeError("the model returned nonsense")
        run_guarded(_boom, _Veil(), poll_s=0.01)
        assert runs == [1], f"the failing beat ran {len(runs)} times"

    def test_it_runs_exactly_once_on_the_asyncio_path_too(self, monkeypatch):
        import dreamlayer.orchestrator.concurrency_anyio as ca
        monkeypatch.setattr(ca, "_HAS_ANYIO", False)
        runs = []

        async def _boom():
            runs.append(1)
            raise RuntimeError("nope")
        run_guarded(_boom, _Veil(), poll_s=0.01)
        assert runs == [1]


class TestTheFloorHolds:
    """`run_until_veil` falls back to plain asyncio with the same cancel-all
    semantics when anyio is absent, and the whole guarantee has to survive
    that — the capability is a nicer implementation, never the guarantee."""

    def test_it_cancels_the_same_way_with_anyio_absent(self, monkeypatch):
        import dreamlayer.orchestrator.concurrency_anyio as ca
        monkeypatch.setattr(ca, "_HAS_ANYIO", False)

        async def _slow():
            await asyncio.sleep(30)
            return "should never be seen"
        t0 = time.monotonic()
        assert run_guarded(_slow, _Veil(flip_after=2), poll_s=0.01) is None
        assert time.monotonic() - t0 < 5.0

    def test_it_returns_the_same_way_with_anyio_absent(self, monkeypatch):
        import dreamlayer.orchestrator.concurrency_anyio as ca
        monkeypatch.setattr(ca, "_HAS_ANYIO", False)

        async def _work():
            return "done"
        assert run_guarded(_work, _Veil()) == "done"


class TestTheDreamBeatUsesIt:
    """The link, asserted through `live_dream` rather than by reading it."""

    def _dream(self, brain, tick):
        from dreamlayer.ai_brain.server.live_dream import LiveDream
        d = LiveDream(brain)
        d._describer = type("_D", (), {"tick": staticmethod(tick)})()
        d._ghost = type("_G", (), {"tick": staticmethod(lambda ctx: None)})()
        return d

    def test_a_veil_dropped_mid_beat_draws_nothing(self, brain, monkeypatch):
        """`scene()` checks `veiled()` once at the top; this is the case that
        check cannot cover, and the reason the scope exists."""
        veil = _Veil(flip_after=2)

        async def _slow(ctx):
            await asyncio.sleep(30)
            return {"description": "should never be drawn"}

        d = self._dream(brain, _slow)
        d._wl = type("_W", (), {"veiled": staticmethod(veil)})()
        monkeypatch.setattr("dreamlayer.ai_brain.server.veil_scope.POLL_S", 0.01)
        t0 = time.monotonic()
        out = d.scene(b"\xff\xd8jpegbytes")
        assert out["scene"] is None
        assert time.monotonic() - t0 < 5.0, (
            "the beat ran to the backend's own timeout with the frame in it")

    def test_an_unveiled_beat_still_draws(self, brain):
        async def _quick(ctx):
            return {"description": "a warm room", "dominant_color": 0x2CC79A}

        d = self._dream(brain, _quick)
        d._wl = type("_W", (), {"veiled": staticmethod(_Veil())})()
        out = d.scene(b"\xff\xd8jpegbytes")
        assert out["scene"] is not None

    def test_the_top_of_beat_check_is_still_there(self, brain):
        """Belt and braces, deliberately: the scope handles the mid-beat case,
        and refusing before any work starts is cheaper and does not depend on a
        poll interval."""
        called = []

        async def _tick(ctx):
            called.append(1)
            return {}

        d = self._dream(brain, _tick)
        d._wl = type("_W", (), {"veiled": staticmethod(lambda: True)})()
        assert d.scene(b"jpeg") == {"scene": None, "ghost": None}
        assert called == [], "a veiled beat still reached the model"


class TestThePromotionNeedsBothHalves:
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

    def test_the_wheel_alone_is_not_enough(self, monkeypatch):
        """A wheel on disk with no beat run through it is the
        importable-never-called state this whole audit is about."""
        import dreamlayer.ai_brain.server.veil_scope as vs
        monkeypatch.setattr(vs, "_SCOPES", 0)
        monkeypatch.setattr(
            "dreamlayer.orchestrator.concurrency_anyio.available", True)
        assert driving() is False

    def test_a_scope_alone_is_not_enough(self, monkeypatch):
        """The capability IS anyio. The asyncio path is the baseline it must
        never do worse than, so a scope that ran on the fallback is the
        guarantee working and not the capability."""
        import dreamlayer.ai_brain.server.veil_scope as vs
        monkeypatch.setattr(vs, "_SCOPES", 5)
        monkeypatch.setattr(
            "dreamlayer.orchestrator.concurrency_anyio.available", False)
        assert driving() is False

    def test_both_together_promote(self, brain, monkeypatch):
        import dreamlayer.ai_brain.server.veil_scope as vs
        monkeypatch.delenv("DL_WIRED_STRUCTURED_CONCURRENCY", raising=False)
        monkeypatch.setattr(vs, "_SCOPES", 1)
        monkeypatch.setattr(
            "dreamlayer.orchestrator.concurrency_anyio.available", True)
        assert driving() is True
        assert self._env(brain, monkeypatch)[
            "DL_WIRED_STRUCTURED_CONCURRENCY"] == "1"

    def test_a_brain_that_never_dreamed_is_not_promoted(self, brain,
                                                        monkeypatch):
        import dreamlayer.ai_brain.server.veil_scope as vs
        monkeypatch.delenv("DL_WIRED_STRUCTURED_CONCURRENCY", raising=False)
        monkeypatch.setattr(vs, "_SCOPES", 0)
        assert "DL_WIRED_STRUCTURED_CONCURRENCY" not in self._env(
            brain, monkeypatch)
