"""The trail on the real ambient path — a departure becomes an anchor a wearer
can ask about.

`test_object_trail.py` covers the producer in isolation. This is the wiring:
`POST /live/look?ambient=1` → `_trail_frame` → a Waypath anchor → the answer
`waypath_locate` gives, which is the thing the wearer actually experiences. The
capability being closed is exactly the "importable ≠ reachable-from-a-surface"
gap — the trail working alone would change nothing.
"""
from __future__ import annotations

import tempfile

import numpy as np
import pytest

from dreamlayer.ai_brain.server import live as live_mod
from dreamlayer.ai_brain.server.server import Brain


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


def _frame():
    return np.full((64, 64, 3), 120, np.uint8)


class Ladder:
    """Stands in for the vision ladder; `rows` is swapped between frames."""

    def __init__(self):
        self.rows = []

    def detect(self, frame, min_confidence=0.25):
        return list(self.rows)

    def __call__(self, frame):
        return (self.rows[0][0], self.rows[0][1]) if self.rows else None


@pytest.fixture
def ladder(monkeypatch):
    lad = Ladder()
    monkeypatch.setattr(live_mod, "_classifier", lambda: lad)
    return lad


def _ambient(brain, n=1):
    for _ in range(n):
        live_mod.world_look(brain, _frame(), ambient=True)


class TestTheAnchorLands:
    def test_walking_away_from_a_thing_anchors_where_it_was(self, brain, ladder):
        ladder.rows = [("mug", 0.9, (0.3, 0.3)), ("notebook", 0.8, (0.7, 0.7))]
        _ambient(brain, 2)
        ladder.rows = [("notebook", 0.8, (0.7, 0.7))]
        _ambient(brain, 2)
        cue = brain.waypath.locate("mug")
        assert cue.found is True
        # The place is the scene it was last in — the copy the object-recall
        # card has always shown, with nothing behind it until now.
        assert cue.place == "beside the notebook"

    def test_the_wearer_can_ask_and_get_the_card(self, brain, ladder):
        ladder.rows = [("keys", 0.9, None)]
        _ambient(brain, 2)
        ladder.rows = []
        _ambient(brain, 2)
        out = brain.waypath_locate("keys")
        assert out["ok"] is True and out["found"] is True
        assert "keys" in out["say"]

    def test_the_anchor_survives_a_restart(self, brain, ladder, monkeypatch):
        ladder.rows = [("keys", 0.9, None)]
        _ambient(brain, 2)
        ladder.rows = []
        _ambient(brain, 2)
        again = Brain(str(brain.cfg_dir))
        assert again.waypath.locate("keys").found is True

    def test_a_thing_still_in_front_of_you_is_not_anchored(self, brain, ladder):
        ladder.rows = [("mug", 0.9, None)]
        _ambient(brain, 6)
        assert brain.waypath.locate("mug").found is False

    def test_one_bad_frame_anchors_nothing(self, brain, ladder):
        ladder.rows = [("ufo", 0.9, None)]
        _ambient(brain, 1)
        ladder.rows = []
        _ambient(brain, 3)
        assert brain.waypath.locate("ufo").found is False

    def test_a_coordinate_is_pinned_when_the_brain_has_a_fix(self, brain, ladder,
                                                             monkeypatch):
        # The coordinate is what makes the anchor walkable — `waypath_locate`
        # computes a live bearing from it, which a stored bearing cannot give
        # once the wearer has moved.
        monkeypatch.setattr(type(brain), "here",
                            lambda self: {"lat": 45.5, "lon": -122.6})
        ladder.rows = [("keys", 0.9, None)]
        _ambient(brain, 2)
        ladder.rows = []
        _ambient(brain, 2)
        anchor, = [a for a in brain.waypath.anchors() if a.subject == "keys"]
        assert anchor.has_coord()

    def test_no_fix_is_still_an_anchor(self, brain, ladder, monkeypatch):
        monkeypatch.setattr(type(brain), "here", lambda self: None)
        ladder.rows = [("keys", 0.9, None)]
        _ambient(brain, 2)
        ladder.rows = []
        _ambient(brain, 2)
        assert brain.waypath.locate("keys").found is True


