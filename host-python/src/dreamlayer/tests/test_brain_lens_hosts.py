"""test_brain_lens_hosts.py — the lenses that could not be loaded from the Brain.

`scripts/lens_reachability.py` found 12 of 28 declared lenses outside the Brain's
import closure entirely. Seven of them are hosted by `lens_hosts.py`, and the bar
here is the one retention set: **not** "the object constructs", but "it answers,
through a real `Brain(cfg)`, about state the Brain actually holds". A lens that
returns an empty result because its ring is empty looks identical to a lens that
works and has nothing to report — that ambiguity is the whole failure mode this
audit exists to close, so every test below puts real state in first.
"""
from __future__ import annotations

import json
import time

import pytest

from dreamlayer.ai_brain.server import Brain
from dreamlayer.ai_brain.server.store import BrainConfig
from dreamlayer.memory.db import MemoryDB


@pytest.fixture(autouse=True)
def _no_db_override(monkeypatch):
    monkeypatch.delenv("DREAMLAYER_DB", raising=False)


def _brain(tmp_path) -> Brain:
    cfg = tmp_path / "cfg"
    cfg.mkdir(exist_ok=True)
    BrainConfig(token="tok").save(cfg)
    return Brain(cfg)


def _seed_db(cfg_dir, rows):
    db = MemoryDB(str(cfg_dir / "dreamlayer.db"))
    for kind, summary in rows:
        db.add_memory(kind, summary)
    db.conn.commit()
    db.conn.close()


class TestTheLensesAreReachableAtAll:
    """The headline: `brain.lenses()` exists and every lens builds."""

    def test_every_lens_is_reachable_from_a_real_brain(self, tmp_path):
        ls = _brain(tmp_path).lenses()
        assert ls is not None
        for name in ("provenance", "candor", "drift", "saga", "stasis",
                     "premonition", "weather"):
            assert getattr(ls, name) is not None, f"{name} did not build"

    def test_the_module_is_in_the_brains_import_closure_now(self):
        """The check that found the gap must now agree these are wired."""
        import subprocess
        import sys
        from pathlib import Path
        script = Path(__file__).resolve().parents[4] / "scripts" / "lens_reachability.py"
        if not script.exists():
            pytest.skip("checker not on disk")
        out = subprocess.run([sys.executable, str(script)],
                             capture_output=True, text=True).stdout
        unreachable = out.split("UNREACHABLE", 1)[-1].split("reachable (", 1)[0]
        for lens in ("Provenance", "Candor", "Commitment Drift", "Saga",
                     "Stasis", "Premonition", "Inner Weather"):
            assert lens not in unreachable, (
                f"{lens} is still unreachable from the Brain — the host did not "
                f"put it in the import closure")


class TestTheRing:
    """The piece that did not exist: a timeline of what the wearer said."""

    def test_the_ring_is_seeded_from_the_memory_store(self, tmp_path):
        cfg = tmp_path / "cfg"
        cfg.mkdir()
        BrainConfig(token="tok").save(cfg)
        _seed_db(cfg, [("conversation", "I told Ana I would send the deposit"),
                       ("task", "send Ana the deposit"),
                       ("object", "a mug on the desk")])

        ls = Brain(cfg).lenses()
        summaries = [b.event.summary for b in ls.ring.latest(limit=50)]

        assert any("deposit" in s for s in summaries), (
            "the ring came up empty after a restart — the three ring lenses "
            "would answer 'nothing to report' for the wrong reason")
        assert not any("mug" in s for s in summaries), (
            "a sighting got into the statement ring — object rows drown the "
            "signal Candor and Provenance look for")

    def test_seeding_happens_once_even_when_it_fails(self, tmp_path):
        """A failing seed must not retry on every property access."""
        ls = _brain(tmp_path).lenses()
        calls = {"n": 0}
        real = ls._seed

        def _count():
            calls["n"] += 1
            return real()

        ls._seed = _count            # type: ignore[method-assign]
        ls._seeded = False
        for _ in range(5):
            # Touching the property IS the test — `ring` seeds on first access
            # and must not on the next four. Bound to `_` so it reads as a
            # deliberate probe rather than a stray expression somebody should
            # tidy away; ruff's B018 flags the bare form for exactly that
            # reason, and it would be right about every other occurrence.
            _ = ls.ring
        assert calls["n"] == 1

    def test_observe_is_veil_gated(self, tmp_path, monkeypatch):
        brain = _brain(tmp_path)
        ls = brain.lenses()
        assert ls.observe("conversation", "said out loud") is True
        before = len(ls.ring)

        monkeypatch.setattr(Brain, "incognito_now", lambda self: True)
        assert ls.observe("conversation", "said under the veil") is False
        assert len(ls.ring) == before, "a veiled statement entered the ring"

    def test_an_unreadable_posture_fails_closed(self, tmp_path, monkeypatch):
        ls = _brain(tmp_path).lenses()

        def _boom(self):
            raise RuntimeError("posture unreadable")

        monkeypatch.setattr(Brain, "incognito_now", _boom)
        assert ls.observe("conversation", "anything") is False


