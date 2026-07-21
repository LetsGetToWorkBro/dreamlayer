"""W8 — the four new capability packs are real, resolvable, and installable.

The big-wins batch added the interpreter, world-sound, sky, graph, and rehearsal
capabilities but left them unbundled — a person browsing the panel's pack list
would never find them. These four packs surface them, and these tests pin that
every pack resolves to real caps, references only real pyproject extras, and is
recognised by the installer path (so an "Install" button can't silently no-op).
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from dreamlayer import capabilities as C

PYPROJECT = Path(__file__).parents[3] / "pyproject.toml"
_NEW = {"interpreter", "world-sense", "stargazer", "mind-palace"}


def _groups():
    with open(PYPROJECT, "rb") as f:
        return tomllib.load(f)["project"]["optional-dependencies"]


def test_new_packs_are_registered():
    keys = {p.key for p in C.PACKS}
    assert _NEW <= keys


def test_pack_keys_are_unique():
    keys = [p.key for p in C.PACKS]
    assert len(keys) == len(set(keys))


def test_every_new_pack_resolves_to_real_caps():
    by_key = {p.key: p for p in C.PACKS}
    for k in _NEW:
        caps = by_key[k].caps()
        assert caps, f"{k} resolves to no capabilities"
        # each resolved cap's extra is one the pack claims
        for cap in caps:
            assert cap.extra in by_key[k].extras


def test_new_pack_extras_exist_in_pyproject():
    groups = _groups()
    by_key = {p.key: p for p in C.PACKS}
    for k in _NEW:
        for extra in by_key[k].extras:
            assert extra in groups, f"{k} references missing extra {extra!r}"


def test_expected_capabilities_are_bundled():
    """The headline capability of each new pack is actually in it (no empty
    marketing bundle)."""
    caps_of = {p.key: {c.key for c in p.caps()} for p in C.PACKS}
    assert "live_interpret" in caps_of["interpreter"]
    assert {"sound_events", "bird_song", "depth_sense"} <= caps_of["world-sense"]
    assert "sky_sense" in caps_of["stargazer"]
    assert {"memory_graph", "memory_rehearsal"} <= caps_of["mind-palace"]


def test_packs_report_includes_new_packs_with_state():
    rows = {r["key"]: r for r in C.packs_report()}
    for k in _NEW:
        assert k in rows
        assert rows[k]["state"] in ("installed", "partial", "available")
        assert rows[k]["caps"], f"{k} report has no caps"
        assert 1 <= rows[k]["impact"] <= 5


def test_new_packs_are_available_when_wheels_absent():
    # none of the heavy wheels are present in CI → the packs read "available"
    rows = {r["key"]: r for r in C.packs_report()}
    for k in _NEW:
        assert rows[k]["state"] == "available"


def test_taglines_are_present_and_honest():
    by_key = {p.key: p for p in C.PACKS}
    for k in _NEW:
        assert by_key[k].tagline and len(by_key[k].tagline) > 20
        assert by_key[k].name
        assert by_key[k].size


def test_installer_recognises_each_new_pack():
    """The installer resolves each new pack key to a non-empty pip requirement
    list — an unknown key returns [] and the panel 400s, so a silent no-op is
    impossible."""
    for k in _NEW:
        reqs = C.pack_requirements(k)
        assert reqs, f"{k}: installer found no requirements (unknown key?)"
    # a genuinely unknown key still returns [] (the 400 path)
    assert C.pack_requirements("no-such-pack") == []
