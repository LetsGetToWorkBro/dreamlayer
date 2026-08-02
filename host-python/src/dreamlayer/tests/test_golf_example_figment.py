"""examples/figments/reflex-ladder.json is the Figment Golf entry for issue
#402 — this test runs that exact file through the REAL referee, so the entry
cannot rot: if a fixture edit breaks a budget, drops the score below its
claimed floor, or silently inflates the canonical byte count, CI fails."""
from __future__ import annotations

import json
from pathlib import Path

from dreamlayer.reality_compiler.v2.figment import Figment
from dreamlayer.reality_compiler.v2.golf import referee, score

FIXTURE = (Path(__file__).resolve().parents[4]
           / "examples" / "figments" / "reflex-ladder.json")

# Measured with `dreamlayer golf verify examples/figments/reflex-ladder.json
# --json` on the committed fixture; the floor is the achieved score, so the
# entry can't silently rot below what it claims (issue #402's "done means").
PINNED_GOLF_SCORE = 20.1
PINNED_BYTES = 4627


def _load() -> Figment:
    return Figment.from_dict(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_fixture_exists_and_decodes():
    assert FIXTURE.is_file()
    fig = _load()
    assert fig.initial in fig.scenes


def test_entry_is_eligible():
    report = referee(_load())
    assert report["ok"] is True
    assert report["violations"] == []
    assert report["warnings"] == []


def test_entry_holds_its_score_floor():
    sc = score(_load())
    assert sc["golf_score"] >= PINNED_GOLF_SCORE
    # the other half of "fewest bytes": a fixture edit that inflates the
    # canonical form fails here even if the score floor somehow still held
    assert sc["bytes"] == PINNED_BYTES
