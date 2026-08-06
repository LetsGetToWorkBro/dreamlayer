"""The two graph algorithms behind the autonomous-emit budget, tested directly.

WHY THIS FILE EXISTS
--------------------
#530 replaced the flood check's exponential cycle enumeration with two real
algorithms — an iterative-DFS zero-time cycle finder and a maximum-ratio-cycle
search (binary search over Bellman-Ford) — about 150 lines of new numeric code
in a file the mutation gate holds to a survivor ceiling.

Nothing tested them directly. `test_budgets_boundaries.py` and
`test_rc2_budgets.py` reach them only through `verify()`, which asks one
question ("does this figment trip the flood code?") and cannot distinguish a
correct maximum-ratio search from one that happens to clear the threshold on
the fixtures at hand.

The weekly mutation job said so and nobody was reading it: budgets.py went from
213 survivors to 291 in the week #530 landed, and the job — scheduled, never a
merge gate — has been red ever since. Of those, 25 were in `_zero_time_cycle`,
39 in `_max_ratio_cycle`, and `_cycle_analysis` grew from 3 to 46. The old 213
is documented residue (diagnostic message strings); this was not residue.

These are pure functions over plain lists and dicts, so they can simply be
called with graphs whose answers are known by hand. Every expected value below
was read off the implementation before being asserted, not guessed.

WHAT IS DELIBERATELY EXACT
--------------------------
`_max_ratio_cycle` reports the witness cycle's own emits/seconds division, not
the binary search's bound — the search converges but never lands, and an
earlier version returned 0.9999999999989981 for a cycle that plainly emits once
per second. So the rates here are asserted with `==`, not `pytest.approx`: the
approximate form passes on the bound too, which is the bug that block exists to
prevent.
"""
from __future__ import annotations

import sys

import pytest

from dreamlayer.reality_compiler.v2.budgets import (
    _max_ratio_cycle,
    _zero_time_cycle,
)


class TestZeroTimeCycle:
    """A cycle whose every edge takes no time is a livelock: the figment can go
    round it forever without the clock advancing."""

    def test_no_nodes_and_no_edges_is_not_a_cycle(self):
        assert _zero_time_cycle([], {}) is None
        assert _zero_time_cycle(["a", "b"], {}) is None

    def test_a_two_node_ring_is_found(self):
        assert _zero_time_cycle(["a", "b"], {"a": ["b"], "b": ["a"]}) == ["a", "b"]

    def test_a_self_loop_is_a_cycle(self):
        """The shortest livelock there is, and the one an off-by-one in the
        back-edge test loses: `path[path.index(nxt):]` must include the node
        itself."""
        assert _zero_time_cycle(["a"], {"a": ["a"]}) == ["a"]

    def test_a_chain_is_not_a_cycle(self):
        assert _zero_time_cycle(["a", "b", "c"],
                                {"a": ["b"], "b": ["c"]}) is None

    def test_a_diamond_is_not_a_cycle(self):
        """The case that separates "on the current path" from "already
        finished", which is the whole reason for a three-colour DFS rather than
        a visited set.

        a→b, a→c, b→d, c→d reaches `d` twice and contains no cycle. Collapse
        GREY and BLACK into one "seen" state — the obvious simplification, and
        what several of the surviving mutants do — and this graph is reported
        as a livelock. A false livelock refuses a valid figment.
        """
        g = {"a": ["b", "c"], "b": ["d"], "c": ["d"]}
        assert _zero_time_cycle(["a", "b", "c", "d"], g) is None

    def test_a_cycle_not_reachable_from_the_first_node_is_still_found(self):
        """The outer loop over roots is load-bearing: `a` is isolated and the
        ring is b↔c. Search only from the first node and the livelock ships."""
        got = _zero_time_cycle(["a", "b", "c"], {"b": ["c"], "c": ["b"]})
        assert got == ["b", "c"]

    def test_the_returned_path_is_a_real_ring(self):
        """Not just "some nodes" — every consecutive pair, and the wrap-around,
        must be an actual edge. A mutant that slices the path at the wrong
        index still returns a plausible-looking list."""
        g = {"a": ["b"], "b": ["c"], "c": ["d"], "d": ["b"]}
        got = _zero_time_cycle(["a", "b", "c", "d"], g)
        assert got is not None
        ring = list(got) + [got[0]]
        for u, w in zip(ring, ring[1:]):
            assert w in g.get(u, ()), f"{u}->{w} is not an edge; {got} is not a ring"

    def test_a_deep_graph_does_not_blow_the_python_stack(self):
        """The docstring's claim, asserted. 20,000 chained nodes against a
        recursion limit of ~1000: a recursive DFS raises RecursionError, which
        `verify()` does not catch, so an import-shaped payload would take the
        Brain down rather than be refused.
        """
        n = 20_000
        assert n > sys.getrecursionlimit() * 4
        nodes = [str(i) for i in range(n)]
        edges = {str(i): [str(i + 1)] for i in range(n - 1)}
        assert _zero_time_cycle(nodes, edges) is None
        edges[str(n - 1)] = ["0"]                       # close the ring
        got = _zero_time_cycle(nodes, edges)
        assert got is not None and len(got) == n


