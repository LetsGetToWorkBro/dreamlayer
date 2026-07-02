"""Tests for TruthLens fusion engine."""
import pytest
from dreamlayer.truth_lens.schema import (
    AUFrame, ProsodyFrame, LinguisticFrame, ContactBaseline,
)
from dreamlayer.truth_lens.fusion import FusionEngine


def calm_au():
    return AUFrame(au_values=[0.05] * 17, face_confidence=0.9)


def stressed_au():
    return AUFrame(au_values=[0.9] * 17, face_confidence=0.9)


def calm_prosody():
    return ProsodyFrame(
        pitch_mean_hz=180, pitch_variance=10, jitter_pct=0.2,
        shimmer_pct=0.3, hesitation_rate=0.1, pause_ratio=0.25,
        speech_rate_norm=1.0, energy_db=-20,
    )


def stressed_prosody():
    return ProsodyFrame(
        pitch_mean_hz=220, pitch_variance=600, jitter_pct=8.0,
        shimmer_pct=12.0, hesitation_rate=4.0, pause_ratio=0.7,
        speech_rate_norm=2.0, energy_db=-10,
    )


def calm_ling():
    return LinguisticFrame(
        hedging_rate=0.01, first_person_rate=0.10,
        complexity_score=0.2, negation_rate=0.02, word_count=50,
    )


def deceptive_ling():
    return LinguisticFrame(
        hedging_rate=0.25, first_person_rate=0.01,
        complexity_score=0.9, negation_rate=0.15, word_count=50,
    )


def calibrated_baseline():
    b = ContactBaseline(contact_id="test")
    b.sample_count = 20
    b.is_calibrated = True
    return b


class TestFusionEngine:
    def setup_method(self):
        self.fe = FusionEngine()

    def test_stranger_mode_when_no_baseline(self):
        cv = self.fe.fuse(calm_au(), calm_prosody(), calm_ling(), None)
        assert cv.is_stranger is True

    def test_stranger_mode_low_confidence(self):
        cv = self.fe.fuse(calm_au(), calm_prosody(), calm_ling(), None)
        assert cv.confidence <= 0.2

    def test_known_contact_not_stranger(self):
        b = calibrated_baseline()
        cv = self.fe.fuse(calm_au(), calm_prosody(), calm_ling(), b)
        assert cv.is_stranger is False

    def test_calm_signals_low_deception(self):
        b = calibrated_baseline()
        cv = self.fe.fuse(calm_au(), calm_prosody(), calm_ling(), b)
        assert cv.deception_prob < 0.35

    def test_stressed_signals_higher_deception(self):
        b = calibrated_baseline()
        cv = self.fe.fuse(stressed_au(), stressed_prosody(), deceptive_ling(), b)
        assert cv.deception_prob > 0.45

    def test_missing_channels_handled(self):
        b = calibrated_baseline()
        cv = self.fe.fuse(None, stressed_prosody(), None, b)
        assert 0.0 <= cv.deception_prob <= 1.0

    def test_dominant_channel_is_string(self):
        b = calibrated_baseline()
        cv = self.fe.fuse(calm_au(), calm_prosody(), calm_ling(), b)
        assert isinstance(cv.dominant_channel, str)

    def test_deception_prob_bounded(self):
        b = calibrated_baseline()
        cv = self.fe.fuse(stressed_au(), stressed_prosody(), deceptive_ling(), b)
        assert 0.0 <= cv.deception_prob <= 1.0

    def test_confidence_bounded(self):
        b = calibrated_baseline()
        cv = self.fe.fuse(stressed_au(), stressed_prosody(), deceptive_ling(), b)
        assert 0.0 <= cv.confidence <= 1.0
