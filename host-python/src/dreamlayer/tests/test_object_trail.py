"""The trail behind a thing you walked away from.

`WaypathLens` has answered "where are my keys" since it was written, from
anchors its own docstring says are dropped "when it sees where you left
something". Nothing in the tree ever saw: every anchor came from the wearer
narrating one out loud, so the feature only worked for the things they thought
to mention — never the things they actually lose.

These cover the producer that closes it, at three layers: the detections the
vision ladder can and cannot give, the trail that turns them into departures,
and the ambient path that turns a departure into an anchor `waypath_locate`
answers from.
"""
import pytest

from dreamlayer.object_lens.classify_backends import detections
from dreamlayer.orchestrator.object_trail import (
    MIN_FRAMES, NOT_A_THING, ObjectTrail,
)


class FakeTracker:
    """`update([(cx, cy), …]) -> [id, …]`, nearest-centroid, exactly the shape
    `SupervisionTracker` promises. Its own logic is tested elsewhere; what
    matters here is that the trail SPEAKS the shape."""

    def __init__(self, max_dist=0.15):
        self.max_dist = max_dist
        self._prev: dict = {}
        self._next = 1

    def update(self, centroids):
        out = []
        taken = set()
        for cx, cy in centroids:
            best, best_d = None, self.max_dist
            for tid, (px, py) in self._prev.items():
                if tid in taken:
                    continue
                d = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
                if d <= best_d:
                    best, best_d = tid, d
            if best is None:
                best = self._next
                self._next += 1
            taken.add(best)
            self._prev[best] = (cx, cy)
            out.append(best)
        return out


class LabelOnlyLadder:
    """Every rung but YOLO: one label for the whole frame, no geometry."""

    def __init__(self, hit=("mug", 0.9)):
        self.hit = hit

    def __call__(self, frame):
        return self.hit


class BoxLadder:
    """A localising rung — the shape `YoloClassifier.detect` now exposes."""

    def __init__(self, rows):
        self.rows = rows

    def detect(self, frame, min_confidence=0.25):
        return [r for r in self.rows if r[1] >= min_confidence]

    def __call__(self, frame):
        return (self.rows[0][0], self.rows[0][1]) if self.rows else None


# ------------------------------------------------------------- the detections

class TestDetections:
    def test_a_localising_rung_gives_every_box_with_a_centroid(self):
        rows = detections(BoxLadder([("mug", 0.9, (0.2, 0.3)),
                                     ("book", 0.6, (0.8, 0.4))]), None)
        assert rows == [("mug", 0.9, (0.2, 0.3)), ("book", 0.6, (0.8, 0.4))]

    def test_a_label_only_rung_says_what_not_where(self):
        # `None`, not a fabricated centre point. A head-mounted camera's centre
        # is where the wearer is looking, so "centre of frame" would look
        # perfectly reasonable and would make every label-only rung report an
        # object that never moves, at the same spot, forever.
        assert detections(LabelOnlyLadder(), None) == [("mug", 0.9, None)]

    def test_a_rung_that_sees_nothing_gives_nothing(self):
        assert detections(LabelOnlyLadder(hit=None), None) == []
        assert detections(BoxLadder([]), None) == []

    def test_low_confidence_boxes_are_dropped(self):
        rows = detections(BoxLadder([("mug", 0.9, (0.2, 0.3)),
                                     ("ghost", 0.05, (0.1, 0.1))]), None)
        assert [r[0] for r in rows] == ["mug"]

    def test_a_low_confidence_single_label_is_dropped_too(self):
        assert detections(LabelOnlyLadder(hit=("mug", 0.05)), None) == []

    def test_a_ladder_that_raises_is_not_an_exception_upward(self):
        class Boom:
            def __call__(self, frame):
                raise RuntimeError("backend died mid-frame")
        assert detections(Boom(), None) == []

    def test_a_detect_with_a_narrower_signature_still_works(self):
        class OldStyle:
            def detect(self, frame):
                return [("mug", 0.9, (0.5, 0.5))]
        assert detections(OldStyle(), None) == [("mug", 0.9, (0.5, 0.5))]

    def test_a_detect_returning_none_falls_back_to_the_label(self):
        # `None` means "this backend cannot localise right now" (no model
        # loaded), which is different from "it saw nothing".
        class Unloaded:
            def detect(self, frame, min_confidence=0.25):
                return None

            def __call__(self, frame):
                return ("mug", 0.9)
        assert detections(Unloaded(), None) == [("mug", 0.9, None)]


