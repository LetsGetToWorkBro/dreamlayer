"""test_refine.py — rehearsal refinement (INNOVATION_SESSION 5.3).

When a figment is banished at the same scene again and again, the compiler
proposes the trim in rehearsal words and re-signs a variant with the lineage
kept. Pins the hotspot detection, the proposal copy/threshold, that the variant
is a fresh budget-verified figment carrying its parentage, and the Brain surface.
"""
from __future__ import annotations

import pytest

from dreamlayer.reality_compiler.v2 import (
    Figment, Scene, TextLine, Transition, END,
    RealityCompilerV2, propose_refinement, build_variant, banish_hotspot,
)


def _timer(name="Rounds", dur=1500.0):
    f = Figment(name=name, initial="run")
    f.add_scene(Scene(id="run", duration_sec=dur, lines=[TextLine(name, row=0)],
                      on_timeout=[Transition(target=END)]))
    return f


# -- hotspot + proposal -------------------------------------------------------

def test_hotspot_needs_repetition():
    hist = [{"action": "banish", "scene": "run", "elapsed": 1200.0}]
    assert banish_hotspot(hist, min_banishes=2) is None            # once isn't a pattern
    hist.append({"action": "banish", "scene": "run", "elapsed": 1180.0})
    hot = banish_hotspot(hist, min_banishes=2)
    assert hot["scene"] == "run" and hot["count"] == 2
    assert 1180 <= hot["elapsed"] <= 1200                          # mean of the two


def test_proposal_meets_you_where_you_stop():
    fig = _timer(dur=1500.0)   # 25:00
    hist = [{"action": "banish", "scene": "run", "elapsed": 1200.0},
            {"action": "banish", "scene": "run", "elapsed": 1200.0}]
    p = propose_refinement(fig, hist)
    assert p is not None
    assert p.suggested_sec == pytest.approx(1200.0)               # trim 25:00 → 20:00
    assert "20:00" in p.reason and "25:00" in p.reason
    assert "20:00" in " ".join(p.card().hud_lines())


def test_no_proposal_without_a_pattern():
    fig = _timer()
    assert propose_refinement(fig, [{"action": "complete"}]) is None
    assert propose_refinement(fig, [{"action": "banish", "scene": "run",
                                     "elapsed": 1200.0}]) is None  # only once


def test_no_proposal_when_no_timing_would_trim_below_floor():
    fig = _timer(dur=0.6)      # already at the floor; nothing to trim
    hist = [{"action": "banish", "scene": "run"}] * 2
    assert propose_refinement(fig, hist) is None


def test_falls_back_to_a_trim_without_timing():
    fig = _timer(dur=1000.0)
    hist = [{"action": "banish", "scene": "run"},   # no elapsed captured
            {"action": "banish", "scene": "run"}]
    p = propose_refinement(fig, hist)
    assert p is not None and p.suggested_sec < 1000.0


# -- the variant --------------------------------------------------------------

def test_variant_is_fresh_and_keeps_lineage():
    fig = _timer(dur=1500.0)
    v = build_variant(fig, "run", 1200.0)
    assert v.id != fig.id                                          # a new identity
    assert v.scenes["run"].duration_sec == 1200.0
    assert v.meta["refined_from"] == fig.id and v.meta["refined_scene"] == "run"
    assert fig.scenes["run"].duration_sec == 1500.0               # original untouched


# -- end to end through the compiler + vault ----------------------------------

def test_apply_refinement_signs_and_keeps_both(tmp_path):
    rc = RealityCompilerV2(vault_dir=tmp_path / "v")
    fig = _timer(dur=1500.0)
    rc.keep(fig)
    for _ in range(2):
        rc.deploy(fig.id)
        rc.record_outcome(fig.id, "banish", scene="run", elapsed=1200.0)
    p = rc.refine_proposal(fig.id)
    assert p is not None and p.scene == "run"
    entry = rc.apply_refinement(p)
    assert entry.figment.meta["refined_from"] == fig.id
    assert entry.sig                                              # re-signed
    ids = {e.figment.id for e in rc.repertoire()}
    assert fig.id in ids and entry.figment.id in ids             # family kept


# -- the Brain surface --------------------------------------------------------

class TestBrainSurface:
    def _brain(self, tmp_path):
        from dreamlayer.ai_brain.server import Brain
        return Brain(tmp_path)

    def test_suggestion_then_one_tap_apply(self, tmp_path):
        brain = self._brain(tmp_path)
        fig = _timer(dur=1500.0)
        brain.rc.keep(fig)
        for _ in range(2):
            brain.rc.record_outcome(fig.id, "banish", scene="run", elapsed=1200.0)
        sug = brain.rc_refine_suggestion(fig.id)
        assert sug["proposal"] and sug["proposal"]["scene"] == "run"
        applied = brain.rc_refine_apply(fig.id)
        assert applied["ok"] is True and applied["entry"]["name"] == "Rounds"

    def test_nothing_to_refine_is_graceful(self, tmp_path):
        brain = self._brain(tmp_path)
        fig = _timer()
        brain.rc.keep(fig)
        assert brain.rc_refine_suggestion(fig.id)["proposal"] is None
        assert brain.rc_refine_apply(fig.id)["ok"] is False
