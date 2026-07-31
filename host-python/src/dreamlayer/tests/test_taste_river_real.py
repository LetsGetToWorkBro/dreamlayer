"""RiverTasteRanker against the REAL river model (issue #453).

`orchestrator/taste_river.py` is the `online_learning` capability (`intelligence`
extra, `river`). Its only existing coverage —
test_integration_seams_pr2.py::test_taste_river_fallback_learns — runs on a box
without river, so it exercises the in-house running mean in `_prefs` and never
the river pipeline. This file is the other half: the same class with a live
`compose.Pipeline(StandardScaler, LogisticRegression)` behind it.

Follow-up in the real-path series (#396/#428/#432/#417/#528/#545), and the
cheapest of them: river is pure Python with NO model download, so there is no
`real_model` mark here — `importorskip("river")` alone is the gate. On a box with
the `intelligence` extra the file runs in the ordinary suite; without it, it
skips. (The default CI job installs `.[dev,verify,sync]`, so it skips there
today; adding river to that job is the maintainer's call, not a test's.)

Non-vacuity (the #396 lesson): every branch in this module is `real path or
silently fall through to the running mean`, so a real-path test that lets the
fallback answer proves nothing. The `real_path` fixture therefore

  * counts the live pipeline's `learn_one` / `predict_proba_one` calls, and
  * swaps `_prefs` — the fallback's ENTIRE state — for a ledger pre-loaded with
    the OPPOSITE preference (the chosen key at 0.0, the passed-over key at 1.0)
    that records every write.

So a silent degrade cannot pass: in `observe` the fallback's only effect is
writing `_prefs`, which the ledger records; in `score` the fallback returns
`_prefs.get(key, 0.5)`, which is now the inverted preference, so every ordering
assertion below flips.

Scenario choice: exactly two keys. The pipeline has a single feature,
`hash(key) % 997`, so its score is monotone in that bucket and the bucket order
is randomised per process (PYTHONHASHSEED) — with two keys the standardiser
makes the outcome deterministic, with three it is a coin flip. Two keys is what
this model can actually represent; see the issue for the wider limitation.
"""
from __future__ import annotations

import pytest

pytest.importorskip("river")

from river import compose, linear_model, preprocessing  # noqa: E402

from dreamlayer.orchestrator import taste_river  # noqa: E402
from dreamlayer.orchestrator.taste_river import RiverTasteRanker  # noqa: E402

CHOSEN, PASSED = "oat-latte", "black-coffee"
# Five rounds of "picked the oat latte, walked past the black coffee".
HISTORY = [(CHOSEN, True), (PASSED, False)] * 5
# Keys no observation ever mentions — the running mean has nothing to say about
# any of them, by construction (`_prefs.get(key, 0.5)`).
UNSEEN = [f"unseen-{i}" for i in range(8)]


class _PoisonedPrefs(dict[str, float]):
    """The running-mean ledger, pre-loaded with the OPPOSITE preference and
    recording every write. The poison is seeded through `dict.__init__`, so it is
    not itself counted as a fallback write."""

    def __init__(self, poison: dict[str, float]):
        super().__init__(poison)
        self.writes: list[tuple[str, float]] = []

    def __setitem__(self, key: str, value: float) -> None:
        self.writes.append((key, value))
        super().__setitem__(key, value)


class _RealPathSpy:
    """Counts the live pipeline's calls and poisons the fallback ledger, so the
    two paths are distinguishable in both directions."""

    def __init__(self, ranker: RiverTasteRanker):
        self.ranker = ranker
        self.learn_calls = 0
        self.predict_calls = 0
        self.prefs = _PoisonedPrefs({CHOSEN: 0.0, PASSED: 1.0})
        ranker._prefs = self.prefs
        model = ranker._model
        real_learn, real_predict = model.learn_one, model.predict_proba_one

        def spy_learn(x, y, **kw):
            self.learn_calls += 1
            return real_learn(x, y, **kw)

        def spy_predict(x, **kw):
            self.predict_calls += 1
            return real_predict(x, **kw)

        model.learn_one = spy_learn
        model.predict_proba_one = spy_predict

    @property
    def fallback_writes(self) -> list[tuple[str, float]]:
        return self.prefs.writes

    def teach(self) -> None:
        for key, chosen in HISTORY:
            self.ranker.observe(key, chosen)


@pytest.fixture
def real_path() -> _RealPathSpy:
    """A RiverTasteRanker with a genuinely built river pipeline behind it.
    river is installed (we are past the importorskip), so a ranker that still
    has no model is a broken install, not an absent capability — assert, never
    skip, or the whole file passes vacuously."""
    ranker = RiverTasteRanker()
    assert ranker.available is True
    assert ranker._model is not None, (
        "river is installed but RiverTasteRanker built no pipeline; __init__ "
        "swallowed the failure and every call would silently use the running "
        "mean"
    )
    return _RealPathSpy(ranker)


def _running_mean_ranker() -> RiverTasteRanker:
    """The same class with the pipeline removed — the shape every box without
    the `intelligence` extra runs, for differential comparison."""
    ranker = RiverTasteRanker()
    ranker._model = None
    for key, chosen in HISTORY:
        ranker.observe(key, chosen)
    return ranker


# --------------------------------------------------------------------------
# The pipeline is real
# --------------------------------------------------------------------------

def test_the_ranker_reports_the_online_learning_capability():
    """The single assertion the capability registry rests on: `online_learning`
    claims river is wired up. Everything below is only meaningful if it holds."""
    assert RiverTasteRanker().available is True