class TestYoloDetect:
    """`YoloClassifier.detect` on a stubbed ultralytics result — the geometry
    `__call__` throws away, which is what nothing in the tree ever produced."""

    def _yolo(self, boxes, shape=(200.0, 100.0)):
        from dreamlayer.object_lens.classify_backends import YoloClassifier

        class Tensorish(list):
            # ultralytics hands back a torch tensor; `.tolist()` is the shape
            # every call site in the tree already uses (person_guard,
            # vision_extras). A plain list stub would pass a broken reader.
            def tolist(self):
                return list(self)

        class Box:
            def __init__(self, xyxy, conf, cls):
                self.xyxy = [Tensorish(xyxy)]
                self.conf, self.cls = [conf], [cls]

        class Res:
            orig_shape = shape
            names = {0: "mug", 1: "book"}

            def __init__(self, bs):
                self.boxes = bs

        y = YoloClassifier.__new__(YoloClassifier)
        y._model = lambda frame, verbose=False: [
            Res([Box(b, c, k) for b, c, k in boxes])]
        return y

    def test_every_box_comes_back_normalised(self):
        y = self._yolo([([0.0, 0.0, 20.0, 40.0], 0.9, 0),
                        ([50.0, 100.0, 70.0, 140.0], 0.7, 1)])
        assert y.detect(None) == [("mug", 0.9, (0.1, 0.1)),
                                  ("book", 0.7, (0.6, 0.6))]

    def test_the_confidence_floor_applies(self):
        y = self._yolo([([0.0, 0.0, 20.0, 40.0], 0.1, 0)])
        assert y.detect(None) == []

    def test_no_model_is_none_not_empty(self):
        from dreamlayer.object_lens.classify_backends import YoloClassifier
        y = YoloClassifier.__new__(YoloClassifier)
        y._model = None
        assert y.detect(None) is None

    def test_a_degenerate_frame_is_no_detections(self):
        assert self._yolo([([0.0, 0.0, 1.0, 1.0], 0.9, 0)],
                          shape=(0.0, 0.0)).detect(None) == []


# ------------------------------------------------------------------ the trail

class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        self.t += 10.0
        return self.t


def _feed(trail, frames):
    """Run frames through and return the departures from each."""
    return [trail.observe(f) for f in frames]


