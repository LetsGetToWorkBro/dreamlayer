"""The rule you can read, with the thresholds your own moments chose.

`persona_tuning` was dormant with the plainest possible reason, written in its
own catalogue entry: *"the classifier already applies any rule callable you
hand it — installing this is what lets you BUILD that rule by example … nothing
in the tree builds one yet."* `tune()` is the half that was missing.

It is deliberately NOT "learn a rule". `FunctionClassifier` — what human-learn
actually offers headlessly — wraps a rule you wrote into the scikit-learn API
so it can be scored and grid-searched. The human writes the shape; the wearer's
labelled moments choose the numbers; the answer stays a sentence you can say
out loud. That is the whole argument for this library over a model.

The consumer is `MaturityGate`, whose APPRENTICE confidence bar has always been
a hand-picked 0.85 — the same guess for everyone, about the one question the
wearer answers all day by keeping or swatting a card.
"""
from __future__ import annotations

import random

import pytest

from dreamlayer.orchestrator import maturity as M
from dreamlayer.orchestrator.persona_humanlearn import (
    MIN_EXAMPLES, HumanLearnClassifier, Tuned, tune,
)


def above(rows, min_confidence=0.85):
    """The rule under test, and the one the gate itself applies."""
    return [float(r.get("confidence", 0.0)) >= min_confidence for r in rows]


def _rows(n=60, truth=0.8, seed=7):
    rnd = random.Random(seed)
    rows = [{"confidence": round(rnd.uniform(0.5, 1.0), 2)} for _ in range(n)]
    return rows, [r["confidence"] >= truth for r in rows]


GRID = {"min_confidence": [0.6, 0.7, 0.75, 0.8, 0.85, 0.9]}


class TestTuning:
    def test_it_recovers_the_threshold_the_labels_imply(self):
        rows, labels = _rows()
        best = tune(above, rows, labels, GRID)
        assert best and best.params == {"min_confidence": 0.8}
        assert best.score > 0.95

    def test_a_tuned_rule_becomes_a_classifier(self):
        rows, labels = _rows()
        c = HumanLearnClassifier.from_tuned(above, tune(above, rows, labels, GRID))
        assert c.classify({"confidence": 0.95}) == "yes"
        assert c.classify({"confidence": 0.55}) == "no"

    def test_a_refused_tuning_does_not_bind_guessed_parameters(self):
        # Applying the rule with made-up numbers is worse than not applying it.
        c = HumanLearnClassifier.from_tuned(above, Tuned(refused="nope"))
        assert c.classify({"confidence": 0.99}) == "neutral"

    def test_too_few_examples_is_refused_not_guessed(self):
        rows, labels = _rows(n=MIN_EXAMPLES - 1)
        got = tune(above, rows, labels, GRID)
        assert not got and "labelled examples" in got.refused

    def test_one_label_is_refused(self):
        rows, _ = _rows()
        got = tune(above, rows, [True] * len(rows), GRID)
        assert not got and "same label" in got.refused

    def test_mismatched_lengths_are_refused(self):
        rows, labels = _rows()
        assert not tune(above, rows, labels[:-1], GRID)

    def test_an_empty_grid_still_scores_the_rule_as_written(self):
        rows, labels = _rows()
        got = tune(above, rows, labels, {})
        assert got and got.params == {}

    def test_a_rule_that_raises_is_refused_not_crashed(self):
        def broken(rows, **kw):
            raise RuntimeError("bad rule")
        rows, labels = _rows()
        got = tune(broken, rows, labels, GRID)
        assert not got and "could not score" in got.refused

    def test_a_rule_returning_the_wrong_length_loses(self):
        def short(rows, min_confidence=0.85):
            return [True]
        rows, labels = _rows()
        assert not tune(short, rows, labels, GRID)