def test_the_model_is_a_live_river_pipeline(real_path):
    model = real_path.ranker._model
    assert isinstance(model, compose.Pipeline)
    stages = list(model.steps.values())
    assert isinstance(stages[0], preprocessing.StandardScaler)
    assert isinstance(stages[-1], linear_model.LogisticRegression)
    assert dict(stages[-1].weights) == {}, "a fresh ranker must be untrained"


# --------------------------------------------------------------------------
# The real path answers — and the running mean provably does not
# --------------------------------------------------------------------------

def test_observe_trains_the_pipeline_and_never_the_running_mean(real_path):
    """`observe`'s fallback branch has exactly one effect — writing `_prefs`.
    Zero writes across the whole history is therefore a complete proof that
    every observation went into river."""
    real_path.teach()
    assert real_path.learn_calls == len(HISTORY)
    assert real_path.fallback_writes == []
    weights = dict(real_path.ranker._model["LogisticRegression"].weights)
    assert weights and any(w != 0.0 for w in weights.values()), (
        "learn_one ran but the regression never moved: nothing was learned"
    )


def test_score_moves_toward_the_key_that_was_chosen(real_path):
    """The poisoned ledger holds the inverted preference, so a silent degrade
    here returns 0.0 for the chosen key and 1.0 for the passed-over one and
    fails on both bounds — it cannot rescue this assertion."""
    real_path.teach()
    chosen, passed = real_path.ranker.score(CHOSEN), real_path.ranker.score(PASSED)
    assert chosen > 0.5 > passed          # moved off the untrained 0.5 both ways
    # guards, after the behavioural assertion: river answered, the ledger did not
    assert real_path.predict_calls == 2
    assert real_path.fallback_writes == []


def test_rerank_puts_the_reinforced_key_first(real_path):
    """The behaviour the capability advertises ("adapts to your taste as you use
    it"), through the public entry point, on the real model."""
    ranker = real_path.ranker
    before = [k for k, _ in ranker.rerank([(PASSED, 1), (CHOSEN, 2)])]
    real_path.teach()
    after = [k for k, _ in ranker.rerank([(PASSED, 1), (CHOSEN, 2)])]
    assert before == [PASSED, CHOSEN], "an untrained pipeline must not reorder"
    assert after == [CHOSEN, PASSED]
    assert real_path.fallback_writes == []


def test_river_generalizes_to_keys_it_has_never_seen(real_path):
    """The river-specific property the running mean cannot produce at all. The
    pipeline is ONE shared regression over `hash(key) % 997`, so what it learns
    from two keys transfers to every other key; the running mean is a per-key
    ledger and answers the same default for anything it has not been told
    about. This is the contrast that makes the file worth having — the ordering
    assertions above are ones the fallback also satisfies."""
    real_path.teach()
    spread = {real_path.ranker.score(key) for key in UNSEEN}
    assert real_path.fallback_writes == []
    assert len(spread) > 1, (
        f"river scored every unseen key identically ({spread}); that is the "
        "running mean's answer, not a trained model's"
    )
    assert spread != {0.5}


def test_the_running_mean_answers_the_same_default_for_every_unseen_key():
    """The other half of the contrast, and the reason the assertion above is
    river-specific rather than a coincidence. Stays green with river absent."""
    assert {_running_mean_ranker().score(key) for key in UNSEEN} == {0.5}


def test_river_stays_less_certain_than_the_running_mean(real_path):
    """A second contrast, on the same history: the running mean is a per-key
    exponential average with alpha=0.2, so five rounds saturate it past 0.8/0.16;
    river must fit both keys with one shared weight vector at lr=0.01 and stays
    near the decision boundary. Same input, visibly different calibration —
    a degrade to the mean cannot produce river's numbers."""
    real_path.teach()
    mean_ranker = _running_mean_ranker()
    for key in (CHOSEN, PASSED):
        river_gap = abs(real_path.ranker.score(key) - 0.5)
        mean_gap = abs(mean_ranker.score(key) - 0.5)
        assert 0.0 < river_gap < mean_gap, (
            f"{key}: river {river_gap:.4f} vs running mean {mean_gap:.4f}"
        )
    assert real_path.fallback_writes == []


# --------------------------------------------------------------------------
# The fallback contract is unchanged — these stay green with river forced off
# --------------------------------------------------------------------------

class TestRunningMeanFallback:
    def test_forced_unavailable_keeps_the_running_mean_path(self, monkeypatch):
        """Force the "river not installed" branch even though river IS installed
        (it must be, to reach this importorskip-gated file): proves the
        `_HAS_RIVER` guard in `__init__` degrades on its own, not only the
        try/except around the Pipeline construction below it."""
        monkeypatch.setattr(taste_river, "_HAS_RIVER", False)
        ranker = RiverTasteRanker()
        assert ranker._model is None
        for key, chosen in HISTORY:
            ranker.observe(key, chosen)
        assert set(ranker._prefs) == {CHOSEN, PASSED}   # the ledger did the work
        assert ranker.score(CHOSEN) > 0.5 > ranker.score(PASSED)
        ranked = ranker.rerank([(PASSED, 1), (CHOSEN, 2)])
        assert [k for k, _ in ranked] == [CHOSEN, PASSED]

    def test_the_ledger_saturates_the_way_the_exponential_mean_says(self):
        """`cur + 0.2 * (chosen - cur)` from 0.5, five times: the fixed numbers
        the contrast above compares river against."""
        ranker = _running_mean_ranker()
        assert ranker.score(CHOSEN) == pytest.approx(0.83616)
        assert ranker.score(PASSED) == pytest.approx(0.16384)
        assert ranker.score("never-mentioned") == 0.5