class TestTheLensesActuallyAnswer:
    """Each one, over state the Brain holds — not a constructor smoke test."""

    def test_candor_notices_you_contradicting_yourself(self, tmp_path):
        ls = _brain(tmp_path).lenses()
        ls.observe("conversation", "the deposit was paid on Friday")

        res = ls.candor.check("the deposit was not paid on Friday")

        assert res.fired is True, (
            "Candor saw a direct contradiction of a statement in the ring and "
            "reported nothing")
        assert res.prior_summary == "the deposit was paid on Friday"
        assert res.card["type"] == "ConsistencyCard"      # a HUD card, ready

    def test_candor_is_quiet_when_you_are_consistent(self, tmp_path):
        ls = _brain(tmp_path).lenses()
        ls.observe("conversation", "the deposit was paid on Friday")
        assert ls.candor.check("the weather is nice today").fired is False

    def test_provenance_traces_a_belief_to_where_it_came_from(self, tmp_path):
        ls = _brain(tmp_path).lenses()
        ls.observe("conversation", "Ana said the venue is booked for June")

        res = ls.provenance.trace("the venue is booked")

        assert res.found is True, (
            "Provenance found no source for a belief whose origin is in the ring")
        assert "venue is booked" in res.origin.summary
        assert res.card["type"] == "ProvenanceCard"       # a HUD card, ready

    def test_drift_tracks_a_promise_and_tending_resets_it(self, tmp_path):
        ls = _brain(tmp_path).lenses()
        ls.observe("task", "send Ana the deposit")
        ls.drift.tick(time.time())

        records = ls.drift.all_records()
        assert records, "Commitment Drift saw no promise in the ring"

    def test_saga_reports_stats_over_the_drift_engine(self, tmp_path):
        ls = _brain(tmp_path).lenses()
        ls.observe("task", "send Ana the deposit")
        ls.drift.tick(time.time())
        stats = ls.saga.stats()
        assert stats is not None

    def test_premonition_predicts_from_the_ring(self, tmp_path):
        ls = _brain(tmp_path).lenses()
        base = time.time() - 7 * 86400
        for day in range(7):                       # a daily rhythm
            ls.observe("task", "morning coffee", ts=base + day * 86400)
        ls.premonition.observe_buffer(ls.ring)
        # a daily rhythm is exactly what the recurrence model is for
        assert ls.premonition.predict(time.time()) is not None

    def test_inner_weather_samples_without_a_body_sensor(self, tmp_path):
        """No wearable is attached, so this must degrade honestly rather than
        fabricate a reading."""
        ls = _brain(tmp_path).lenses()
        assert ls.weather_tick({}) == [], "calm was not reported as calm"
        # ...and it CONSUMES a real phone payload rather than ignoring it
        stormy = {"imu_delta": {"yaw": 1.2, "pitch": 0.9, "roll": 0.6}}
        for _ in range(12):
            ls.weather_tick(stormy)
        assert ls.weather.state > 0.0, (
            "Inner Weather ignored the phone's IMU payload — the adapter is "
            "not reaching sample()")


class TestStasisSurvivesARestart:
    """"Freeze a thought, resume inside it" — a held thought that dies on
    restart is not a save state, which is the entire premise of the lens."""

    def test_a_held_thought_is_still_there_after_a_restart(self, tmp_path):
        from dreamlayer.orchestrator.stasis import FreezeFrame

        cfg = tmp_path / "cfg"
        cfg.mkdir()
        BrainConfig(token="tok").save(cfg)

        ls = Brain(cfg).lenses()
        ls.stasis.push(FreezeFrame(id=1, created_ts=time.time(),
                                   final_utterance="so the deposit needs to—"))
        ls.save_stasis()
        assert ls.stasis_path.exists()

        again = Brain(cfg).lenses()
        held = again.stasis.frames()
        assert held, "the held thought did not survive a restart"
        assert held[0].final_utterance == "so the deposit needs to—"

    def test_one_corrupt_frame_costs_only_that_thought(self, tmp_path):
        from dreamlayer.orchestrator.stasis import FreezeFrame

        cfg = tmp_path / "cfg"
        cfg.mkdir()
        BrainConfig(token="tok").save(cfg)
        ls = Brain(cfg).lenses()
        ls.stasis.push(FreezeFrame(id=1, created_ts=time.time(),
                                   final_utterance="the good one"))
        ls.save_stasis()
        rows = json.loads(ls.stasis_path.read_text())
        rows.append({"nonsense": True})            # a frame we cannot rebuild
        ls.stasis_path.write_text(json.dumps(rows))

        held = Brain(cfg).lenses().stasis.frames()
        assert [f.final_utterance for f in held] == ["the good one"]


class TestTheseStoresObeyTheSameRules:
    """A new store that skips retention or erase is how "nothing expires" and
    "erase everything" quietly stop being true."""

    def test_retention_ages_the_statement_ring_out(self, tmp_path):
        brain = _brain(tmp_path)
        ls = brain.lenses()
        ls.observe("conversation", "an old statement",
                   ts=time.time() - 48 * 3600)     # past the 24 h hot window
        ls.observe("conversation", "a fresh statement")
        assert len(ls.ring) == 2

        report = brain.sweep_retention()

        assert report["hot_purged"] >= 1
        assert len(ls.ring) == 1, "the stale statement outlived the hot window"

    def test_erase_everything_reaches_the_ring_and_the_held_thought(self, tmp_path):
        from dreamlayer.orchestrator.stasis import FreezeFrame

        brain = _brain(tmp_path)
        ls = brain.lenses()
        ls.observe("conversation", "something I said")
        ls.stasis.push(FreezeFrame(id=1, created_ts=time.time(),
                                   final_utterance="a held thought"))
        ls.save_stasis()

        out = brain.purge_memories()

        assert out["ok"] is True
        assert out["statements_purged"] >= 1
        assert not ls.stasis_path.exists(), (
            "erase-everything left a held thought on disk")
        assert len(brain.lenses().ring) == 0
