"""test_catalog.py — every glasses feature is demo-ready.

The catalog maps each feature to a real card and generates both a per-feature
clip and one master film, so a full-product demo is a single command.
"""
from __future__ import annotations

import json

from dreamlayer.demo.catalog import (
    FEATURES, feature_scenes, master_scene, write_catalog_md,
)
from dreamlayer.demo import render_scene
from dreamlayer.hud.cards import ALL_SAMPLES


def test_every_feature_maps_to_a_real_card_and_is_unique():
    ids = [f.id for f in FEATURES]
    assert len(ids) == len(set(ids))                     # no duplicate ids
    for f in FEATURES:
        assert f.card in ALL_SAMPLES, f.id
        assert f.title and f.blurb and f.group


def test_broad_coverage():
    # a real full-product demo, not a handful
    assert len(FEATURES) >= 20
    groups = {f.group for f in FEATURES}
    assert len(groups) >= 4                              # multiple sections


def test_master_film_covers_every_feature_in_order():
    m = master_scene()
    assert len(m.beats) == len(FEATURES)
    # monotonic, non-overlapping-enough timing
    for a, b in zip(m.beats, m.beats[1:]):
        assert a.t_in < b.t_in
    assert m.duration() > 60.0                           # the whole product


def test_per_feature_scenes_are_one_card_each():
    scenes = feature_scenes()
    assert set(scenes) == {f.id for f in FEATURES}
    for s in scenes.values():
        assert len(s.beats) == 1


def test_catalog_md_lists_every_feature(tmp_path):
    p = tmp_path / "catalog.md"
    write_catalog_md(p)
    text = p.read_text()
    for f in FEATURES:
        assert f.title in text


def test_a_feature_clip_and_the_master_render(tmp_path):
    render_scene(feature_scenes()["veritas"], tmp_path / "veritas", preview_fps=4)
    assert (tmp_path / "veritas" / "manifest.json").exists()

    m = master_scene()
    m.size = (240, 426)                                  # tiny + slow to stay light
    manifest = render_scene(m, tmp_path / "master", preview_fps=2)
    assert (tmp_path / "master" / "poster.png").exists()
    assert len(json.loads((tmp_path / "master" / "manifest.json").read_text())["beats"]) == len(FEATURES)
