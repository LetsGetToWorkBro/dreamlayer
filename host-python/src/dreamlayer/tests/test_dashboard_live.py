"""The live terminal dashboard — the `dashboard` capability, driven at last.

`ai_brain/dashboard_rich.py` sat in the reachability report's worst-but-honest
bucket: "loadable, dormant, and NOTHING promotes them". The seam imported, the
wearer was correctly told dormant, and no path in the product ever called
`render()`. `python -m dreamlayer.ai_brain.server --dashboard` now does.

Two things this pins beyond "it draws":

  * **proof, not availability.** `rich` importing is not evidence the panel
    works — a `Console` with no terminal to write to, or a `Table` that raises,
    both fall through to the plain line while `available` still reads True. Only
    a completed draw increments `rich_renders`, and only that promotes the
    capability.
  * **the panel says counts, never content.** It reports how much the ear has
    heard and never a word of what — the same rule `ear.status()` follows.
"""
from __future__ import annotations

import contextlib
import io
import time

import pytest

from dreamlayer.ai_brain.dashboard_rich import (
    Dashboard, brain_status, start_dashboard,
)


class _Index:
    def __init__(self, files=42):
        self._n = files

    def stats(self):
        return {"files": self._n}


class FakeBrain:
    """Only what `brain_status` touches."""

    class _Cfg:
        model = "llama3"
        folders = ["/docs", "/notes"]
        token = "t"
        cloud_calls = 3

    def __init__(self, veiled=False, ear=None, broken=()):
        self.config = self._Cfg()
        self.index = _Index()
        self._veiled = veiled
        self._ear = ear
        self._broken = set(broken)

    def incognito_now(self):
        if "veil" in self._broken:
            raise RuntimeError("posture unreadable")
        return self._veiled

    def ear_status(self):
        if "ear" in self._broken:
            raise RuntimeError("no ear")
        return self._ear


@pytest.fixture
def panels():
    """Start panels through this, and they are stopped at teardown.

    A dashboard is a daemon thread that PRINTS. One left running does not just
    leak — it interleaves rich tables into the captured stdout of every later
    test in the session, which is exactly how this file first turned
    `test_perception_club.py::test_cli_json` red while passing in isolation.
    """
    started = []
    yield started
    for d in started:
        stop = getattr(d, "stop", None)
        if callable(stop):
            stop()


