"""test_perception_club.py — the 350ms Club perception bench (1.4).

Pins the bundled labeled set is deterministic, the deadline runner drops
over-budget answers (so a slow perceptor can't score), the offline vision
ladder clears its own floor, and the CLI prints/【json】s a report.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("numpy")   # the bench needs the perception extra

from dreamlayer.object_lens import bench
from dreamlayer import cli


def test_sample_set_is_deterministic_and_labeled():
    a = bench.sample_set()
    b = bench.sample_set()
    assert len(a) == 24 and [lbl for _, lbl in a] == [lbl for _, lbl in b]
    import numpy as np
    assert np.array_equal(a[0][0], b[0][0])          # same seed → same pixels


def test_offline_ladder_clears_a_floor():
    res = bench.run_perception_bench()
    assert res.n == 24
    assert res.accuracy >= 0.75                       # the coarse kinds separate
    assert res.dropped == 0                           # the heuristic is microseconds
    assert 0.0 < res.score <= 1.0


def test_a_slow_perceptor_is_dropped_not_scored():
    import time

    def molasses(frame):
        time.sleep(0.02)                              # 20ms > a 5ms budget
        return ("houseplant", 0.9)                    # would be right if counted

    res = bench.run_perception_bench(classifier=molasses, deadline_ms=5.0)
    assert res.dropped == res.n                        # every answer was late
    assert res.correct == 0 and res.accuracy == 0.0    # lateness ≠ correct


def test_a_declining_perceptor_scores_zero_without_being_dropped():
    res = bench.run_perception_bench(classifier=lambda f: None)
    assert res.dropped == 0 and res.correct == 0       # in-budget, just wrong


def test_cli_reports_a_score(capsys):
    assert cli.main(["bench", "perception"]) == 0
    out = capsys.readouterr().out
    assert "350ms Club" in out and "score" in out


def test_cli_json(capsys):
    assert cli.main(["bench", "perception", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["n"] == 24 and "score" in doc and "mean_ms" in doc
