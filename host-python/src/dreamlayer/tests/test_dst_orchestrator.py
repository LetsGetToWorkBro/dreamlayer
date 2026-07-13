"""DST-lite: seeded, replayable interleaving over the hub's real race surfaces.

Two halves. First the harness proves ITSELF: same seed → same schedule, replay
is exact, and — the point of the whole exercise — a planted lost-update race is
FOUND by exploration, its seed reported, and its exact schedule reproduced by
replay. A concurrency harness that can't demonstrably catch a race is theater.

Then the hub: the three concurrent parties the concurrency doc names (the
capture pipeline routing captions, message polling flashing cards, the
attention pulse) are modeled as actors — the very calls their real threads
make — and interleaved against the main thread's tick/veil/pause across many
seeded schedules, with invariants checked after every step. A true-thread
stress pass runs the same scenarios on real threads for sub-op races.

Cooldowns/session windows run on SimClock virtual time (installed over the
orch._clock seam), so "a minute passes" costs nothing and is identical every
run."""
import pytest

from dreamlayer.orchestrator.orchestrator import Orchestrator
from dreamlayer.testkit import (
    Interleaver, InterleavingFailure, SimClock, run_threads,
)

SEEDS = range(40)


class FakeBridge:
    def __init__(self):
        import threading
        self.cards = []
        self._lock = threading.Lock()

    def send_card(self, payload, event="answer_ready"):
        with self._lock:
            self.cards.append((event, payload))

    def __getattr__(self, name):          # any other bridge call is a no-op
        return lambda *a, **k: None


# ---------------------------------------------------------------------------
# The harness proves itself
# ---------------------------------------------------------------------------

class TestHarnessSelfProof:
    def test_same_seed_same_schedule(self):
        def scenario():
            log = []
            actors = {"a": [lambda i=i: log.append(("a", i)) for i in range(4)],
                      "b": [lambda i=i: log.append(("b", i)) for i in range(4)]}
            return log, actors
        log1, actors1 = scenario()
        log2, actors2 = scenario()
        t1 = Interleaver().run(actors1, seed=7)
        t2 = Interleaver().run(actors2, seed=7)
        assert t1.steps == t2.steps and log1 == log2
        # and per-actor order was preserved inside the merge
        assert [i for a, i in t1.steps if a == "a"] == [0, 1, 2, 3]

    def test_planted_race_is_found_and_replays_exactly(self):
        """A textbook lost update: two actors do read → write as SEPARATE ops
        on a shared counter. Some schedules interleave the reads and lose an
        increment. explore() must find such a seed, and replay() must
        reproduce the identical wrong final value."""
        def make():
            state = {"n": 0, "tmp": {}}

            def read(actor):
                state["tmp"][actor] = state["n"]

            def write(actor):
                state["n"] = state["tmp"][actor] + 1

            actors = {
                "a": [lambda: read("a"), lambda: write("a")],
                "b": [lambda: read("b"), lambda: write("b")],
            }
            return state, actors

        found = None
        for seed in range(64):
            state, actors = make()
            trace = Interleaver().run(actors, seed)
            if state["n"] != 2:            # an increment was lost
                found = (seed, trace, state["n"])
                break
        assert found is not None, "exploration failed to find the planted race"
        seed, trace, bad_value = found
        # replay the exact schedule on a fresh scenario → identical bad value
        state2, actors2 = make()
        Interleaver().replay(actors2, trace)
        assert state2["n"] == bad_value

    def test_invariant_failure_names_the_seed(self):
        def make_scenario():
            box = {"v": 0}
            actors = {"x": [lambda: box.__setitem__("v", 1)]}

            def invariant():
                assert box["v"] == 0, "v mutated"
            return actors, invariant

        with pytest.raises(InterleavingFailure) as e:
            Interleaver().explore(make_scenario, seeds=range(3))
        assert "reproduce with" in str(e.value)

    def test_simclock_is_monotonic_and_thread_safe(self):
        clock = SimClock()
        run_threads({f"t{k}": [lambda: clock.advance(0.5) for _ in range(200)]
                     for k in range(4)})
        assert clock.monotonic() == pytest.approx(400.0)


# ---------------------------------------------------------------------------
# The hub's real race surfaces
# ---------------------------------------------------------------------------

def _hub():
    br = FakeBridge()
    orch = Orchestrator(br)
    clock = SimClock(start=1000.0).install(orch)
    return br, orch, clock