class TestMaxRatioCycle:
    """The worst sustained autonomous emit rate over every cycle in the graph.

    `arcs` are (source, emits, seconds, target).
    """

    def test_an_empty_graph_emits_nothing(self):
        assert _max_ratio_cycle([], [], 0.0, 1.0) == (0.0, None)

    def test_an_acyclic_graph_emits_nothing_sustained(self):
        """One arc and no way back. A burst is not a rate — the budget is about
        what a figment can keep doing."""
        assert _max_ratio_cycle(["a", "b"], [("a", 1.0, 1.0, "b")],
                                0.0, 10.0) == (0.0, None)

    def test_a_cycle_that_emits_nothing_is_not_a_flood(self):
        """A figment may loop forever as long as it is quiet. The search starts
        at L=0, so this is the case that must NOT come back positive."""
        arcs = [("a", 0.0, 1.0, "b"), ("b", 0.0, 1.0, "a")]
        assert _max_ratio_cycle(["a", "b"], arcs, 0.0, 10.0) == (0.0, None)

    @pytest.mark.parametrize("emits,secs,rate", [
        (1.0, 1.0, 1.0),      # once a second
        (3.0, 1.0, 3.0),      # three a second
        (1.0, 4.0, 0.25),     # once every four seconds
        (7.0, 2.0, 3.5),
    ])
    def test_the_rate_is_the_cycle_s_own_exact_division(self, emits, secs, rate):
        """`==`, not approx, and that is the point.

        The binary search converges toward the maximum without reaching it, so
        the bound alone gave 0.9999999999989981 for the first row here. The
        exact-ratio block re-derives emits/seconds from the witness cycle. An
        approximate assertion passes on the bound too and would not have caught
        it — and at the budget boundary that rounding error reads as under
        budget when the figment is exactly at it.
        """
        arcs = [("a", emits, secs, "b"), ("b", 0.0, 0.0, "a")]
        got, cycle = _max_ratio_cycle(["a", "b"], arcs, 0.0, 10.0)
        assert got == rate
        assert cycle is not None and set(cycle) == {"a", "b"}

    def test_it_reports_the_worst_cycle_not_the_first(self):
        """Two disjoint rings, 1/s and 5/s. Returning either the first found or
        the last would pass a test with one ring; the budget has to see the
        worst thing the figment can sustain."""
        nodes = ["a", "b", "c", "d"]
        arcs = [("a", 1.0, 1.0, "b"), ("b", 0.0, 0.0, "a"),
                ("c", 5.0, 1.0, "d"), ("d", 0.0, 0.0, "c")]
        rate, cycle = _max_ratio_cycle(nodes, arcs, 0.0, 10.0)
        assert rate == 5.0
        assert cycle is not None and set(cycle) == {"c", "d"}

    def test_the_worst_cycle_is_found_whichever_order_the_arcs_arrive(self):
        """Same graph, arcs reversed. A search that depends on arc order is one
        that a differently-ordered figment slips past."""
        nodes = ["a", "b", "c", "d"]
        arcs = [("d", 0.0, 0.0, "c"), ("c", 5.0, 1.0, "d"),
                ("b", 0.0, 0.0, "a"), ("a", 1.0, 1.0, "b")]
        rate, cycle = _max_ratio_cycle(nodes, arcs, 0.0, 10.0)
        assert rate == 5.0
        assert cycle is not None and set(cycle) == {"c", "d"}

    def test_an_emitting_zero_time_cycle_saturates_the_search(self):
        """Emitting round a ring that takes no time is an infinite rate. There
        is no finite division to report, so the search runs to its upper bound
        and `_zero_time_cycle` is what actually refuses the figment — this pins
        that the two checks agree about whose job it is."""
        arcs = [("a", 1.0, 0.0, "b"), ("b", 1.0, 0.0, "a")]
        rate, cycle = _max_ratio_cycle(["a", "b"], arcs, 0.0, 10.0)
        assert rate >= 9.9, f"expected the search to saturate near hi, got {rate}"
        assert cycle is not None
        assert _zero_time_cycle(["a", "b"], {"a": ["b"], "b": ["a"]}) is not None

    def test_a_slower_ring_does_not_hide_behind_a_faster_one(self):
        """A shared node between rings. The witness must be the fast ring even
        though the slow one is reachable from it."""
        nodes = ["a", "b", "c"]
        arcs = [("a", 0.0, 1.0, "b"), ("b", 0.0, 1.0, "a"),   # quiet ring
                ("b", 4.0, 1.0, "c"), ("c", 0.0, 0.0, "b")]   # loud ring
        rate, cycle = _max_ratio_cycle(nodes, arcs, 0.0, 10.0)
        assert rate == 4.0
        assert cycle is not None and set(cycle) == {"b", "c"}


