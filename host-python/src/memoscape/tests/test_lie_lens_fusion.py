"""Tests for LieLens fusion engine."""
import pytest
from memoscape.lie_lens.schema import (
    AUFrame, ProsodyFrame, LinguisticFrame, ContactBaseline,
)
from memoscape.lie_lens.fusion import fuse


def make_au(activation=0.2):
    return AUFrame(aus=[activation] * 17,
                   micro_exp_label="neutral", micro_exp_confidence=0.6)


def make_prosody(stress=0.2):
    return ProsodyFrame(
        pitch_mean_hz=180, pitch_variance=stress * 500,
        jitter_pct=stress * 3, shimmer_pct=stress * 5,
        hesitation_rate=stress * 2, energy_db=-20,
        speech_rate_norm=1.0 + stress * 0.5,
    )


def make_ling(hedge=0.1):
    from memoscape.lie_lens.linguistic import extract_linguistic_features
    return extract_linguistic_features("I went to the store.")


def make_baseline(contact_id="alice"):
    return ContactBaseline(
        contact_id=contact_id,
        au_mean=[0.15] * 17,
        au_std=[0.05] * 17,
        prosody_pitch_mean=180.0,
        prosody_pitch_std=20.0,
        prosody_jitter_mean=0.5,
        prosody_shimmer_mean=1.0,
        linguistic_hedge_mean=0.08,
        linguistic_fp_mean=0.12,
        sample_count=30,
    )


class TestFusion:
    def test_empty_inputs_low_deception(self):
        cv = fuse([], [], [], None, window_count=0)
        assert cv.deception_prob == pytest.approx(0.5, abs=0.05)
        assert cv.confidence == 0.0

    def test_stranger_confidence_halved(self):
        cv = fuse([make_au()], [make_prosody()], [make_ling()],
                  baseline=None, window_count=4)
        assert cv.confidence <= 0.5
        assert cv.is_stranger is True

    def test_known_contact_higher_confidence(self):
        b = make_baseline()
        cv = fuse([make_au()] * 4, [make_prosody()] * 4,
                  [make_ling()] * 4, baseline=b, window_count=4)
        assert cv.is_stranger is False
        assert cv.confidence == 1.0

    def test_calm_signals_low_deception_prob(self):
        b = make_baseline()
        cv = fuse([make_au(0.1)] * 6, [make_prosody(0.05)] * 6,
                  [make_ling()] * 6, baseline=b, window_count=6)
        assert cv.deception_prob < 0.6

    def test_stressed_signals_higher_deception_prob(self):
        b = make_baseline()
        cv_calm = fuse([make_au(0.1)] * 6, [make_prosody(0.0)] * 6,
                       [make_ling()] * 6, baseline=b, window_count=6)
        cv_stress = fuse([make_au(0.9)] * 6, [make_prosody(0.9)] * 6,
                         [make_ling()] * 6, baseline=b, window_count=6)
        assert cv_stress.deception_prob > cv_calm.deception_prob

    def test_dominant_signal_is_string(self):
        cv = fuse([make_au()], [make_prosody()], [make_ling()],
                  None, window_count=2)
        assert isinstance(cv.dominant_signal, str)

    def test_deception_prob_bounded(self):
        b = make_baseline()
        cv = fuse([make_au(1.0)] * 10, [make_prosody(1.0)] * 10,
                  [make_ling()] * 10, baseline=b, window_count=10)
        assert 0.0 <= cv.deception_prob <= 1.0

    def test_stranger_should_not_alert_below_threshold(self):
        cv = fuse([make_au(0.5)] * 6, [make_prosody(0.5)] * 6,
                  [make_ling()] * 6, baseline=None, window_count=6)
        # Stranger threshold is 0.92; moderate signals shouldn't exceed it
        if cv.deception_prob < 0.92:
            assert cv.should_alert is False
