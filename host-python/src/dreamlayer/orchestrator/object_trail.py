"""object_trail.py — the thing you walked away from, and where it was.

`WaypathLens` answers "where are my keys" from an anchor. Its own docstring
says those anchors come "from the anchors DreamLayer already drops when it sees
where you left something" — and nothing in the tree ever saw. Every anchor came
from the wearer SAYING one out loud ("I left my bike at the north rack"), which
means the feature only ever worked for the things you thought to narrate. The
things you actually lose are the ones you put down without thinking.

This is that missing half: the ambient look loop keeps a short trail of what is
in front of the wearer, and when something they had been looking at goes away,
it drops an anchor for where it last was.

WHY DEPARTURE, AND NOT "SET DOWN"
---------------------------------
The obvious design is to detect the moment of setting a thing down — a tracked
object whose position stops changing. It is also the design that cannot be
built honestly here. Only one rung of the vision ladder can localise anything
(YOLO); the rest answer one label for the whole frame. A label-only rung has no
position, so it never shows motion, so it can never show motion *stopping* — the
feature would be silently dead on every Brain without ultralytics, which is most
of them.

Departure needs no geometry. A thing was there across several frames; now it is
not; the wearer has walked away from it. That is exactly the question Waypath
answers, it works on every rung, and it gets BETTER with a localiser rather than
requiring one: with centroids the tracker keeps two mugs apart and survives a
frame of occlusion, and without them a label is its own identity.

WHAT IT REFUSES TO DO
---------------------
* **Nothing lands under the veil.** The caller checks first and does not call;
  this class also takes no place it was not given. The Veil is about the record
  and fails CLOSED.
* **A flicker is not a sighting.** An object must be seen `min_frames` times
  before its departure means anything, or a single mis-classified frame drops
  an anchor for a thing that was never there.
* **A blink is not a departure.** It must be missing `patience` frames running,
  so a hand passing over the keys does not "lose" them.
* **It anchors things, not people and not scenery.** A person is never trailed
  (the Social Lens owns people, and `person_guard` owns that refusal); and an
  anchor for "wall" or "ceiling" is noise that would bury the one for "keys".
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger("dreamlayer.object_trail")

#: Frames an object must appear in before its departure is worth an anchor.
MIN_FRAMES = 2

#: Consecutive misses before "gone". At the live loop's several-frames-a-minute
#: cadence this is tens of seconds — long enough that a hand, a turn of the
#: head, or one bad frame does not lose the object.
PATIENCE = 2

#: Trails older than this with no sighting are dropped outright. Without it the
#: table grows for the length of the session.
FORGET_AFTER_S = 15 * 60.0

#: Never trailed, whatever the classifier says. `person` is the load-bearing
#: one — people are the Social Lens's business and the Live Lens already refuses
#: to name them — and the rest are scenery: an anchor for "wall" is not a place
#: you can walk back to, and it would bury the anchor for the thing you lost.
NOT_A_THING = frozenset({
    "person", "people", "man", "woman", "child", "face", "hand",
    "wall", "floor", "ceiling", "sky", "ground", "road", "grass", "tree",
    "window", "door", "room", "building", "water",
})


@dataclass
class Trail:
    """One thing, seen across frames."""
    key: str                       # the identity this trail is keyed by
    label: str
    first_ts: float
    last_ts: float
    frames: int = 1
    misses: int = 0
    confidence: float = 0.0
    place: str = ""
    centroid: Optional[tuple] = None
    #: True once a centroid was ever seen for it — so a caller can tell an
    #: anchor that knows where in frame from one that only knows "it was here".
    localised: bool = False

    @property
    def dwell_s(self) -> float:
        return max(0.0, self.last_ts - self.first_ts)


@dataclass
class Departure:
    """A trail that has gone. What the Waypath anchor is made from."""
    label: str
    place: str
    last_ts: float
    dwell_s: float
    frames: int
    confidence: float
    localised: bool
    #: What else was in front of the wearer the last time this was seen. A Brain
    #: with no place NAME still has this, and "beside the notebook" is a spot a
    #: person can use — it is the copy the product's own panel has always shown
    #: for object recall ("beside blue notebook · 7:42 PM"), with nothing behind
    #: it until now.
    neighbours: tuple = ()


@dataclass
class ObjectTrail:
    """Keep a trail per object; report the ones that just went away.

    `tracker` is anything with ``update([(cx, cy), …]) -> [id, …]`` aligned to
    the input order — `dream_mode.track_supervision.SupervisionTracker` is the
    one in the tree, and it is optional: without it, and for any detection with
    no centroid, the label is its own identity. That degrades exactly one thing
    (two of the same object in frame become one trail) and nothing else.
    """
    # `Any`, because the tracker is a DUCK: anything with
    # `update([(cx, cy), …]) -> [id, …]`. Naming SupervisionTracker here would
    # make the seam mandatory, and it is optional by design.
    tracker: Any = None
    min_frames: int = MIN_FRAMES
    patience: int = PATIENCE
    forget_after_s: float = FORGET_AFTER_S
    now_fn: Any = None
    trails: dict = field(default_factory=dict)
    #: How many sightings the TRACKER has given an identity to. The promotion
    #: proof for `object_tracking`: a tracker that is constructed and never
    #: handed a centroid is the dormant state this whole module exists to end,
    #: and it would look identical from the outside.
    tracked: int = 0

    def _now(self) -> float:
        fn = self.now_fn
        return float(fn()) if callable(fn) else time.time()

    @staticmethod
    def _trailable(label: str) -> bool:
        lab = (label or "").strip().lower()
        if not lab:
            return False
        # Substring, not equality: a classifier says "person" but also "a
        # person standing", and COCO-style labels arrive as "potted plant".
        # Refusing on the whole string only would let both through.
        return not any(word in lab.split() or word == lab for word in NOT_A_THING)

    def _identify(self, sightings) -> list:
        """A stable key per sighting, in input order.

        Centroids go to the tracker; everything else is keyed by its label. The
        two never collide, because a tracked key carries its numeric id.
        """
        keys: list = [None] * len(sightings)
        spatial = [(i, s[2]) for i, s in enumerate(sightings) if s[2] is not None]
        if spatial and self.tracker is not None:
            try:
                ids = self.tracker.update([c for _i, c in spatial])
            except Exception as exc:                 # noqa: BLE001
                log.warning("[trail] tracker failed: %s; keying by label", exc)
                ids = []
            for (i, _c), tid in zip(spatial, list(ids)):
                if tid is not None:
                    keys[i] = f"#{int(tid)}"
                    self.tracked += 1
        for i, (label, _conf, _cen) in enumerate(sightings):
            if keys[i] is None:
                keys[i] = f"={label.strip().lower()}"
        return keys

    def observe(self, sightings, place: str = "", now: Optional[float] = None):
        """Feed one frame; get back the trails that have just DEPARTED.

        `sightings` is `[(label, confidence, centroid_or_None), …]` — exactly
        what `object_lens.classify_backends.detections` returns.
        """
        ts = self._now() if now is None else float(now)
        rows = [(str(lab), float(conf), cen) for lab, conf, cen in (sightings or ())
                if self._trailable(lab)]
        keys = self._identify(rows)
        seen = set()
        for key, (label, conf, centroid) in zip(keys, rows):
            seen.add(key)
            t = self.trails.get(key)
            if t is None:
                self.trails[key] = Trail(
                    key=key, label=label, first_ts=ts, last_ts=ts,
                    confidence=conf, place=place, centroid=centroid,
                    localised=centroid is not None)
                continue
            t.last_ts = ts
            t.frames += 1
            t.misses = 0
            t.confidence = conf
            t.label = label
            t.centroid = centroid
            t.localised = t.localised or centroid is not None
            # The place is the wearer's CURRENT one, and only while the thing is
            # still in front of them. Once it is gone, the place it was left in
            # must not follow them down the hall.
            if place:
                t.place = place

        # Whatever is still in front of the wearer is the context a departing
        # thing was last seen beside. Read before the departures are harvested,
        # so a thing leaving in the same frame is never its own neighbour.
        alongside = tuple(dict.fromkeys(
            t.label for k, t in self.trails.items()
            if k in seen and t.frames >= self.min_frames))

        departed = []
        for key, t in list(self.trails.items()):
            if key in seen:
                continue
            t.misses += 1
            if t.misses < self.patience:
                continue
            self.trails.pop(key, None)
            if t.frames >= self.min_frames:
                departed.append(Departure(
                    label=t.label, place=t.place, last_ts=t.last_ts,
                    dwell_s=t.dwell_s, frames=t.frames,
                    confidence=t.confidence, localised=t.localised,
                    neighbours=tuple(n for n in alongside if n != t.label)))
        # Anything that stopped being reported at all (the loop went quiet, the
        # wearer closed the page) ages out rather than living forever.
        for key, t in list(self.trails.items()):
            if ts - t.last_ts > self.forget_after_s:
                self.trails.pop(key, None)
        return departed

    def present(self) -> list:
        """The trails in front of the wearer right now, newest first."""
        return sorted((t for t in self.trails.values() if t.misses == 0),
                      key=lambda t: t.last_ts, reverse=True)

    def forget_all(self) -> int:
        """Drop every trail — the memory-erase hook, and what the veil coming
        down should do to anything held in memory."""
        n = len(self.trails)
        self.trails.clear()
        return n

    def tracking_live(self) -> bool:
        """True when a REAL tracker has actually given something an identity.

        Both halves are load-bearing. `SupervisionTracker` falls back to a
        nearest-centroid tracker when supervision is not installed, so ids alone
        prove nothing about the library; and a ByteTrack that was constructed
        and never handed a centroid is exactly the dormant state this module
        exists to end.
        """
        real = getattr(self.tracker, "_tracker", None) is not None
        return bool(real and self.tracked)