class TestTheCasesTheFirstDraftMissed:
    """Added after mutation-testing the class above.

    Each test here kills mutants that survived it, and each survivor named a
    real gap rather than a quibble: the first draft used only two-node rings
    with one arc per pair, so the cycle-reconstruction walk and the
    parallel-arc scoring never ran at all.
    """

    def test_a_cycle_is_found_after_an_already_finished_node(self):
        """`continue` in the root loop, not `break`.

        `a` is walked first and colours `b` BLACK. `b` then comes up as a root,
        is not WHITE, and must be SKIPPED — not treated as the end of the
        search. Turn that `continue` into a `break` and the c↔d livelock two
        roots later is never looked for. The first draft's version of this test
        had no already-coloured node before the ring, so the branch never ran.
        """
        g = {"a": ["b"], "c": ["d"], "d": ["c"]}
        got = _zero_time_cycle(["a", "b", "c", "d"], g)
        assert got is not None and set(got) == {"c", "d"}

    def test_a_cycle_is_found_after_backtracking_out_of_a_dead_end(self):
        """`continue` on exhausting a node's edges, not `break`.

        `a`'s first edge leads to the dead end `b`. Popping it must resume `a`'s
        remaining edges; abandoning the whole DFS instead loses the a→c→a ring
        that is one branch to the right. Every graph in the first draft found
        its cycle on the first branch tried.
        """
        g = {"a": ["b", "c"], "c": ["a"]}
        got = _zero_time_cycle(["a", "b", "c"], g)
        assert got is not None and set(got) == {"a", "c"}

    def test_the_loudest_arc_between_two_scenes_is_the_one_that_counts(self):
        """Parallel arcs — two transitions from the same scene to the same
        scene, emitting different amounts.

        The witness cycle is a list of NODES, so the rate it reports has to
        pick an arc for each hop, and it picks the highest-scoring one. With a
        single arc per pair — every case in the first draft — that choice is
        forced and the whole scoring block is dead code that no test observes.

        A figment can plainly have two routes from one scene to another. If the
        quiet one is scored, the budget under-reports what the figment can
        sustain, which is the direction that ships a flood.
        """
        nodes = ["a", "b"]
        arcs = [("a", 1.0, 1.0, "b"),      # the quiet route
                ("a", 6.0, 1.0, "b"),      # the loud one
                ("b", 0.0, 0.0, "a")]
        rate, cycle = _max_ratio_cycle(nodes, arcs, 0.0, 10.0)
        assert rate == 6.0, "the quieter of two parallel arcs was scored"
        assert cycle is not None and set(cycle) == {"a", "b"}

    def test_parallel_arcs_do_not_change_a_verdict_they_should_not(self):
        """The other direction, so the test above cannot be satisfied by
        always taking the last arc seen: the loud arc first, quiet second."""
        nodes = ["a", "b"]
        arcs = [("a", 6.0, 1.0, "b"),
                ("a", 1.0, 1.0, "b"),
                ("b", 0.0, 0.0, "a")]
        rate, _ = _max_ratio_cycle(nodes, arcs, 0.0, 10.0)
        assert rate == 6.0

    def test_a_long_ring_reached_down_a_tail_is_reconstructed_whole(self):
        """The walk that turns Bellman-Ford's predecessor map back into a
        cycle, exercised for the first time.

        Two-node rings make that walk trivial — it terminates immediately
        whatever the loop bounds are. Here a four-node ring sits at the end of
        a three-node tail, so the walk has to step INTO the ring before
        collecting it and stop once round. An off-by-one in either bound
        returns a truncated ring or a path that is not a cycle at all.
        """
        nodes = ["t0", "t1", "t2", "r0", "r1", "r2", "r3"]
        arcs = [("t0", 0.0, 1.0, "t1"), ("t1", 0.0, 1.0, "t2"),
                ("t2", 0.0, 1.0, "r0"),
                ("r0", 1.0, 1.0, "r1"), ("r1", 1.0, 1.0, "r2"),
                ("r2", 1.0, 1.0, "r3"), ("r3", 1.0, 1.0, "r0")]
        rate, cycle = _max_ratio_cycle(nodes, arcs, 0.0, 10.0)
        assert rate == 1.0                      # 4 emits over 4 seconds
        assert cycle is not None
        assert set(cycle) == {"r0", "r1", "r2", "r3"}, (
            f"the reconstructed cycle is {cycle} — it must be the ring itself, "
            f"with no tail node and nothing missing")

    def test_the_reconstructed_ring_is_a_real_walk(self):
        """Same graph, asserting the SHAPE rather than the membership: every
        consecutive pair must be an arc. A reconstruction that returns the
        right four nodes in the wrong order scores the wrong edges."""
        nodes = ["t0", "r0", "r1", "r2", "r3"]
        arcs = [("t0", 0.0, 1.0, "r0"),
                ("r0", 2.0, 1.0, "r1"), ("r1", 0.0, 1.0, "r2"),
                ("r2", 2.0, 1.0, "r3"), ("r3", 0.0, 1.0, "r0")]
        rate, cycle = _max_ratio_cycle(nodes, arcs, 0.0, 10.0)
        assert rate == 1.0                      # 4 emits over 4 seconds
        assert cycle is not None
        edges = {(u, t) for u, _e, _s, t in arcs}
        ring = list(cycle) + [cycle[0]]
        for u, w in zip(ring, ring[1:]):
            assert (u, w) in edges, f"{u}->{w} is not an arc; {cycle} is no ring"