class TestTheTrail:
    def test_a_thing_seen_then_gone_departs(self):
        t = ObjectTrail(now_fn=Clock())
        out = _feed(t, [[("mug", 0.9, None)]] * 3 + [[], []])
        assert all(o == [] for o in out[:-1])
        assert [d.label for d in out[-1]] == ["mug"]

    def test_a_blink_is_not_a_departure(self):
        # A hand passing over the keys must not lose them.
        t = ObjectTrail(now_fn=Clock(), patience=2)
        mug = [("mug", 0.9, None)]
        out = _feed(t, [mug, mug, [], mug, mug])
        assert all(o == [] for o in out)
        assert [x.label for x in t.present()] == ["mug"]

    def test_a_flicker_is_not_a_sighting(self):
        # One mis-classified frame must not anchor a thing that was never there.
        t = ObjectTrail(now_fn=Clock(), min_frames=MIN_FRAMES)
        out = _feed(t, [[("ufo", 0.9, None)], [], []])
        assert all(o == [] for o in out)

    def test_the_departure_carries_how_long_it_was_there(self):
        t = ObjectTrail(now_fn=Clock())
        out = _feed(t, [[("mug", 0.9, None)]] * 4 + [[], []])
        d, = out[-1]
        assert d.frames == 4 and d.dwell_s == pytest.approx(30.0)

    def test_a_person_is_never_trailed(self):
        t = ObjectTrail(now_fn=Clock())
        out = _feed(t, [[("person", 0.99, None)]] * 3 + [[], []])
        assert all(o == [] for o in out)
        assert t.present() == []

    def test_scenery_is_never_trailed(self):
        t = ObjectTrail(now_fn=Clock())
        rows = [[(w, 0.9, None)] for w in ("wall", "ceiling", "sky")]
        for r in rows:
            t.observe(r)
        assert t.present() == []

    def test_a_multi_word_label_containing_a_refused_word_is_refused(self):
        t = ObjectTrail(now_fn=Clock())
        t.observe([("a person standing", 0.9, None)])
        assert t.present() == []

    def test_a_multi_word_label_that_merely_contains_the_letters_is_kept(self):
        # "personal organizer" is a thing you lose; refusing on a substring
        # rather than a word would drop it.
        t = ObjectTrail(now_fn=Clock())
        t.observe([("personal organizer", 0.9, None)])
        assert [x.label for x in t.present()] == ["personal organizer"]

    def test_every_refused_word_is_actually_refused(self):
        t = ObjectTrail(now_fn=Clock())
        for word in NOT_A_THING:
            t.observe([(word, 0.9, None)])
        assert t.present() == []

    def test_the_departure_remembers_what_it_was_beside(self):
        # "beside the notebook" — the copy the object-recall card has always
        # shown, with nothing behind it until now.
        t = ObjectTrail(now_fn=Clock())
        both = [("mug", 0.9, None), ("notebook", 0.8, None)]
        out = _feed(t, [both, both, [("notebook", 0.8, None)]] +
                    [[("notebook", 0.8, None)]])
        d, = [x for o in out for x in o]
        assert d.label == "mug" and d.neighbours == ("notebook",)

    def test_a_thing_is_never_its_own_neighbour(self):
        t = ObjectTrail(now_fn=Clock())
        mug = [("mug", 0.9, None)]
        out = _feed(t, [mug, mug, [], []])
        d, = out[-1]
        assert d.neighbours == ()

    def test_the_place_follows_the_thing_not_the_wearer(self):
        # Once it is gone, the place it was left in must not follow the wearer
        # down the hall.
        t = ObjectTrail(now_fn=Clock())
        mug = [("mug", 0.9, None)]
        t.observe(mug, place="the kitchen")
        t.observe(mug, place="the kitchen")
        t.observe([], place="the hallway")
        out = t.observe([], place="the porch")
        assert [(d.label, d.place) for d in out] == [("mug", "the kitchen")]

    def test_trails_age_out(self):
        clock = Clock()
        t = ObjectTrail(now_fn=clock, forget_after_s=15.0)
        t.observe([("mug", 0.9, None)])
        clock.t += 3600.0
        t.observe([("book", 0.8, None)])
        t.observe([("book", 0.8, None)])
        assert [x.label for x in t.present()] == ["book"]

    def test_forget_all_clears_everything(self):
        t = ObjectTrail(now_fn=Clock())
        t.observe([("mug", 0.9, None), ("book", 0.8, None)])
        assert t.forget_all() == 2 and t.present() == []


