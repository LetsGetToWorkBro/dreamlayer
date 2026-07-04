"""test_storyboards.py — the viral clips render as real, exportable scenes.

Each storyboard is built from real HUD cards and must export cleanly (overlays +
manifest + preview) so a compositor can drop it over footage.
"""
from __future__ import annotations

import json

from dreamlayer.demo.storyboards import SCENES
from dreamlayer.demo import render_scene


def test_the_clips_exist():
    assert {"veritas", "answer_ahead", "owe_someone", "the_tour"} <= set(SCENES)


def test_the_tour_shows_breadth():
    tour = SCENES["the_tour"]
    types = {b.card.get("type") for b in tour.beats}
    # several distinct features, not just the fact-checker
    assert "FactCheckCard" in types
    assert len(types) >= 5
    assert tour.duration() >= 25.0


def test_every_beat_is_a_real_card_with_sane_timing():
    for name, scene in SCENES.items():
        assert scene.beats, name
        for b in scene.beats:
            assert isinstance(b.card, dict) and b.card.get("type"), name
            assert 0.0 <= b.t_in < b.t_out, (name, b.label)
            assert 0.0 < b.width <= 1.0 and 0.0 <= b.anchor[0] <= 1.0


def test_veritas_lands_on_the_fused_fact_check():
    beats = SCENES["veritas"].beats
    fc = [b for b in beats if b.card.get("type") == "FactCheckCard"]
    assert fc and fc[0].card["verdict"] == "self_contradiction"
    assert "seen before" in fc[0].card["footer"]     # the fused delivery tag


def test_each_scene_renders_a_full_bundle(tmp_path):
    for name, scene in SCENES.items():
        out = tmp_path / name
        # smaller + slow fps to keep the test light
        scene.size = (360, 640)
        manifest = render_scene(scene, out, preview_fps=4)
        assert (out / "manifest.json").exists()
        assert (out / "preview.gif").exists()
        assert (out / "poster.png").exists()
        m = json.loads((out / "manifest.json").read_text())
        assert len(m["beats"]) == len(scene.beats)
        for b in m["beats"]:
            assert (out / b["overlay"]).exists()