# --- _cycle_analysis: the caller that builds the graph and reads the verdict --
from dreamlayer.reality_compiler.v2 import (            # noqa: E402
    Figment, Scene, TextLine, Transition,
)
from dreamlayer.reality_compiler.v2.budgets import _cycle_analysis   # noqa: E402
from dreamlayer.reality_compiler.v2.figment import EMIT_REFILL_PER_S  # noqa: E402


def _ring(dur: float, *, emit: bool = True, n: int = 2) -> Figment:
    """`n` scenes in a timeout ring, each `dur` seconds, each optionally
    emitting once on the hop."""
    fig = Figment(name="t", initial="s0")
    for i in range(n):
        fig.add_scene(Scene(
            id=f"s{i}", duration_sec=dur, lines=[TextLine("hi", row=1)],
            on_timeout=[Transition(target=f"s{(i + 1) % n}",
                                   emit="e" if emit else None)]))
    return fig


class TestCycleAnalysisVerdicts:
    """`_cycle_analysis` builds the graph, calls the two algorithms above and
    turns their answers into violations.

    It was reached only through `verify()`, which reports a set of codes — so
    the arc filter, the zero-duration predicate, the empty-graph return and the
    two violation CODES were all unobserved. These call it directly with a
    violations list, which is what makes the code strings assertable.
    """

    def test_a_figment_with_no_timed_edges_has_no_rate(self):
        """The early return. Mutated to 1.0 it reports a figment that cannot
        emit at all as sitting exactly on the BLE budget."""
        fig = Figment(name="t", initial="a")
        fig.add_scene(Scene(id="a", lines=[TextLine("hi", row=1)]))
        v: list = []
        assert _cycle_analysis(fig, v) == 0.0
        assert v == []

    def test_a_quiet_ring_is_not_a_flood(self):
        v: list = []
        assert _cycle_analysis(_ring(1.0, emit=False), v) == 0.0
        assert v == []

    def test_a_zero_duration_ring_is_a_livelock_by_that_name(self):
        """Both halves. The code string is asserted exactly because `codes()`
        is how every other test and every caller identifies a violation — mutate
        "livelock" to "LIVELOCK" and the report still has one entry, so a
        coarse "did anything fire?" check cannot tell.

        This also pins `dur <= 0.0`: as `dur < 0.0` no zero-duration edge is
        ever collected, the livelock check runs on an empty graph, and a figment
        that spins forever without advancing the clock ships.
        """
        v: list = []
        _cycle_analysis(_ring(0.0), v)
        assert "livelock" in {x.code for x in v}, (
            f"expected a livelock, got {[x.code for x in v]}")

    def test_a_ring_over_budget_is_a_flood_by_that_name(self):
        """0.4 s a hop is 2.5 emits/s against a budget of 1/s."""
        v: list = []
        rate = _cycle_analysis(_ring(0.4), v)
        assert rate == 2.5
        assert "ble_flood" in {x.code for x in v}, (
            f"expected a ble_flood, got {[x.code for x in v]}")

    def test_a_ring_exactly_at_the_budget_is_allowed(self):
        """The boundary the comparator owns: `> EMIT_REFILL_PER_S`, not `>=`.
        One emit per second against a 1/s refill is sustainable forever."""
        v: list = []
        rate = _cycle_analysis(_ring(1.0), v)
        assert rate == EMIT_REFILL_PER_S == 1.0
        assert v == [], f"a figment exactly at budget was refused: {v}"

    def test_an_edge_to_a_scene_that_does_not_exist_is_not_an_arc(self):
        """`u in known AND tgt in known`, not OR.

        A dangling transition names a scene the figment does not define. As
        `or`, the arc is admitted and the rate is computed over a graph
        containing a node that is not in `nodes` — the search then reasons
        about a scene that cannot run. The ring here is exactly at budget, so
        admitting the ghost arc is what changes the verdict.
        """
        fig = Figment(name="t", initial="s0")
        fig.add_scene(Scene(
            id="s0", duration_sec=1.0, lines=[TextLine("hi", row=1)],
            on_timeout=[Transition(target="s1", emit="e"),
                        Transition(target="ghost", emit="e")]))
        fig.add_scene(Scene(
            id="s1", duration_sec=1.0, lines=[TextLine("hi", row=1)],
            on_timeout=[Transition(target="s0", emit="e")]))
        v: list = []
        assert _cycle_analysis(fig, v) == 1.0
        assert v == [], f"the dangling edge changed the verdict: {v}"
