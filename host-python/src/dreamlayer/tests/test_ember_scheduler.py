"""Ember scheduler — the curve is pure, gentle to misses, honest about
lapses, and graduation is a ratchet (docs/EMBER.md)."""

import pytest

from dreamlayer.ember import (
    CONSOLIDATION_THRESHOLD_DAYS, RecallOutcome, defer, interval_for,
    is_due, next_review, retrievability, seed_state,
)
from dreamlayer.ember.scheduler import (
    DAY, MAX_INTERVAL_DAYS, MIN_INTERVAL_DAYS, TARGET_RETENTION,
)

NOW = 1_700_000_000.0


def graduate(state, outcome=RecallOutcome.GOOD, cap=50):
    """Review at every due date until graduation; returns (state, reps)."""
    n = 0
    while not state.graduated and n < cap:
        state = next_review(state, outcome, state.due_ts)
        n += 1
    return state, n


class TestCurve:
    def test_pure_and_deterministic(self):
        s = seed_state(NOW)
        a = next_review(s, RecallOutcome.GOOD, NOW + 3 * DAY)
        b = next_review(s, RecallOutcome.GOOD, NOW + 3 * DAY)
        assert a == b
        assert s.reps == 1          # the original never mutated

    def test_retrievability_is_090_exactly_at_due(self):
        s = seed_state(NOW)
        assert retrievability(s, s.due_ts) == pytest.approx(TARGET_RETENTION)

    def test_prompts_never_nag_never_archive(self):
        # the interval clamp holds at both extremes of stability
        assert interval_for(0.001) == MIN_INTERVAL_DAYS
        assert interval_for(10_000.0) == MAX_INTERVAL_DAYS

    def test_success_grows_stability_lapse_shrinks_it(self):
        s = seed_state(NOW)
        due = s.due_ts
        assert next_review(s, RecallOutcome.GOOD, due).stability > s.stability
        assert next_review(s, RecallOutcome.FORGOT, due).stability < s.stability

    def test_grades_order_the_growth(self):
        s = seed_state(NOW)
        due = s.due_ts
        hard = next_review(s, RecallOutcome.HARD, due).stability
        good = next_review(s, RecallOutcome.GOOD, due).stability
        easy = next_review(s, RecallOutcome.EASY, due).stability
        assert hard < good < easy

    def test_harder_won_recall_consolidates_more(self):
        # the same GOOD, reached further down the forgetting curve, grows more
        s = seed_state(NOW)
        early = next_review(s, RecallOutcome.GOOD, s.due_ts)
        late = next_review(s, RecallOutcome.GOOD, s.due_ts + 20 * DAY)
        assert late.stability > early.stability


class TestMissed:
    def test_missed_is_not_a_lapse(self):
        s = seed_state(NOW)
        m = next_review(s, RecallOutcome.MISSED, s.due_ts)
        assert m.stability == s.stability
        assert m.difficulty == s.difficulty
        assert m.lapses == s.lapses and m.reps == s.reps
        assert m.due_ts > s.due_ts          # ...but it does come back around

    def test_defer_floors_at_half_a_day(self):
        s = seed_state(NOW, RecallOutcome.FORGOT)   # tiny stability
        d = defer(s, NOW)
        assert d.due_ts - NOW >= MIN_INTERVAL_DAYS * DAY


class TestGraduation:
    def test_good_recalls_graduate_within_a_year_of_reviews(self):
        s, n = graduate(seed_state(NOW))
        assert s.graduated
        assert s.stability >= CONSOLIDATION_THRESHOLD_DAYS
        assert 5 <= n <= 12, "deletion must be earned slowly, not instantly"

    def test_easy_material_graduates_faster(self):
        _, n_good = graduate(seed_state(NOW))
        _, n_easy = graduate(seed_state(NOW, RecallOutcome.EASY),
                             RecallOutcome.EASY)
        assert n_easy < n_good

    def test_graduation_is_a_ratchet(self):
        s, _ = graduate(seed_state(NOW))
        lapsed = next_review(s, RecallOutcome.FORGOT, s.due_ts)
        assert lapsed.stability < s.stability
        assert lapsed.graduated, "an earned offer is never revoked"

    def test_relearning_is_cheaper_than_learning(self):
        # the savings effect: after one lapse, the same grades regrow faster
        fresh = seed_state(NOW)
        lapsed = next_review(fresh, RecallOutcome.FORGOT, fresh.due_ts)
        regrown = next_review(lapsed, RecallOutcome.GOOD, lapsed.due_ts)
        virgin = seed_state(NOW, RecallOutcome.FORGOT)
        grown = next_review(virgin, RecallOutcome.GOOD, virgin.due_ts)
        assert (regrown.stability / lapsed.stability) > \
               (grown.stability / virgin.stability) * 0.999

    def test_difficulty_stays_in_band_forever(self):
        s = seed_state(NOW)
        for outcome in (RecallOutcome.FORGOT,) * 10 + (RecallOutcome.EASY,) * 10:
            s = next_review(s, outcome, s.due_ts)
            assert 1.0 <= s.difficulty <= 10.0


class TestDue:
    def test_is_due_respects_the_clock(self):
        s = seed_state(NOW)
        assert not is_due(s, NOW)
        assert is_due(s, s.due_ts)