class TestTheVeil:
    """The Veil is about the RECORD and fails closed."""

    def test_nothing_is_anchored_under_the_shield(self, brain, ladder):
        brain.config.network_mode = "lan_only"      # incognito
        ladder.rows = [("keys", 0.9, None)]
        _ambient(brain, 3)
        ladder.rows = []
        _ambient(brain, 3)
        assert brain.waypath.locate("keys").found is False

    def test_the_shield_drops_the_trail_it_was_holding(self, brain, ladder):
        # A trail held across a veil would depart on the first frame after it
        # lifts, and anchor the thing to wherever the wearer is standing THEN —
        # a record made of a period the shield promised would leave none.
        ladder.rows = [("keys", 0.9, None)]
        _ambient(brain, 3)
        assert brain.object_trail.present()
        brain.config.network_mode = "lan_only"
        _ambient(brain, 1)
        assert brain.object_trail.present() == []
        brain.config.network_mode = "auto"
        ladder.rows = []
        _ambient(brain, 3)
        assert brain.waypath.locate("keys").found is False

    def test_an_unreadable_posture_anchors_nothing(self, brain, ladder,
                                                   monkeypatch):
        monkeypatch.setattr(type(brain), "incognito_now",
                            lambda self: (_ for _ in ()).throw(RuntimeError()))
        ladder.rows = [("keys", 0.9, None)]
        _ambient(brain, 3)
        ladder.rows = []
        _ambient(brain, 3)
        assert brain.waypath.locate("keys").found is False

    def test_purging_memories_takes_the_trail_too(self, brain, ladder):
        ladder.rows = [("keys", 0.9, None)]
        _ambient(brain, 3)
        assert brain.object_trail.present()
        brain.purge_memories()
        assert brain.object_trail.present() == []


class TestItNeverCostsTheLook:
    def test_a_deliberate_tap_does_not_trail(self, brain, ladder):
        # Only the passive loop sees the same scene twice, and only it should
        # pay for the trail. A tap is one frame and one answer.
        ladder.rows = [("keys", 0.9, None)]
        for _ in range(4):
            live_mod.world_look(brain, _frame())     # ambient=False
        assert brain.object_trail.present() == []

    def test_a_person_in_frame_is_never_trailed(self, brain, ladder):
        ladder.rows = [("person", 0.99, (0.5, 0.5))]
        _ambient(brain, 3)
        assert brain.object_trail.present() == []

    def test_a_trail_that_explodes_does_not_break_the_look(self, brain, ladder,
                                                           monkeypatch):
        class Boom:
            def observe(self, *a, **kw):
                raise RuntimeError("trail blew up")

            def forget_all(self):
                return 0
        monkeypatch.setattr(brain, "object_trail", Boom())
        ladder.rows = [("keys", 0.9, None)]
        out = live_mod.world_look(brain, _frame(), ambient=True)
        assert out["ok"] is True

    def test_a_brain_with_no_trail_still_looks(self, brain, ladder,
                                               monkeypatch):
        monkeypatch.setattr(brain, "object_trail", None)
        ladder.rows = [("keys", 0.9, None)]
        assert live_mod.world_look(brain, _frame(), ambient=True)["ok"] is True

    def test_the_log_line_never_carries_the_label(self, brain, ladder, caplog):
        # A classifier's word for a thing the wearer owns is theirs, not the
        # log's (tests/test_logging_discipline.py).
        import logging
        caplog.set_level(logging.INFO, logger="dreamlayer.ai_brain.live")
        caplog.set_level(logging.INFO)
        ladder.rows = [("diary", 0.9, None)]
        _ambient(brain, 2)
        ladder.rows = []
        _ambient(brain, 2)
        assert brain.waypath.locate("diary").found is True
        assert not any("diary" in r.getMessage() for r in caplog.records)
