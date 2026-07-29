"""Private zones, and the coordinate that makes Waypath tell you a direction.

Both features needed the same missing input — where the wearer is — and neither
could have it, so both sat unbuilt for opposite-looking reasons.

PRIVATE ZONES are wired as a THIRD TERM in `incognito_now()` rather than as a
suppression path of their own. `private_zone_card` says "CAPTURE SUSPENDED ·
Memory resumes when you leave", and the only way to make that sentence true is
to raise the shield every gate in the product already consults. A parallel
mechanism would be a second thing to keep in step, and the first gate it fell
out of step with would be a card promising a silence the Brain was not keeping.

WAYPATH already computed "12 m to your left" — `WaypathLens.locate` has had the
bearing branch since it was written, and `landing/index.html` promises it in
those words. Nothing ever populated `bearing_deg`/`distance_m`, which are
documented as an IMU seam the Brain does not have. A coordinate needs no IMU,
and unlike a stored bearing it stays true after the wearer moves.
"""
from __future__ import annotations

import tempfile

import pytest

from dreamlayer.ai_brain.server import geo
from dreamlayer.ai_brain.server.server import Brain

LONDON = (51.5074, -0.1278)
PARIS = (48.8566, 2.3522)


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


def _pushes(brain):
    seen = []
    brain.push_event = lambda kind, card=None, veil_ok=False: (
        seen.append((kind, card, veil_ok)) or 1)
    return seen


def _zone(name="home", at=LONDON, radius=150):
    return {"name": name, "lat": at[0], "lon": at[1], "radius_m": radius}


# --- the arithmetic ----------------------------------------------------------

class TestTheMaths:

    def test_distance_is_metres_not_degrees(self):
        d = geo.haversine_m(*LONDON, *PARIS)
        assert 330_000 < d < 350_000, d          # London→Paris ≈ 344 km

    def test_bearing_is_clockwise_from_north(self):
        assert abs(geo.initial_bearing_deg(0.0, 0.0, 1.0, 0.0) - 0.0) < 0.5    # N
        assert abs(geo.initial_bearing_deg(0.0, 0.0, 0.0, 1.0) - 90.0) < 0.5   # E
        assert abs(geo.initial_bearing_deg(1.0, 0.0, 0.0, 0.0) - 180.0) < 0.5  # S

    def test_null_island_is_not_a_location(self):
        """A phone with no fix reports (0, 0), which is a real point in the Gulf
        of Guinea — accepting it would put a private zone there."""
        assert geo.valid_coord(*LONDON) is True
        assert geo.valid_coord(0.0, 0.0) is False
        assert geo.valid_coord(91.0, 0.0) is False
        assert geo.valid_coord("north", None) is False

    def test_a_stale_fix_is_no_fix(self):
        """A stale fix must not hold a zone's shield up after the wearer has
        driven away from it."""
        f = geo.LastFix()
        f.set(*LONDON, ts=0.0)
        assert f.get() is None
        f.set(*LONDON)
        assert f.get() is not None

    def test_a_zone_with_no_radius_is_skipped_not_treated_as_a_point(self):
        """A zone that can never match is a shield the wearer thinks they have
        and does not."""
        assert geo.zone_containing([{"name": "x", "lat": 51.5074, "lon": -0.1278}],
                                   *LONDON) == ""
        assert geo.zone_containing([_zone()], *LONDON) == "home"

    def test_one_malformed_zone_does_not_lose_the_rest(self):
        zones = [{"name": "bad", "lat": "north", "lon": None, "radius_m": 100},
                 _zone("home")]
        assert geo.zone_containing(zones, *LONDON) == "home"


# --- the shield --------------------------------------------------------------

class TestTheShieldIsReal:

    def test_inside_a_zone_the_brain_is_incognito(self, brain):
        """Not a flag the card reads — the actual shield every gate consults."""
        brain.config.private_zones = [_zone()]
        brain._last_fix.set(*LONDON)
        assert brain.private_zone_now() == "home"
        assert brain.incognito_now() is True

    def test_the_ear_actually_stops_capturing_inside_one(self, brain):
        """The claim on the card, tested through a real gate rather than
        asserted. If this passes and the card still says "capture suspended",
        the card is telling the truth."""
        from dreamlayer.ai_brain.server.ear import EarHost
        brain.config.private_zones = [_zone()]
        brain._last_fix.set(*LONDON)
        ear = EarHost(brain)
        ear.ingest_caption("something said inside the zone")
        assert ear.heard_count == 0

    def test_leaving_lifts_it(self, brain):
        brain.config.private_zones = [_zone()]
        brain._last_fix.set(*LONDON)
        assert brain.incognito_now() is True
        brain._last_fix.set(*PARIS)
        assert brain.private_zone_now() == ""
        assert brain.incognito_now() is False

    def test_no_fix_fails_OPEN_not_closed(self, brain):
        """The one gate here that deliberately fails open. An unreadable
        geofence that quietly disabled capture forever would look exactly like
        the product being broken, with no way to tell — and the wearer has
        other, explicit shields."""
        brain.config.private_zones = [_zone()]
        assert brain.here() is None
        assert brain.private_zone_now() == ""
        assert brain.incognito_now() is False

    def test_no_zones_configured_costs_nothing(self, brain):
        brain._last_fix.set(*LONDON)
        assert brain.private_zone_now() == ""
        assert brain.incognito_now() is False


# --- the card ----------------------------------------------------------------