class TestTheDependencyIsHonest:
    """`cross_validated` is the one thing the wearer's caller cannot infer, and
    the difference the dependency actually buys."""

    def test_the_fallback_tunes_too(self):
        # The floor: no dependency must never mean no answer.
        rows, labels = _rows()
        from dreamlayer.orchestrator.persona_humanlearn import _tune_plain
        got = _tune_plain(above, rows, labels, GRID)
        assert got and got.params == {"min_confidence": 0.8}

    def test_the_fallback_says_it_did_not_cross_validate(self):
        rows, labels = _rows()
        from dreamlayer.orchestrator.persona_humanlearn import _tune_plain
        assert _tune_plain(above, rows, labels, GRID).cross_validated is False

    def test_without_the_library_the_answer_still_comes_and_says_so(self,
                                                                    monkeypatch):
        from dreamlayer.orchestrator import persona_humanlearn as ph
        monkeypatch.setattr(ph, "_HAS_HULEARN", False)
        rows, labels = _rows()
        got = ph.tune(above, rows, labels, GRID)
        assert got and got.params == {"min_confidence": 0.8}
        assert got.cross_validated is False

    def test_with_the_library_it_cross_validates(self):
        pytest.importorskip("hulearn")
        pytest.importorskip("sklearn")
        rows, labels = _rows()
        got = tune(above, rows, labels, GRID)
        assert got.cross_validated is True, (
            "hulearn is installed but the k-fold path did not run — the "
            "capability would be reporting a benefit it is not delivering")


class TestTheGateUsesIt:
    """`MaturityGate.tuned_confidence` — the consumer that was missing."""

    def _gate(self, now=1_000_000.0):
        g = M.MaturityGate(now_fn=lambda: now)
        g.paired_at = now - 30 * 86400.0          # time served
        g.events_seen = 1000
        return g

    def _teach(self, gate, n=40, truth=0.90, lo=0.75, seed=3):
        """A wearer who keeps the surest cards and swats the rest.

        The confidence range is chosen so the dismissal rate lands BETWEEN the
        two rates the gate already reacts to on its own: under 0.60 so
        recalibration does not fire, over 0.40 so RESIDENT is not earned — and
        RESIDENT skips the confidence gate entirely. Teaching outside that band
        tests the regression mechanism instead of this one.
        """
        rnd = random.Random(seed)
        for _ in range(n):
            conf = round(rnd.uniform(lo, 1.0), 2)
            gate.observe_card(dismissed=conf < truth, confidence=conf,
                              kind="commitment")
        assert M.APPRENTICE_MAX_DISMISS < gate._dismiss_rate() \
            <= M.REGRESS_DISMISS, "the fixture drifted out of APPRENTICE"
        assert gate.state() == M.APPRENTICE

    def test_no_history_means_the_hand_picked_floor(self):
        assert self._gate().tuned_confidence() == 0.0

    def test_too_few_labelled_cards_is_not_a_fit(self):
        g = self._gate()
        self._teach(g, n=M.TUNE_MIN_CARDS - 1)
        assert g.tuned_confidence() == 0.0

    def test_a_wearer_who_only_keeps_the_surest_cards_raises_the_bar(self):
        g = self._gate()
        self._teach(g)
        assert g.tuned_confidence() > M.APPRENTICE_MIN_CONFIDENCE

    def test_it_can_never_lower_the_bar(self):
        # The load-bearing one. A wearer who keeps everything must not be able
        # to argue the system into interrupting MORE — a trust mechanism that
        # loosens itself from its own output is not a trust mechanism.
        g = self._gate()
        rnd = random.Random(11)
        for _ in range(40):
            conf = round(rnd.uniform(0.5, 1.0), 2)
            g.observe_card(dismissed=conf < 0.55, confidence=conf)
        assert g.tuned_confidence() >= M.APPRENTICE_MIN_CONFIDENCE

    def test_the_gate_applies_the_tuned_bar(self):
        g = self._gate()
        self._teach(g)
        bar = g.tuned_confidence()
        assert bar > M.APPRENTICE_MIN_CONFIDENCE
        # A card that clears the OLD floor but not the learned one is refused.
        between = (M.APPRENTICE_MIN_CONFIDENCE + bar) / 2.0
        assert g.allows_proactive("commitment", confidence=between) is False
        assert g.allows_proactive("commitment", confidence=1.0) is True

    def test_a_card_with_no_confidence_leaves_the_log_empty(self):
        # Every existing caller — ops_ingest's SHAKE_DISMISS — passes no
        # confidence, and must keep behaving exactly as before.
        g = self._gate()
        for _ in range(40):
            g.observe_card(dismissed=True)
        assert g.tuned_confidence() == 0.0
        assert g.summary()["labelled_cards"] == 0

    def test_a_bad_confidence_is_not_a_label(self):
        g = self._gate()
        for _ in range(40):
            g.observe_card(dismissed=True, confidence=float("nan"))
        # NaN survives float() but can never clear a threshold, so it cannot
        # invent a bar; what matters is that it did not raise.
        assert isinstance(g.tuned_confidence(), float)

    def test_the_dismissal_rate_is_untouched_by_the_new_log(self):
        g = self._gate()
        self._teach(g, n=20)
        assert 0.0 < g.summary()["dismiss_rate"] < 1.0
        assert g.summary()["labelled_cards"] == 20

    def test_the_summary_reports_the_live_bar(self):
        g = self._gate()
        assert g.summary()["confidence_bar"] == M.APPRENTICE_MIN_CONFIDENCE
        self._teach(g)
        assert g.summary()["confidence_bar"] == g.tuned_confidence()

    def test_the_fit_is_cached_until_a_new_card_arrives(self):
        g = self._gate()
        self._teach(g)
        first = g.tuned_confidence()
        calls = []
        import dreamlayer.orchestrator.persona_humanlearn as ph
        real = ph.tune
        ph.tune = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
        try:
            assert g.tuned_confidence() == first and not calls   # cached
            g.observe_card(dismissed=False, confidence=0.99)
            g.tuned_confidence()
            assert calls                                          # refitted
        finally:
            ph.tune = real