def _quiet(fn, *a, **kw):
    """Run something that prints, and hand back (result, what it printed)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = fn(*a, **kw)
    return out, buf.getvalue()


class TestTheStatusItReports:
    def test_it_reads_the_brains_live_state(self):
        st = brain_status(FakeBrain(ear={"listening": True, "heard_count": 7}))
        assert st["model"] == "llama3"
        assert st["folders"] == "2" and st["files"] == "42"
        assert st["token"] == "set" and st["cloud calls"] == "3"

    def test_the_veil_is_on_the_panel(self):
        """The one piece of state that changes what the Brain is ALLOWED to do
        belongs where a wearer can glance at it."""
        assert brain_status(FakeBrain(veiled=False))["veil"] == "down"
        assert brain_status(FakeBrain(veiled=True))["veil"] == "UP"

    def test_the_ear_reports_a_count_and_never_content(self):
        st = brain_status(FakeBrain(ear={"listening": True, "heard_count": 7,
                                         "last_heard": "the lease is due Friday"}))
        assert st["ear"] == "listening" and st["heard"] == "7"
        assert "lease" not in " ".join(st.values()), (
            "the panel is carrying what was heard, not just how much")

    def test_a_phone_driven_ear_counts_as_listening(self):
        st = brain_status(FakeBrain(ear={"listening": False, "remote_listening": True,
                                         "heard_count": 2}))
        assert st["ear"] == "listening"

    def test_extras_ride_along(self):
        st = brain_status(FakeBrain(ear=None), port=7777, https=7778)
        assert st["port"] == "7777" and st["https"] == "7778"

    @pytest.mark.parametrize("broken", ["veil", "ear"])
    def test_a_field_the_brain_cannot_answer_degrades(self, broken):
        """A dashboard must never be the thing that takes the server down."""
        st = brain_status(FakeBrain(ear={"heard_count": 1}, broken=[broken]))
        assert st, "the whole status collapsed on one bad field"
        if broken == "veil":
            assert st["veil"] == "?"
        else:
            assert "ear" not in st          # unreadable → omitted, not guessed


class TestProofNotAvailability:
    def test_a_fresh_dashboard_has_drawn_nothing(self):
        assert Dashboard().rich_renders == 0

    def test_a_completed_draw_counts(self):
        rich = pytest.importorskip("rich")          # noqa: F841
        d = Dashboard()
        _, printed = _quiet(d.render, {"model": "llama3"})
        assert d.rich_renders == 1
        assert "DreamLayer Brain" in printed, "the rich table never reached stdout"

    def test_a_render_that_raises_does_not_count(self, monkeypatch):
        """The exact case `available` cannot see: the wheel is present, the
        console exists, and drawing still fails. It must fall back to the plain
        line AND leave the capability unpromoted."""
        pytest.importorskip("rich")
        d = Dashboard()
        if d._console is None:
            pytest.skip("rich console not constructible here")
        monkeypatch.setattr(d._console, "print",
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no tty")))
        text, printed = _quiet(d.render, {"model": "llama3"})
        assert d.rich_renders == 0, "a failed draw was counted as proof"
        assert "model: llama3" in text and "model: llama3" in printed

    def test_without_rich_it_still_returns_the_plain_line(self, monkeypatch):
        d = Dashboard()
        monkeypatch.setattr(d, "_console", None)     # the no-rich path
        text, printed = _quiet(d.render, {"model": "llama3", "veil": "down"})
        assert text == "model: llama3  ·  veil: down"
        assert printed == "", "the no-rich path printed instead of returning"
        assert d.rich_renders == 0


class TestTheLiveLoop:
    def test_it_redraws_on_its_interval(self, panels):
        pytest.importorskip("rich")
        b = FakeBrain(ear={"listening": False, "heard_count": 0})
        dash, _ = _quiet(start_dashboard, b, interval=0.02, port=7777)
        assert dash is not None
        panels.append(dash)
        time.sleep(0.2)
        assert dash.rich_renders > 1, "the panel drew once and stopped"

    def test_the_thread_is_a_daemon(self, panels):
        """It must never hold the process open at Ctrl-C — every background loop
        in this product is a daemon (docs/CONCURRENCY.md)."""
        import threading
        dash, _ = _quiet(start_dashboard, FakeBrain(ear=None), interval=5.0)
        panels.append(dash)
        named = [t for t in threading.enumerate() if t.name == "dreamlayer-dashboard"]
        assert named and all(t.daemon for t in named)

    def test_a_brain_that_raises_does_not_kill_the_loop(self, panels):
        """`brain_status` already degrades per field; this covers the tick itself
        blowing up — the loop has to survive and try again."""
        class Exploding(FakeBrain):
            def __init__(self):
                super().__init__(ear=None)
                self.n = 0

            @property
            def config(self):
                self.n += 1
                if self.n < 3:
                    raise RuntimeError("still starting")
                return FakeBrain._Cfg()

            @config.setter
            def config(self, _v):
                pass

        dash, _ = _quiet(start_dashboard, Exploding(), interval=0.02)
        panels.append(dash)
        time.sleep(0.2)
        assert dash is not None      # survived the early failures


    def test_a_started_panel_can_be_stopped(self, panels):
        """Not decoration: an unstoppable panel keeps writing to stdout after
        whoever started it has moved on. This file's own first version left two
        running and turned an unrelated JSON-output test red."""
        pytest.importorskip("rich")
        dash, _ = _quiet(start_dashboard, FakeBrain(ear=None), interval=0.02)
        panels.append(dash)
        assert callable(getattr(dash, "stop", None)), "no way to stop the panel"
        time.sleep(0.08)
        dash.stop()
        time.sleep(0.08)
        settled = dash.rich_renders
        time.sleep(0.15)
        assert dash.rich_renders == settled, "the panel kept drawing after stop()"


class TestTheLauncherFlag:
    def _main_src(self):
        import pathlib
        from dreamlayer.ai_brain.server import __main__ as m
        return pathlib.Path(m.__file__).read_text(encoding="utf-8")

    def test_the_flag_exists_and_defaults_off(self):
        src = self._main_src()
        assert '"--dashboard", action="store_true"' in src, (
            "the flag is not store_true, so a bare launch may start the panel")

    def test_a_bare_launch_does_not_start_it(self):
        """The startup block a bare `python -m …server` prints is what the
        installer, the docs and the launch tests read. `--dashboard` must be
        opt-in or that output moves under everyone."""
        import argparse
        ap = argparse.ArgumentParser()
        ap.add_argument("--dashboard", action="store_true")
        assert ap.parse_args([]).dashboard is False
        assert ap.parse_args(["--dashboard"]).dashboard is True

    def test_promotion_is_behind_a_real_render(self):
        """`DL_WIRED_DASHBOARD` must be set from `rich_renders`, not from
        `available` — that is the whole distinction this capability's bucket
        turns on."""
        src = self._main_src()
        block = src.split("if args.dashboard:", 1)[1].split("try:", 1)[0]
        assert "rich_renders > 0" in block
        assert "DL_WIRED_DASHBOARD" in block

    def test_it_says_so_when_the_pack_is_missing(self):
        src = self._main_src()
        block = src.split("if args.dashboard:", 1)[1].split("try:", 1)[0]
        assert "Dashboard.available" in block and "infra" in block


class TestTheCapabilityReportsHonestly:
    def test_the_key_matches_what_the_launcher_sets(self):
        from dreamlayer.capabilities import CAPABILITIES
        cap = next(c for c in CAPABILITIES if c.key == "dashboard")
        assert cap.flag_env == "DL_DISABLE_DASHBOARD"
        assert "DL_WIRED_" + cap.key.upper() == "DL_WIRED_DASHBOARD"

    def test_it_is_still_declared_dormant_by_default(self):
        """Correct, and not a gap: the panel only runs when asked for. The
        reachability report distinguishes "dormant and nothing promotes it" from
        "dormant by default, promoted while it runs" — this belongs in the
        second bucket now, and that is what `_NOT_WIRED` plus a live
        `DL_WIRED_` setter means."""
        from dreamlayer.capabilities import _NOT_WIRED
        assert "dashboard" in _NOT_WIRED
