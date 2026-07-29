"""Regression tests for SupervisionTracker's real tracker path (issue #545).

update() documents a list-of-(cx, cy)-centroids contract, but that input used
to raise AttributeError inside update_with_detections (a list has no
`confidence`), so every frame silently degraded to the nearest-centroid
fallback; and the `or` truth test on the tracker_id ndarray raised on
empty/multi-element arrays while SILENTLY dropping track id 0. These tests
feed raw centroids — the documented contract — and spy on both the real
tracker and the fallback so a silent degrade fails instead of passing.
"""
import numpy as np
import pytest

pytest.importorskip("supervision")

import supervision as sv  # noqa: E402

from dreamlayer.dream_mode.track_supervision import SupervisionTracker  # noqa: E402

# Two objects approach, overlap, and separate: a fast object overtakes a slow
# one on the same line. Scripted so the nearest-centroid fallback at
# max_dist=0.15 swaps the two ids at the pass (proven below).
CROSSING_FRAMES = [
    [(0.30 + 0.02 * k, 0.5), (0.42 + 0.008 * k, 0.5)] for k in range(14)
]


class _Spies:
    """Counts calls into the real tracker and into the centroid fallback."""

    def __init__(self, tracker, monkeypatch):
        self.tracker = tracker
        self.real_calls = 0
        self.fallback_calls = 0
        real_update = tracker._tracker.update_with_detections

        def spy_real(detections):
            self.real_calls += 1
            return real_update(detections)

        tracker._tracker.update_with_detections = spy_real
        original_fallback = SupervisionTracker._centroid_fallback

        def spy_fallback(self_, detections):
            self.fallback_calls += 1
            return original_fallback(self_, detections)

        monkeypatch.setattr(SupervisionTracker, "_centroid_fallback", spy_fallback)


@pytest.fixture
def spies(monkeypatch):
    tracker = SupervisionTracker()
    assert tracker.available is True
    assert tracker._tracker is not None, (
        "supervision is installed but the real tracker failed to initialise; "
        "a degraded environment must fail, not silently skip the point"
    )
    return _Spies(tracker, monkeypatch)


def test_real_tracker_is_available():
    assert SupervisionTracker().available is True


def test_crossing_tracks_keep_identity(spies):
    """The real tracker must hold both identities across the crossing, in
    input order, without ever touching the centroid fallback."""
    first = spies.tracker.update(CROSSING_FRAMES[0])
    assert len(first) == 2 and len(set(first)) == 2
    for frame in CROSSING_FRAMES[1:]:
        assert spies.tracker.update(frame) == first
    assert spies.real_calls == len(CROSSING_FRAMES)
    assert spies.fallback_calls == 0


def test_fallback_would_swap_on_the_same_scenario():
    """Scenario-choice proof: the raw nearest-centroid fallback cannot hold
    identity across the crossing — this is what update() must NOT degrade to."""
    tracker = SupervisionTracker()
    tracker._tracker = None  # force the degraded path
    results = [tracker.update(frame) for frame in CROSSING_FRAMES]
    assert results[0] == [1, 2]
    assert results[-1] == [2, 1]  # the swap


def test_tracker_id_zero_is_not_dropped(spies):
    """np.array([0]) is falsy under `or` — the old code returned [] for a real
    track. This case fails WITHOUT raising, so it needs its own assertion."""

    class _ZeroIdTracker:
        def update_with_detections(self, detections):
            return sv.Detections(
                xyxy=np.array([[0.48, 0.48, 0.52, 0.52]]),
                confidence=np.ones(1, dtype=float),
                class_id=np.zeros(1, dtype=int),
                tracker_id=np.array([0]),
            )

    spies.tracker._tracker = _ZeroIdTracker()
    assert spies.tracker.update([(0.5, 0.5)]) == [0]
    assert spies.fallback_calls == 0


def test_multi_object_frame_does_not_raise_or_degrade(spies):
    """np.array([1, 2]) raised ValueError under the old truth test; the
    exception was swallowed and the frame degraded to the fallback."""
    ids1 = spies.tracker.update([(0.2, 0.2), (0.8, 0.8)])
    ids2 = spies.tracker.update([(0.21, 0.19), (0.82, 0.79)])
    assert len(ids1) == 2 and len(set(ids1)) == 2
    assert ids2 == ids1
    assert spies.real_calls == 2
    assert spies.fallback_calls == 0


def test_empty_input_returns_empty_without_calling_tracker(spies):
    assert spies.tracker.update([]) == []
    assert spies.real_calls == 0
    assert spies.fallback_calls == 0


def test_fallback_path_still_works_when_tracker_absent(monkeypatch):
    """The degraded contract is unchanged: one stable id per input."""
    tracker = SupervisionTracker()
    tracker._tracker = None  # force the degraded path
    calls = 0
    original_fallback = SupervisionTracker._centroid_fallback

    def spy_fallback(self_, detections):
        nonlocal calls
        calls += 1
        return original_fallback(self_, detections)

    monkeypatch.setattr(SupervisionTracker, "_centroid_fallback", spy_fallback)
    ids1 = tracker.update([(0.1, 0.1), (0.8, 0.8)])
    ids2 = tracker.update([(0.11, 0.09), (0.82, 0.79)])
    assert ids1 == ids2 and len(set(ids1)) == 2
    assert calls == 2
