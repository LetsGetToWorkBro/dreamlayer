"""`social_graph` — paths, mutual friends and communities over who you've met.

Two halves were missing and only one of them was the wiring.

`RelationshipGraph` shipped with `people_at` and `connections`, and the
no-networkx fallback answers BOTH identically — so installing the wheel bought
the wearer nothing, and the capability's own stated gain ("paths, mutual friends,
communities") described three queries that did not exist. Adding a caller alone
would have made the capability read green while still buying nothing.

So: the graph grew the three queries, each honest about which engine answered,
and `Brain._social_graph` builds one from the meeting log.

THE SOURCE IS MEETINGS, NOT CONTACTS, and that is the sharpest decision here.
`meetings.json` records `attendees`, and two people in one room is evidence they
have met. An address book is not: importing it asserts that everybody in it knows
everybody else, which is false and would fabricate the entire graph — every
"mutual friend" and every "circle" would be an artefact of having synced Contacts.
`test_the_graph_is_not_built_from_the_address_book` is the one that pins it.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from dreamlayer.ai_brain.server.server import Brain

PANEL = (pathlib.Path(__file__).resolve().parents[1]
         / "ai_brain" / "server" / "panel.py")


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


@pytest.fixture(params=["networkx", "fallback"])
def graph(request, monkeypatch):
    """Every query is tested on BOTH engines.

    The fallback is not a lesser path to be waved at — it is what most installs
    actually run, and a query that worked only with the wheel would be a silent
    downgrade rather than a graceful one. `communities` is the single exception and
    it says so in its own test.
    """
    from dreamlayer.social_lens import graph as G
    if request.param == "networkx":
        pytest.importorskip("networkx")
    else:
        monkeypatch.setattr(G, "_HAS_NX", False)
        monkeypatch.setattr(G.RelationshipGraph, "available", False)
    return G.RelationshipGraph()


def _meet(brain, title, *who):
    log = brain._meetings()
    log.start(title=title, attendees=list(who))
    return log


# --- the three queries, on both engines ------------------------------------

class TestMutual:

    def test_shared_people_and_shared_events_are_reported_separately(self, graph):
        """They mean different things to a person reading them: "you both know
        Priya" is a social fact, "you were both at the launch" is a where-from
        fact. One merged list loses the only thing that makes it useful."""
        graph.met_at("marcus", "the launch")
        graph.met_at("ada", "the launch")
        graph.relate("marcus", "priya")
        graph.relate("ada", "priya")
        m = graph.mutual("marcus", "ada")
        assert m["people"] == ["priya"]
        assert m["events"] == ["the launch"]

    def test_the_pair_themselves_are_never_their_own_mutual_connection(self, graph):
        graph.relate("marcus", "ada")
        graph.relate("marcus", "priya")
        graph.relate("ada", "priya")
        assert graph.mutual("marcus", "ada")["people"] == ["priya"]

    def test_a_person_has_nothing_in_common_with_themselves(self, graph):
        graph.relate("marcus", "priya")
        assert graph.mutual("marcus", "marcus") == {"people": [], "events": []}

    def test_strangers_share_nothing(self, graph):
        graph.met_at("marcus", "the launch")
        graph.met_at("ada", "a different room")
        assert graph.mutual("marcus", "ada") == {"people": [], "events": []}

    def test_an_unknown_name_does_not_raise(self, graph):
        graph.relate("marcus", "priya")
        assert graph.mutual("marcus", "nobody") == {"people": [], "events": []}


class TestPath:

    def test_a_chain_through_a_person(self, graph):
        graph.relate("marcus", "priya")
        graph.relate("priya", "ada")
        p = graph.path("marcus", "ada")
        assert [s["id"] for s in p] == ["marcus", "priya", "ada"]
        assert [s["kind"] for s in p] == ["person", "person", "person"]

    def test_a_chain_through_a_ROOM_is_typed_as_one(self, graph):
        """"Marcus → (the launch) → Ada" — which step is a person and which is a
        room is the whole meaning of the answer, so the steps are typed rather
        than returned as bare strings for the caller to guess at."""
        graph.met_at("marcus", "the launch")
        graph.met_at("ada", "the launch")
        p = graph.path("marcus", "ada")
        assert [s["kind"] for s in p] == ["person", "event", "person"]
        assert p[1]["id"] == "the launch"

    def test_the_shortest_chain_wins(self, graph):
        """A long way round exists and must not be the answer. Breadth-first, so
        the goal is first reached by a shortest route — a depth-first walk would
        return some path and call it the shortest."""
        graph.relate("a", "b")
        graph.relate("b", "c")
        graph.relate("c", "d")
        graph.relate("a", "d")                    # the short way
        p = graph.path("a", "d")
        assert [s["id"] for s in p] == ["a", "d"]

    def test_unconnected_people_have_no_path(self, graph):
        graph.relate("a", "b")
        graph.relate("c", "d")
        assert graph.path("a", "d") == []

    def test_an_over_long_chain_is_dropped_not_truncated(self, graph):
        """Half a chain is not a shorter explanation, it is a wrong one — it would
        claim two people are connected by a route that does not reach."""
        names = [f"p{i}" for i in range(10)]
        for a, b in zip(names, names[1:]):
            graph.relate(a, b)
        assert graph.path(names[0], names[-1], max_hops=3) == []
        assert graph.path(names[0], names[1], max_hops=3)

    def test_a_person_has_no_path_to_themselves(self, graph):
        graph.relate("a", "b")
        assert graph.path("a", "a") == []

    def test_unknown_names_do_not_raise(self, graph):
        graph.relate("a", "b")
        assert graph.path("a", "ghost") == []
        assert graph.path("ghost", "a") == []
        assert graph.path("", "") == []


class TestCommunities:

    def test_two_separate_circles_are_two_groups(self, graph):
        graph.relate("a", "b")
        graph.relate("b", "c")
        graph.relate("x", "y")
        graph.relate("y", "z")
        groups = [set(g) for g in graph.communities()]
        assert {"a", "b", "c"} in groups
        assert {"x", "y", "z"} in groups

    def test_rooms_are_never_members_of_a_circle(self, graph):
        """A conference is not a member of a friendship group — it is the thing
        that connected one."""
        graph.met_at("a", "the launch")
        graph.met_at("b", "the launch")
        flat = [name for g in graph.communities() for name in g]
        assert "the launch" not in flat
        assert set(flat) == {"a", "b"}

    def test_the_engine_is_named_so_the_answer_is_not_overstated(self, graph):
        """The one query where the fallback is genuinely weaker, and the whole
        reason `communities_engine()` exists. Two cliques joined by a single
        acquaintance are ONE connected component and TWO communities — a surface
        that showed both as "circles" would be claiming more than it computed."""
        assert graph.communities_engine() == (
            "modularity" if graph.available else "components")

    def test_bigger_groups_come_first(self, graph):
        graph.relate("a", "b")
        graph.relate("b", "c")
        graph.relate("x", "y")
        sizes = [len(g) for g in graph.communities()]
        assert sizes == sorted(sizes, reverse=True)

    def test_an_empty_graph_has_no_circles(self, graph):
        assert graph.communities() == []


# --- the Brain builds one from real data -----------------------------------

class TestTheBrainBuildsIt:

    def test_a_meeting_becomes_a_shared_event_and_a_relationship(self, brain):
        _meet(brain, "the lease signing", "Marcus", "Priya")
        st = brain.social_graph_state()
        assert set(st["people"]) == {"Marcus", "Priya"}
        assert st["events"] == ["the lease signing"]
        assert st["meetings_seen"] == 1

    def test_co_attendance_is_a_relationship_connections_can_see(self, brain):
        """Recorded explicitly as well as through the event node, because
        `connections()` walks only person→person edges."""
        _meet(brain, "the lease signing", "Marcus", "Priya")
        g, _ = brain._social_graph()
        assert g.connections("Marcus") == ["Priya"]

    def test_two_people_who_shared_a_meeting_have_it_in_common(self, brain):
        _meet(brain, "the lease signing", "Marcus", "Priya")
        out = brain.social_mutual("Marcus", "Priya")
        assert out["ok"] is True
        assert out["events"] == ["the lease signing"]

    def test_a_bridge_between_two_meetings_gives_a_path(self, brain):
        _meet(brain, "the lease signing", "Marcus", "Priya")
        _meet(brain, "the launch", "Priya", "Ada")
        out = brain.social_mutual("Marcus", "Ada")
        assert out["ok"] is True
        ids = [s["id"] for s in out["path"]]
        assert ids[0] == "Marcus" and ids[-1] == "Ada"
        assert "Priya" in ids

    def test_a_solo_meeting_creates_no_edges(self, brain):
        """One person in a room is not evidence they met anybody."""
        _meet(brain, "thinking alone", "Marcus")
        st = brain.social_graph_state()
        assert st["meetings_seen"] == 0
        assert st["people"] == []

    def test_untitled_meetings_do_not_merge_into_one_room(self, brain):
        """Two untitled meetings are two rooms, and this found a real collision.

        Keying the event on the record id looked safe and is not: `MeetingLog.start`
        derives `id` from `int(time.time() * 1000)`, so two meetings begun in the
        same millisecond share one — which happens on any rapid sequence. The graph
        then wired two sets of people into a room they were never in, inventing
        mutual connections out of a clock collision. Written back-to-back here on
        purpose, because that is the case that failed.
        """
        _meet(brain, "", "Marcus", "Priya")
        _meet(brain, "", "Ada", "Tomas")
        st = brain.social_graph_state()
        assert len(st["events"]) == 2, st["events"]
        assert all(e.strip() for e in st["events"])
        assert brain.social_mutual("Marcus", "Ada")["events"] == []
        assert brain.social_mutual("Marcus", "Ada")["path"] == []

    def test_a_shared_TITLE_is_deliberately_a_shared_event(self, brain):
        """The other side of the decision above. Two records called "standup" are
        one recurring thing, and "you were both at standup" is true and useful — so
        a repeated title MUST join people, unlike a repeated blank."""
        _meet(brain, "standup", "Marcus", "Priya")
        _meet(brain, "standup", "Ada", "Tomas")
        st = brain.social_graph_state()
        assert st["events"] == ["standup"]
        assert brain.social_mutual("Marcus", "Ada")["events"] == ["standup"]

    def test_the_graph_is_not_built_from_the_address_book(self, brain):
        """The decision that keeps the whole answer meaningful. Contacts assert
        acquaintance with the WEARER, never with each other — building from them
        would make every circle an artefact of having synced Contacts."""
        brain.add_person("Marcus", note="landlord")
        brain.add_person("Ada", note="a colleague")
        st = brain.social_graph_state()
        assert st["people"] == [], "the address book leaked into the graph"
        out = brain.social_mutual("Marcus", "Ada")
        assert out["ok"] is False
        assert out["unknown"] == ["Marcus", "Ada"]

    def test_a_named_but_unmet_person_is_said_plainly(self, brain):
        """Not returned as an empty result, which reads as "nothing in common"."""
        _meet(brain, "the launch", "Marcus", "Priya")
        out = brain.social_mutual("Marcus", "Ghost")
        assert out["ok"] is False
        assert out["unknown"] == ["Ghost"]
        assert "meeting" in out["reason"]

    def test_two_names_are_required(self, brain):
        for a, b in (("", "Ada"), ("Marcus", ""), ("", "")):
            assert brain.social_mutual(a, b)["ok"] is False

    def test_the_meeting_window_is_bounded_and_reported(self, brain):
        """A graph query is interactive and history is unbounded, so it reads a
        recent window — and says so, rather than implying it saw everything."""
        st = brain.social_graph_state()
        assert st["meetings_max"] == brain.MAX_GRAPH_MEETINGS
        assert brain.MAX_GRAPH_MEETINGS > 0
        g, seen = brain._social_graph(limit=1)
        assert seen <= 1

    def test_the_graph_is_rebuilt_not_cached(self, brain):
        """Meetings are appended by a live path (the ear, `meeting_command`). A
        cached graph would answer "who do we both know" with a picture from before
        the meeting that just happened."""
        _meet(brain, "the first", "Marcus", "Priya")
        assert brain.social_graph_state()["count"] == 2
        _meet(brain, "the second", "Ada", "Tomas")
        assert brain.social_graph_state()["count"] == 4

    def test_the_engine_is_reported_on_every_answer(self, brain):
        _meet(brain, "the launch", "Marcus", "Priya")
        assert brain.social_graph_state()["engine"] in ("networkx", "fallback")
        assert brain.social_mutual("Marcus", "Priya")["engine"] in (
            "networkx", "fallback")


# --- the capability, promoted only by proof --------------------------------

class TestTheCapabilityIsHonest:

    def test_it_stays_declared_dormant_so_the_default_is_truthful(self):
        from dreamlayer import capabilities as C
        assert "social_graph" in C._NOT_WIRED

    def test_an_empty_graph_does_not_promote_it(self, brain):
        """networkx over an empty graph answers every query with nothing — exactly
        what the fallback does — so the wheel alone must not read green."""
        assert brain.social_graph_wired() is False

    def test_a_real_graph_promotes_it_only_with_networkx(self, brain):
        pytest.importorskip("networkx")
        _meet(brain, "the launch", "Marcus", "Priya")
        assert brain.social_graph_wired() is True

    def test_without_networkx_it_is_never_promoted(self, brain, monkeypatch):
        from dreamlayer.social_lens import graph as G
        monkeypatch.setattr(G, "_HAS_NX", False)
        monkeypatch.setattr(G.RelationshipGraph, "available", False)
        _meet(brain, "the launch", "Marcus", "Priya")
        assert brain.social_graph_wired() is False

    def test_the_report_promotes_it_without_touching_the_environment(self, brain):
        """Computed into the report's own env copy, never `os.environ`: there is no
        start/stop event to hang a durable flag on, so a flag would go stale in
        both directions — left set after the last meeting is deleted, unset until
        something remembered to set it."""
        import os
        from dreamlayer.ai_brain.server.server import _capability_payload
        pytest.importorskip("networkx")
        _meet(brain, "the launch", "Marcus", "Priya")
        before = os.environ.get("DL_WIRED_SOCIAL_GRAPH")
        payload = _capability_payload(brain)
        assert os.environ.get("DL_WIRED_SOCIAL_GRAPH") == before
        row = next(i for i in payload["items"] if i["key"] == "social_graph")
        assert row["state"] == "active", row

    def test_the_report_does_not_promote_it_on_an_empty_graph(self, brain):
        from dreamlayer.ai_brain.server.server import _capability_payload
        row = next(i for i in _capability_payload(brain)["items"]
                   if i["key"] == "social_graph")
        assert row["state"] != "active", row

    def test_a_broken_graph_never_breaks_the_capability_report(self, brain):
        """The report is what the panel renders; a graph failure must degrade it,
        not 500 it."""
        from dreamlayer.ai_brain.server.server import _capability_payload

        def _boom():
            raise RuntimeError("meetings.json is a directory")
        brain.social_graph_wired = _boom
        assert _capability_payload(brain)["items"]


# --- the surface -----------------------------------------------------------

class TestItIsReachable:

    def test_the_route_is_registered(self):
        from dreamlayer.ai_brain.server import server as S
        src = pathlib.Path(S.__file__).read_text(encoding="utf-8")
        assert '"/dreamlayer/social/graph": _get_social_graph' in src

    def test_the_panel_asks_for_a_pair_and_for_the_circles(self):
        src = PANEL.read_text(encoding="utf-8")
        assert "async function askMutual" in src
        assert "async function loadCircles" in src
        assert "/dreamlayer/social/graph" in src

    def test_the_panel_loads_the_circles_when_people_load(self):
        """A function nothing calls is the gap one layer up — the same shape this
        whole capability was in."""
        src = PANEL.read_text(encoding="utf-8")
        i = src.index("async function loadPeople")
        assert "loadCircles()" in src[i:src.index("async function addPerson")]

    def test_the_panel_names_the_weaker_algorithm_rather_than_hiding_it(self):
        """"Circles" claims more than connected components can support."""
        src = PANEL.read_text(encoding="utf-8")
        i = src.index("async function loadCircles")
        body = src[i:i + 1400]
        assert 'communities_engine==="modularity"' in body
        assert "reachable" in body

    def test_the_panel_draws_a_room_differently_from_a_person(self):
        src = PANEL.read_text(encoding="utf-8")
        i = src.index("async function askMutual")
        body = src[i:i + 1800]
        assert 's.kind==="event"' in body
