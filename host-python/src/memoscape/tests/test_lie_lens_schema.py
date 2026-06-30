"""Tests for LieLens schema dataclasses."""
import pytest
from memoscape.lie_lens.schema import (
    AUFrame, ProsodyFrame, LinguisticFrame,
    CredibilityVector, ContactBaseline, LieLensResult,
)


class TestAUFrame:
    def test_deception_au_score_range(self):
        aus = [0.5] * 17
        f = AUFrame(aus=aus, micro_exp_label="contempt",
                    micro_exp_confidence=0.8)
        s = f.deception_au_score()
        assert 0.0 <= s <= 1.0

    def test_zero_aus_zero_score(self):
        f = AUFrame(aus=[0.0] * 17, micro_exp_label="neutral",
                    micro_exp_confidence=0.5)
        assert f.deception_au_score() == 0.0

    def test_high_aus_high_score(self):
        aus = [1.0] * 17
        f = AUFrame(aus=aus, micro_exp_label="fear",
                    micro_exp_confidence=0.9)
        assert f.deception_au_score() > 0.5


class TestProsodyFrame:
    def test_calm_score_low(self):
        f = ProsodyFrame(pitch_mean_hz=180, pitch_variance=10,
                         jitter_pct=0.3, shimmer_pct=0.5,
                         hesitation_rate=0.2, energy_db=-20,
                         speech_rate_norm=1.0)
        assert f.stress_score() < 0.25

    def test_stressed_score_high(self):
        f = ProsodyFrame(pitch_mean_hz=300, pitch_variance=700,
                         jitter_pct=8.0, shimmer_pct=12.0,
                         hesitation_rate=3.5, energy_db=-5,
                         speech_rate_norm=2.0)
        assert f.stress_score() > 0.6

    def test_score_clamped(self):
        f = ProsodyFrame(pitch_mean_hz=0, pitch_variance=9999,
                         jitter_pct=99, shimmer_pct=99,
                         hesitation_rate=10, energy_db=0,
                         speech_rate_norm=5.0)
        assert f.stress_score() == 1.0


class TestLinguisticFrame:
    def test_hedging_detected(self):
        from memoscape.lie_lens.linguistic import extract_linguistic_features
        lf = extract_linguistic_features("Maybe I think it was kind of okay.")
        assert lf.hedging_score > 0.0

    def test_no_hedging(self):
        from memoscape.lie_lens.linguistic import extract_linguistic_features
        lf = extract_linguistic_features("I went to the store at 3pm on Tuesday.")
        assert lf.hedging_score < lf.specificity_score

    def test_empty_text(self):
        from memoscape.lie_lens.linguistic import extract_linguistic_features
        lf = extract_linguistic_features("")
        assert lf.hedging_score == 0.0
        assert lf.deception_score() >= 0.0

    def test_deception_score_range(self):
        from memoscape.lie_lens.linguistic import extract_linguistic_features
        lf = extract_linguistic_features("I don't know, maybe, I'm not sure.")
        assert 0.0 <= lf.deception_score() <= 1.0


class TestCredibilityVector:
    def make_cv(self, prob=0.5, conf=0.8, stranger=False):
        return CredibilityVector(
            deception_prob=prob, confidence=conf,
            micro_exp_z=1.0, voice_stress_z=1.0, linguistic_z=1.0,
            dominant_signal="voice_stress", is_stranger=stranger,
            window_count=6,
        )

    def test_label_credible(self):
        assert self.make_cv(prob=0.2).label == "CREDIBLE"

    def test_label_uncertain(self):
        assert self.make_cv(prob=0.45).label == "UNCERTAIN"

    def test_label_elevated(self):
        assert self.make_cv(prob=0.65).label == "ELEVATED"

    def test_label_deceptive(self):
        assert self.make_cv(prob=0.80).label == "DECEPTIVE"

    def test_label_high_deception(self):
        assert self.make_cv(prob=0.95).label == "HIGH DECEPTION"

    def test_label_reading_low_confidence(self):
        assert self.make_cv(prob=0.9, conf=0.1).label == "READING"

    def test_should_alert_true(self):
        assert self.make_cv(prob=0.80, conf=0.8).should_alert is True

    def test_should_alert_false_low_confidence(self):
        assert self.make_cv(prob=0.80, conf=0.3).should_alert is False

    def test_stranger_higher_threshold(self):
        cv = self.make_cv(prob=0.80, conf=0.8, stranger=True)
        assert cv.should_alert is False  # 0.80 < 0.92 stranger threshold

    def test_color_green_for_credible(self):
        assert self.make_cv(prob=0.1).hud_color == 0x07E0

    def test_color_red_for_high_deception(self):
        assert self.make_cv(prob=0.95).hud_color == 0xF800


class TestLieLensResult:
    def test_to_hud_card_type(self):
        from memoscape.lie_lens.schema import CredibilityVector, LieLensResult
        cv = CredibilityVector(
            deception_prob=0.5, confidence=0.8,
            micro_exp_z=1.0, voice_stress_z=1.0, linguistic_z=1.0,
            dominant_signal="voice_stress", is_stranger=False, window_count=5,
        )
        r = LieLensResult(credibility=cv, contact_name="Alice")
        card = r.to_hud_card()
        assert card["type"] == "LieLensCard"
        assert card["eyebrow"] == "LIE LENS"
        assert card["name"] == "Alice"

    def test_to_hud_card_has_fx_keys(self):
        from memoscape.lie_lens.renderer import render_lie_lens_card
        from memoscape.lie_lens.schema import CredibilityVector, LieLensResult
        cv = CredibilityVector(
            deception_prob=0.85, confidence=0.9,
            micro_exp_z=2.5, voice_stress_z=3.0, linguistic_z=1.8,
            dominant_signal="micro_exp", is_stranger=False, window_count=8,
        )
        r = LieLensResult(credibility=cv)
        card = render_lie_lens_card(r)
        assert "fx" in card
        assert "chromatic_aberration" in card["fx"]
        assert "particle_color" in card["fx"]
        assert "audio_delay_ms" in card["fx"]
