"""Tests for TruthLens schema dataclasses."""
import pytest
from dreamlayer.truth_lens.schema import (
    AUFrame, ProsodyFrame, LinguisticFrame,
    ContactBaseline, CredibilityVector, TruthLensResult,
)


# ---------------------------------------------------------------------------
# AUFrame
# ---------------------------------------------------------------------------

class TestAUFrame:
    def test_valid_creation(self):
        f = AUFrame(au_values=[0.1] * 17, face_confidence=0.9)
        assert len(f.au_values) == 17

    def test_rejects_wrong_length(self):
        with pytest.raises(ValueError):
            AUFrame(au_values=[0.1] * 10, face_confidence=0.9)

    def test_optional_embedding(self):
        f = AUFrame(au_values=[0.0] * 17, face_confidence=0.8,
                    embedding=[0.1] * 512)
        assert len(f.embedding) == 512


# ---------------------------------------------------------------------------
# ProsodyFrame
# ---------------------------------------------------------------------------

class TestProsodyFrame:
    def _calm(self):
        return ProsodyFrame(
            pitch_mean_hz=180, pitch_variance=10, jitter_pct=0.2,
            shimmer_pct=0.3, hesitation_rate=0.1, pause_ratio=0.25,
            speech_rate_norm=1.0, energy_db=-20,
        )

    def _stressed(self):
        return ProsodyFrame(
            pitch_mean_hz=220, pitch_variance=600, jitter_pct=8.0,
            shimmer_pct=12.0, hesitation_rate=4.0, pause_ratio=0.7,
            speech_rate_norm=2.0, energy_db=-10,
        )

    def test_calm_score_low(self):
        assert self._calm().stress_score() < 0.30

    def test_stressed_score_high(self):
        assert self._stressed().stress_score() > 0.65

    def test_score_bounded(self):
        s = self._stressed()
        assert 0.0 <= s.stress_score() <= 1.0


# ---------------------------------------------------------------------------
# LinguisticFrame
# ---------------------------------------------------------------------------

class TestLinguisticFrame:
    def _calm(self):
        return LinguisticFrame(
            hedging_rate=0.01, first_person_rate=0.10,
            complexity_score=0.2, negation_rate=0.02, word_count=50,
        )

    def _deceptive(self):
        return LinguisticFrame(
            hedging_rate=0.20, first_person_rate=0.01,
            complexity_score=0.9, negation_rate=0.15, word_count=50,
        )

    def test_calm_score_low(self):
        assert self._calm().deception_score() < 0.25

    def test_deceptive_score_high(self):
        assert self._deceptive().deception_score() > 0.55

    def test_score_bounded(self):
        assert 0.0 <= self._deceptive().deception_score() <= 1.0


# ---------------------------------------------------------------------------
# CredibilityVector
# ---------------------------------------------------------------------------

class TestCredibilityVector:
    def _make(self, prob, conf, is_stranger=False):
        return CredibilityVector(
            deception_prob=prob, confidence=conf,
            micro_expression_z=1.0, voice_stress_z=1.0, linguistic_z=1.0,
            dominant_channel="voice_stress", is_stranger=is_stranger,
        )

    def test_label_credible(self):
        assert self._make(0.2, 0.8).label == "CREDIBLE"

    def test_label_uncertain(self):
        assert self._make(0.5, 0.8).label == "UNCERTAIN"

    def test_label_elevated(self):
        assert self._make(0.72, 0.8).label == "ELEVATED"

    def test_label_high_alert(self):
        assert self._make(0.90, 0.8).label == "HIGH ALERT"

    def test_label_calibrating_low_confidence(self):
        assert self._make(0.95, 0.1).label == "CALIBRATING"

    def test_color_green(self):
        assert self._make(0.2, 0.9).hud_color == 0x07E0

    def test_color_red(self):
        assert self._make(0.9, 0.9).hud_color == 0xF800

    def test_color_grey_low_confidence(self):
        assert self._make(0.9, 0.1).hud_color == 0x7BEF


# ---------------------------------------------------------------------------
# TruthLensResult → to_hud_card
# ---------------------------------------------------------------------------

class TestTruthLensResult:
    def _result(self, prob=0.6, conf=0.8):
        cv = CredibilityVector(
            deception_prob=prob, confidence=conf,
            micro_expression_z=1.5, voice_stress_z=2.0, linguistic_z=1.0,
            dominant_channel="voice_stress",
        )
        return TruthLensResult(credibility=cv, contact_name="Alex")

    def test_card_type(self):
        assert self._result().to_hud_card()["type"] == "TruthLensCard"

    def test_card_eyebrow(self):
        assert self._result().to_hud_card()["eyebrow"] == "LIE LENS"

    def test_card_has_renderer_hints(self):
        card = self._result().to_hud_card()
        assert "renderer_hints" in card

    def test_card_footer_is_name(self):
        assert self._result().to_hud_card()["footer"] == "Alex"

    def test_low_confidence_fades_opacity(self):
        card = self._result(prob=0.6, conf=0.1).to_hud_card()
        assert card["opacity"] == 0.4

    def test_chromatic_hint_when_high_voice_stress(self):
        cv = CredibilityVector(
            deception_prob=0.8, confidence=0.9,
            micro_expression_z=1.0, voice_stress_z=3.0, linguistic_z=1.0,
            dominant_channel="voice_stress",
        )
        card = TruthLensResult(credibility=cv).to_hud_card()
        assert card["renderer_hints"]["chromatic_aberration"] is True
