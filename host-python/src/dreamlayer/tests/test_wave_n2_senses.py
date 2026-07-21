"""Wave N2 senses: Moonshine ASR, BirdNET lens, sherpa tagging ladder.

None of the engines/models are in CI, so these pin the fallback contracts, the
pure bird_alert policy (same NaN discipline as sound_events), the model-dir
discovery, and the capability registrations.
"""
from __future__ import annotations

import numpy as np

from dreamlayer.orchestrator import sound_events as S
from dreamlayer.orchestrator.asr_moonshine import (
    MoonshineASR, default_moonshine, find_moonshine_dir, _FILES,
)
from dreamlayer.orchestrator.bird_lens import (
    BirdSongLens, bird_alert, default_bird_lens,
)


class TestMoonshine:
    def test_no_model_dir_found(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DL_MOONSHINE_DIR", raising=False)
        assert find_moonshine_dir(None) is None
        assert find_moonshine_dir(str(tmp_path)) is None      # empty dir → incomplete

    def test_complete_dir_is_found(self, tmp_path):
        for f in _FILES:
            (tmp_path / f).write_bytes(b"x")
        assert find_moonshine_dir(str(tmp_path)) == tmp_path

    def test_incomplete_dir_is_skipped(self, tmp_path):
        (tmp_path / "encode.onnx").write_bytes(b"x")          # only one file
        assert find_moonshine_dir(str(tmp_path)) is None

    def test_transcribe_empty_without_engine(self):
        m = MoonshineASR()
        assert m.ready is False
        assert m.transcribe(np.zeros(1600, np.float32), 16000) == ""

    def test_default_none_without_model(self):
        assert default_moonshine() is None


class TestBirdAlertPolicy:
    def test_best_bird_becomes_a_gentle_listen(self):
        a = bird_alert([("Song Sparrow", 0.8), ("American Robin", 0.6)])
        assert a is not None and a.level == "listen"
        assert "Song Sparrow" in a.clue
        assert a.key == "bird:song sparrow"

    def test_below_threshold_or_nan_is_silent(self):
        assert bird_alert([("Song Sparrow", 0.3)]) is None
        assert bird_alert([("Song Sparrow", float("nan"))]) is None

    def test_malformed_detections_never_raise(self):
        assert bird_alert([None, (), ("x",), {"a": 1}, ("", 0.9)]) is None
        assert bird_alert(None) is None

    def test_key_is_stable_for_cooldown(self):
        a = bird_alert([("Wren", 0.9)])
        b = bird_alert([("Wren", 0.7)])
        assert a.key == b.key


class TestBirdLensFallback:
    def test_identify_empty_without_wheel(self):
        lens = BirdSongLens()
        if not BirdSongLens.available:
            assert lens.ready is False
            assert lens.identify(np.zeros(48000, np.float32)) == []
            assert lens.listen(np.zeros(48000, np.float32)) is None

    def test_default_none_without_wheel(self):
        if not BirdSongLens.available:
            assert default_bird_lens() is None


class TestSherpaLadder:
    def test_detector_still_empty_with_no_engine(self):
        d = S.SoundEventDetector()
        assert d.detect(np.zeros(32000, np.float32), 32000) == []
        assert d.backend == ""

    def test_sherpa_dir_without_wheel_stays_off(self, tmp_path):
        (tmp_path / "model.onnx").write_bytes(b"x")
        (tmp_path / "labels.txt").write_text("0,alarm")
        d = S.SoundEventDetector(sherpa_dir=str(tmp_path))
        # neither wheel in CI → still cleanly off, never raises
        assert d.detect(np.zeros(16000, np.float32), 16000) == []


def test_wave_n2_capabilities_registered():
    from dreamlayer import capabilities as C
    caps = {c.key: c for c in C.CAPABILITIES}
    assert caps["asr_moonshine"].extra == "voice"
    assert "sherpa_onnx" in caps["asr_moonshine"].modules
    assert caps["bird_song"].extra == "birds"
    assert "birdnetlib" in caps["bird_song"].modules
    assert "sherpa_onnx" in caps["sound_events"].modules      # the ladder is declared
