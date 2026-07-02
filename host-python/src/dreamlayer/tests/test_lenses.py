"""test_lenses.py — the six-lens registry is well-formed (pure metadata)."""
from __future__ import annotations

from dreamlayer.lenses import (
    LENSES, SPINE, ATMOSPHERE, all_features, find_feature, lens_of,
)


def test_exactly_six_primary_lenses():
    assert [l.key for l in LENSES] == [
        "memory", "people", "truth", "world", "life", "together"]


def test_every_lens_has_features_and_a_tagline():
    for lens in LENSES:
        assert lens.features and lens.name and lens.tagline


def test_feature_keys_are_globally_unique():
    keys = [f.key for f in all_features()]
    assert len(keys) == len(set(keys))


def test_the_truth_family_is_one_lens():
    truth = next(l for l in LENSES if l.key == "truth")
    assert {f.key for f in truth.features} == {
        "truth_lens", "candor", "provenance"}


def test_lookup_and_reverse_lookup():
    assert find_feature("saga").name == "Saga"
    assert lens_of("saga").key == "life"
    assert lens_of("provenance").key == "truth"
    assert lens_of("prism") is None            # atmosphere, not a primary lens


def test_spine_and_atmosphere_present():
    assert any(f.key == "privacy_veil" for f in SPINE)
    assert {f.key for f in ATMOSPHERE} == {
        "inner_weather", "prism", "palette_cycling"}


def test_modules_are_declared():
    assert all(f.module for f in all_features())
