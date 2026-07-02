"""Tests for TruthLens feature extractors: prosody + linguistic."""
import numpy as np
import pytest
from dreamlayer.truth_lens.prosody import ProsodyAnalyzer, BIN_HZ, SILENCE_THRESHOLD
from dreamlayer.truth_lens.linguistic import LinguisticAnalyzer


def make_fft(peak_hz: float) -> np.ndarray:
    fft = np.zeros(512)
    fft[int(peak_hz / BIN_HZ)] = 1.0
    return fft


class TestProsodyAnalyzer:
    def test_returns_none_before_window_complete(self):
        pa = ProsodyAnalyzer(frames_per_window=40)
        for _ in range(30):
            result = pa.feed(make_fft(200), 0.3)
        assert result is None

    def test_returns_frame_on_window_complete(self):
        pa = ProsodyAnalyzer(frames_per_window=10)
        result = None
        for _ in range(10):
            result = pa.feed(make_fft(200), 0.3)
        assert result is not None

    def test_silence_gives_pause_ratio_one(self):
        pa = ProsodyAnalyzer(frames_per_window=10)
        result = None
        for _ in range(10):
            result = pa.feed(None, 0.0)
        assert result is not None
        assert result.pause_ratio == 1.0

    def test_voiced_gives_low_pause_ratio(self):
        pa = ProsodyAnalyzer(frames_per_window=10)
        result = None
        for _ in range(10):
            result = pa.feed(make_fft(180), 0.5)
        assert result is not None
        assert result.pause_ratio == 0.0

    def test_stress_score_stable_speech_low(self):
        pa = ProsodyAnalyzer(frames_per_window=20)
        result = None
        for _ in range(20):
            result = pa.feed(make_fft(180), 0.3)
        assert result is not None
        assert result.stress_score() < 0.4

    def test_energy_db_nonzero_amplitude(self):
        pa = ProsodyAnalyzer(frames_per_window=10)
        result = None
        for _ in range(10):
            result = pa.feed(make_fft(200), 0.5)
        assert result is not None
        assert result.energy_db > -60


class TestLinguisticAnalyzer:
    def setup_method(self):
        self.la = LinguisticAnalyzer()

    def test_returns_none_for_empty(self):
        assert self.la.analyse("") is None
        assert self.la.analyse(None) is None

    def test_detects_high_hedging(self):
        text = "I think maybe probably you could possibly consider this"
        f = self.la.analyse(text)
        assert f is not None
        assert f.hedging_rate > 0.3

    def test_detects_first_person(self):
        text = "I went to the store and I bought my groceries myself"
        f = self.la.analyse(text)
        assert f is not None
        assert f.first_person_rate > 0.1

    def test_detects_negation(self):
        text = "I never did that and I don't know what you're talking about"
        f = self.la.analyse(text)
        assert f is not None
        assert f.negation_rate > 0.05

    def test_low_deception_score_for_direct_speech(self):
        text = "I went to the office at nine and met with the team."
        f = self.la.analyse(text)
        assert f is not None
        assert f.deception_score() < 0.30

    def test_high_deception_score_for_evasive_speech(self):
        text = ("I mean, I think maybe something could have perhaps "
                "sort of happened, I guess, basically")
        f = self.la.analyse(text)
        assert f is not None
        assert f.deception_score() > 0.40

    def test_word_count_correct(self):
        text = "one two three four five"
        f = self.la.analyse(text)
        assert f.word_count == 5