class TestTheCard:

    def test_entering_draws_the_zone_by_name(self, brain):
        brain.config.private_zones = [_zone("the flat")]
        seen = _pushes(brain)
        brain.note_location(*LONDON)
        kind, card, veil_ok = seen[-1]
        assert kind == "private_zone" and card["type"] == "PrivateZoneCard"
        assert card["detail"] == "the flat"       # a shield with no place named
        assert "resumes when you leave" in card["footer"]

    def test_the_card_pierces_the_shield_it_announces(self, brain):
        """Same trap as PrivacyVeilCard: with the default gate the card is
        suppressed by the very state it is reporting."""
        brain.config.private_zones = [_zone()]
        seen = _pushes(brain)
        brain.note_location(*LONDON)
        assert seen[-1][2] is True

    def test_leaving_replaces_the_card(self, brain):
        """`private_zone_card` is `dismiss_ms: 0`. Without something replacing
        it the glass keeps promising "capture suspended" after capture resumed —
        a stale privacy card is a false assurance."""
        brain.config.private_zones = [_zone()]
        brain.note_location(*LONDON)
        seen = _pushes(brain)
        brain.note_location(*PARIS)
        assert seen[-1][1]["type"] == "ReadyCard"

    def test_it_announces_only_on_a_crossing(self, brain):
        """A phone reports continuously. Re-drawing the card on every fix would
        make the glass unusable inside a zone."""
        brain.config.private_zones = [_zone()]
        brain.note_location(*LONDON)
        seen = _pushes(brain)
        for _ in range(5):
            brain.note_location(51.5074, -0.1279)   # still inside
        assert seen == []

    def test_location_intake_is_not_veil_gated(self, brain):
        """The deliberate exception. A zone contributes to the shield, so gating
        this on the shield would latch it up forever the first time the wearer
        walked into one — they could never be seen to leave."""
        brain.config.private_zones = [_zone()]
        brain.note_location(*LONDON)
        assert brain.incognito_now() is True
        out = brain.note_location(*PARIS)            # accepted while veiled
        assert out["ok"] is True and out["zone"] == ""
        assert brain.incognito_now() is False

    def test_a_junk_coordinate_is_refused(self, brain):
        assert brain.note_location(0.0, 0.0)["ok"] is False
        assert brain.note_location("north", None)["ok"] is False


# --- waypath -----------------------------------------------------------------

class TestWaypathTellsYouWhichWay:

    def test_a_stashed_thing_gets_a_direction_and_a_distance(self, brain):
        """The sentence `landing/index.html` promises, finally true."""
        brain._last_fix.set(*LONDON)
        assert brain.waypath_stash("bike", "the north rack")["located"] is True
        brain._last_fix.set(51.5076, -0.1278)        # ~22 m north of the bike
        out = brain.waypath_locate("bike")
        assert out["found"] is True
        assert "m" in out["detail"] and "behind" in out["detail"], out

    def test_the_bearing_is_computed_from_where_you_are_NOW(self, brain):
        """A stored bearing is relative to wherever the wearer was standing when
        they dropped it, and is worthless the moment they walk away. Same
        anchor, two different positions, two different answers."""
        brain._last_fix.set(*LONDON)
        brain.waypath_stash("bike", "the rack")
        brain._last_fix.set(51.5076, -0.1278)        # north of it
        north_of = brain.waypath_locate("bike")["detail"]
        brain._last_fix.set(51.5072, -0.1278)        # south of it
        south_of = brain.waypath_locate("bike")["detail"]
        assert north_of and south_of and north_of != south_of

    def test_no_fix_still_answers_with_the_place(self, brain):
        """Best-effort by design: without a coordinate the wearer still gets
        "at the hall table", exactly as before."""
        out = brain.waypath_stash("keys", "the hall table")
        assert out["located"] is False
        found = brain.waypath_locate("keys")
        assert found["found"] is True and found["place"] == "the hall table"

    def test_the_card_gets_the_direction_only_when_there_is_one(self, brain):
        """`detail` used to be forced empty because `cue.text` was "at <place>"
        and would print the place twice. With a bearing it is "22m behind you",
        which is the one thing the card could not say before."""
        brain._last_fix.set(*LONDON)
        brain.waypath_stash("bike", "the rack")
        brain._last_fix.set(51.5076, -0.1278)
        seen = _pushes(brain)
        brain.waypath_locate("bike")
        assert "m" in seen[-1][1]["detail"]

        b2 = Brain(tempfile.mkdtemp())
        seen2 = _pushes(b2)
        b2.waypath_stash("keys", "the hall table")
        b2.waypath_locate("keys")
        assert seen2[-1][1]["detail"] == "", "the place was printed twice"

    def test_coordinates_survive_a_restart(self, brain):
        """An anchor that forgets where it was on the next Brain start drops
        straight back to the place-only path — the bug this fixes."""
        import pathlib
        brain._last_fix.set(*LONDON)
        brain.waypath_stash("bike", "the rack")
        again = Brain(str(pathlib.Path(brain.cfg_dir)))
        again._last_fix.set(51.5076, -0.1278)
        out = again.waypath_locate("bike")
        assert "m" in out["detail"], "lat/lon did not survive the save/load round trip"

    def test_the_routes_reach_it(self, brain):
        from dreamlayer.ai_brain.server import server as srv
        text = open(srv.__file__, encoding="utf-8").read()
        assert '"/dreamlayer/location": _post_location,' in text
        assert '"/dreamlayer/where": _get_where,' in text