class TestItSurvivesARestart:
    class _DB:
        def __init__(self):
            self.rows: dict = {}

        def get_setting(self, k):
            return self.rows.get(k)

        def set_setting(self, k, v):
            self.rows[k] = v

    def test_the_labelled_log_persists(self):
        db = self._DB()
        now = 1_000_000.0
        g = M.MaturityGate(db=db, now_fn=lambda: now)
        rnd = random.Random(5)
        for _ in range(30):
            c = round(rnd.uniform(0.5, 1.0), 2)
            g.observe_card(dismissed=c < 0.95, confidence=c, kind="event")
        again = M.MaturityGate(db=db, now_fn=lambda: now)
        assert again.summary()["labelled_cards"] == 30
        assert again.tuned_confidence() == g.tuned_confidence()

    def test_a_profile_written_before_the_log_existed_still_loads(self):
        import json
        db = self._DB()
        db.rows["maturity"] = json.dumps({
            "paired_at": 1.0, "events_seen": 500, "regressed_until": 0.0,
            "resident": True, "sent_today": 0, "sent_day": 0,
            "cards": [False, True, False]})          # no "labelled" key
        g = M.MaturityGate(db=db, now_fn=lambda: 1_000_000.0)
        assert g.events_seen == 500
        assert g.summary()["labelled_cards"] == 0
        assert g.tuned_confidence() == 0.0

    def test_a_corrupt_labelled_row_does_not_drop_the_rest(self):
        import json
        db = self._DB()
        db.rows["maturity"] = json.dumps({
            "paired_at": 1.0, "events_seen": 500,
            "labelled": [{"confidence": 0.9, "kind": "e", "d": False},
                         {"confidence": "not a number", "d": True},
                         {"kind": "no confidence at all", "d": True},
                         {"confidence": 0.4, "kind": "e", "d": True}]})
        g = M.MaturityGate(db=db, now_fn=lambda: 1_000_000.0)
        assert g.summary()["labelled_cards"] == 2
