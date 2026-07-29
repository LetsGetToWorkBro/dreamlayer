"""Regression tests for SupervisionTracker's real tracker path (issue #545).

update() documents a list-of-(cx, cy)-centroids contract, but that input used
to raise AttributeError inside update_with_detections (a list has no
`confidence`), so every frame silently degraded to the nearest-centroid
fallback; and the `or` truth test on the tracker_id ndarray raised on
empty/multi-element arrays while SILENTLY dropping track id 0. These tests
feed raw centroids — the documented contract — and spy on both the real
tracker and the fallback so a silent degrade fails instead of passing.

The behavioural assertions deliberately avoid anything the fix introduces
(such as the `_centroid_fallback` helper), so against pristine upstream code
they fail with real assertion errors — on swapped ids and dropped id 0 —
not with fixture errors. Only the strict no-degrade guard and the
multi-object test use the `spies` fixture that patches `_centroid_fallback`.
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


class _RealPathSpy:
    """Wraps the real tracker's update_with_detections with a call counter.
    Works against any SupervisionTracker whose _tracker is real — including
    pristine upstream — so tests using it fail on behaviour, not on fixtures."""

    def __init__(self, tracker):
        self.tracker = tracker
        self.real_calls = 0
        self.fallback_calls = 0
        real_update = tracker._tracker.update_with_detections

        def spy_real(detections):
            self.real_calls += 1
            return real_update(detections)

        tracker._tracker.update_with_detections = spy_real


@pytest.fixture
def real_path():
    tracker = SupervisionTracker()
    assert tracker.available is True
    assert tracker._tracker is not None, (
        "supervision is installed but the real tracker failed to initialise; "
        "a degraded environment must fail, not silently skip the point"
    )
    return _RealPathSpy(tracker)


@pytest.fixture
def spies(real_path, monkeypatch):
    """Adds a centroid-fallback call counter on top of real_path. Kept
    separate because _centroid_fallback is introduced by the fix: only the
    strict no-degrade assertions belong here, never the behavioural ones."""
    original_fallback = SupervisionTracker._centroid_fallback

    def spy_fallback(self_, detections):
        real_path.fallback_calls += 1
        return original_fallback(self_, detections)

    monkeypatch.setattr(SupervisionTracker, "_centroid_fallback", spy_fallback)
    return real_path


def test_real_tracker_is_available():
    assert SupervisionTracker().available is True


def test_crossing_tracks_keep_identity(real_path):
    """The real tracker must hold both identities across the crossing, in
    input order. Behavioural first: against upstream, update() degrades to
    the centroid fallback, the fallback swaps the ids at the pass, and this
    assertion fails on the swapped values."""
    first = real_path.tracker.update(CROSSING_FRAMES[0])
    assert len(first) == 2 and len(set(first)) == 2
    for frame in CROSSING_FRAMES[1:]:
        assert real_path.tracker.update(frame) == first
    # additional guard, after the behavioural one: the real path ran throughout
    assert real_path.real_calls == len(CROSSING_FRAMES)


def test_fallback_would_swap_on_the_same_scenario():
    """Scenario-choice proof: the raw nearest-centroid fallback cannot hold
    identity across the crossing — this is what update() must NOT degrade to."""
    tracker = SupervisionTracker()
    tracker._tracker = None  # force the degraded path
    results = [tracker.update(frame) for frame in CROSSING_FRAMES]
    assert results[0] == [1, 2]
    assert results[-1] == [2, 1]  # the swap


def test_tracker_id_zero_is_not_dropped():
    """np.array([0]) is falsy under `or` — the old code returned [] for a real
    track. This case fails WITHOUT raising, so it needs its own assertion.
    The stub ignores its input, so this test is independent of how
    update_with_detections is fed and fails behaviourally against upstream."""

    class _ZeroIdTracker:
        def update_with_detections(self, detections):
            return sv.Detections(
                xyxy=np.array([[0.48, 0.48, 0.52, 0.52]]),
                confidence=np.ones(1, dtype=float),
                class_id=np.zeros(1, dtype=int),
                tracker_id=np.array([0]),
            )

    tracker = SupervisionTracker()
    assert tracker.available is True
    assert tracker._tracker is not None
    tracker._tracker = _ZeroIdTracker()
    assert tracker.update([(0.5, 0.5)]) == [0]


def test_multi_object_frame_does_not_raise_or_degrade(spies):
    """np.array([1, 2]) raised ValueError under the old truth test; the
    exception was swallowed and the frame degraded to the fallback — which is
    what the fallback spy catches here."""
    ids1 = spies.tracker.update([(0.2, 0.2), (0.8, 0.8)])
    ids2 = spies.tracker.update([(0.21, 0.19), (0.82, 0.79)])
    assert len(ids1) == 2 and len(set(ids1)) == 2
    assert ids2 == ids1
    assert spies.real_calls == 2
    assert spies.fallback_calls == 0


def test_empty_input_returns_empty_without_calling_tracker(real_path):
    assert real_path.tracker.update([]) == []
    assert real_path.real_calls == 0


def test_fallback_path_still_works_when_tracker_absent():
    """The degraded contract is unchanged: one stable id per input."""
    tracker = SupervisionTracker()
    tracker._tracker = None  # force the degraded path
    ids1 = tracker.update([(0.1, 0.1), (0.8, 0.8)])
    ids2 = tracker.update([(0.11, 0.09), (0.82, 0.79)])
    assert ids1 == ids2 and len(set(ids1)) == 2


def test_real_path_never_degrades_to_fallback(spies):
    """Strict non-vacuity guard: the whole crossing sequence — plus an empty
    frame — must be served by the real tracker, never by the centroid
    fallback. (A frame that breaks tracking continuity, e.g. a cold jump to
    brand-new objects after this sequence, legitimately triggers the
    designed per-frame fallback and is therefore not part of this guard; the
    multi-object no-degrade case is covered on a fresh tracker above.) This
    guard only makes sense against the fixed code (it patches
    _centroid_fallback); the behavioural tests carry the bite."""
    for frame in CROSSING_FRAMES:
        spies.tracker.update(frame)
    spies.tracker.update([])
    assert spies.fallback_calls == 0
    assert spies.real_calls == len(CROSSING_FRAMES)