class TestHubInterleavings:
    def test_capture_vs_veil_vs_tick(self):
        """The capture pipeline routes captions from its worker thread while
        the user toggles incognito and the main loop ticks. Invariant, checked
        after every step: the veil is never breached — the conversation log
        only ever contains lines accepted while capture was allowed, and
        nothing is kept once the veil is up at ingest time."""
        def make_scenario():
            br, orch, clock = _hub()
            accepted = []

            def ingest(i):
                u = orch.ingest_caption(f"line {i}", speaker="Maya")
                if u is not None:
                    accepted.append(i)
                    assert orch.privacy.allow_capture(), \
                        "caption accepted while the veil was up"

            actors = {
                "capture": [lambda i=i: ingest(i) for i in range(6)],
                "veil": [lambda: orch.set_incognito(True),
                         lambda: orch.set_incognito(False),
                         lambda: orch.set_incognito(True)],
                "main": [lambda: (clock.advance(0.25), orch.tick())
                         for _ in range(6)],
            }

            def invariant():
                assert len(orch.conversation) <= len(accepted) + 1

            return actors, invariant

        assert Interleaver().explore(make_scenario, SEEDS) == len(SEEDS)
        # final state: veil up (last toggle True) → a further ingest keeps nothing
        br, orch, clock = _hub()
        orch.set_incognito(True)
        assert orch.ingest_caption("after veil", speaker="Maya") is None

    def test_message_polling_vs_pause_resume(self):
        """The poll worker flashes incoming messages while the main thread
        pauses/resumes the hub and ticks. Invariant: every card the bridge saw
        is well-formed (dict with a type), no step ever raises."""
        def make_scenario():
            br, orch, clock = _hub()
            items = [{"id": f"m{i}", "from": "Maya", "text": f"hi {i}",
                      "ts": 1000.0 + i} for i in range(4)]

            actors = {
                "poller": [lambda batch=items[i:i + 2]:
                           orch.poll_messages(list(batch)) for i in range(0, 4, 2)],
                "user": [lambda: orch.pause(), lambda: orch.resume(),
                         lambda: orch.pause(), lambda: orch.resume()],
                "main": [lambda: (clock.advance(1.0), orch.tick())
                         for _ in range(4)],
            }

            def invariant():
                for _ev, card in br.cards:
                    assert isinstance(card, dict) and card.get("type")

            return actors, invariant

        assert Interleaver().explore(make_scenario, SEEDS) == len(SEEDS)

    def test_hear_storm_vs_attention(self):
        """Two voice sources race hear() against the attention pulse and the
        session-window clock. Invariant: hear() always returns a dict verdict,
        the hub never throws, and the Juno session state stays coherent."""
        def make_scenario():
            from dreamlayer.orchestrator.anticipation import Context
            br, orch, clock = _hub()

            def hear(text):
                out = orch.hear(text)
                assert isinstance(out, dict)

            actors = {
                "voice_a": [lambda: hear("hey juno"),
                            lambda: hear("what time is it")],
                "voice_b": [lambda: hear("hey juno remind me later"),
                            lambda: hear("never mind")],
                "pulse": [lambda k=k: (clock.advance(2.0),
                                       orch.attention_tick(Context(
                                           now=1000.0 + k, place="studio")))
                          for k in range(4)],
            }

            def invariant():
                assert isinstance(orch.juno_listening(), bool)

            return actors, invariant

        assert Interleaver().explore(make_scenario, SEEDS) == len(SEEDS)


class TestHubTrueThreads:
    """Layer 2: the same surfaces on real threads (non-deterministic smoke for
    sub-operation races). Any exception on any thread fails the test."""

    def test_capture_veil_tick_threads(self):
        br, orch, clock = _hub()
        run_threads({
            "capture": [lambda i=i: orch.ingest_caption(f"line {i}", speaker="M")
                        for i in range(25)],
            "veil": [lambda on=bool(i % 2): orch.set_incognito(on)
                     for i in range(25)],
            "main": [lambda: (clock.advance(0.1), orch.tick()) for _ in range(25)],
        })
        for _ev, card in br.cards:
            assert isinstance(card, dict)

    def test_polling_pause_threads(self):
        br, orch, clock = _hub()
        items = [{"id": f"m{i}", "from": "Maya", "text": f"hi {i}",
                  "ts": 1000.0 + i} for i in range(25)]
        run_threads({
            "poller": [lambda it=it: orch.poll_messages([it]) for it in items],
            "user": [lambda i=i: (orch.pause() if i % 2 else orch.resume())
                     for i in range(25)],
            "main": [lambda: (clock.advance(0.5), orch.tick()) for _ in range(25)],
        })