class TestIdentity:
    def test_two_of_the_same_thing_stay_two_things(self):
        # The tracker's whole contribution. Without it these merge, and losing
        # one mug looks like losing both.
        t = ObjectTrail(tracker=FakeTracker(), now_fn=Clock())
        two = [("mug", 0.9, (0.2, 0.2)), ("mug", 0.9, (0.8, 0.8))]
        t.observe(two)
        t.observe(two)
        assert len(t.present()) == 2
        # one leaves, the other stays
        one = [("mug", 0.9, (0.2, 0.2))]
        assert t.observe(one) == []
        out = t.observe(one)
        assert [d.label for d in out] == ["mug"]
        assert len(t.present()) == 1

    def test_without_a_tracker_a_label_is_its_own_identity(self):
        t = ObjectTrail(now_fn=Clock())
        two = [("mug", 0.9, (0.2, 0.2)), ("mug", 0.9, (0.8, 0.8))]
        t.observe(two)
        t.observe(two)
        assert len(t.present()) == 1          # honestly degraded, not broken

    def test_a_moving_thing_keeps_one_identity(self):
        t = ObjectTrail(tracker=FakeTracker(), now_fn=Clock())
        for x in (0.20, 0.24, 0.28, 0.32):
            t.observe([("mug", 0.9, (x, 0.5))])
        assert len(t.present()) == 1
        assert t.present()[0].frames == 4

    def test_a_tracker_that_raises_falls_back_to_labels(self):
        class Broken:
            def update(self, centroids):
                raise RuntimeError("bytetrack blew up")
        t = ObjectTrail(tracker=Broken(), now_fn=Clock())
        t.observe([("mug", 0.9, (0.2, 0.2))])
        t.observe([("mug", 0.9, (0.2, 0.2))])
        assert [x.label for x in t.present()] == ["mug"]

    def test_a_localised_departure_says_so(self):
        t = ObjectTrail(tracker=FakeTracker(), now_fn=Clock())
        t.observe([("mug", 0.9, (0.2, 0.2))])
        t.observe([("mug", 0.9, (0.2, 0.2))])
        t.observe([])
        out = t.observe([])
        assert out and out[0].localised is True

    def test_a_label_only_departure_says_so_too(self):
        t = ObjectTrail(now_fn=Clock())
        t.observe([("mug", 0.9, None)])
        t.observe([("mug", 0.9, None)])
        t.observe([])
        out = t.observe([])
        assert out and out[0].localised is False


class TestTrackingIsProven:
    """`object_tracking` is promoted from proof, never from the wheel being
    importable — the rule every other runtime-promoted capability follows."""

    def test_a_tracker_nobody_feeds_is_not_live(self):
        class ByteTrackish:
            _tracker = object()               # the real library, constructed

            def update(self, centroids):
                return []
        t = ObjectTrail(tracker=ByteTrackish(), now_fn=Clock())
        assert t.tracking_live() is False     # …and never handed a centroid
        t.observe([("mug", 0.9, None)])       # a label-only rung gives it none
        assert t.tracking_live() is False

    def test_the_centroid_fallback_is_not_the_library(self):
        # `SupervisionTracker` falls back to nearest-centroid with supervision
        # absent, so ids alone prove nothing about the capability.
        fallback = FakeTracker()
        fallback._tracker = None
        t = ObjectTrail(tracker=fallback, now_fn=Clock())
        t.observe([("mug", 0.9, (0.2, 0.2))])
        assert t.tracked == 1 and t.tracking_live() is False

    def test_a_real_tracker_given_a_centroid_is_live(self):
        class ByteTrackish(FakeTracker):
            _tracker = object()
        t = ObjectTrail(tracker=ByteTrackish(), now_fn=Clock())
        t.observe([("mug", 0.9, (0.2, 0.2))])
        assert t.tracking_live() is True

    def test_no_tracker_at_all_is_not_live(self):
        t = ObjectTrail(now_fn=Clock())
        t.observe([("mug", 0.9, (0.2, 0.2))])
        assert t.tracking_live() is False


class TestRealTracker:
    """Against `SupervisionTracker` itself — the seam that has taken a centroid
    list since it was written and never been handed one by anything but its own
    tests."""

    def test_the_shipped_tracker_fits_the_trail(self):
        from dreamlayer.dream_mode.track_supervision import SupervisionTracker
        t = ObjectTrail(tracker=SupervisionTracker(), now_fn=Clock())
        two = [("mug", 0.9, (0.2, 0.2)), ("book", 0.8, (0.8, 0.8))]
        t.observe(two)
        t.observe(two)
        assert {x.label for x in t.present()} == {"mug", "book"}
