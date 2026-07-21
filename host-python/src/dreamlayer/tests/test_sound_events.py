"""orchestrator/sound_events.py — the glasses that listen to the world.

PANNs isn't in CI, so the detector tests pin the wheel-absent fallback ([]), and
the bulk of the value — the PURE `attention_for` policy (which sounds are worth a
tap, watch-outs first, speech vetoed) — is tested directly with no model.
"""
from __future__ import annotations

import numpy as np

from dreamlayer.orchestrator import sound_events as S
from dreamlayer.orchestrator.attention import Alert


class TestAttentionPolicy:
    def test_smoke_alarm_is_a_watchout(self):
        a = S.attention_for([("Smoke detector, smoke alarm", 0.8)])
        assert isinstance(a, Alert) and a.level == "watchout"
        assert "Smoke alarm" in a.clue

    def test_kettle_is_a_listen(self):
        a = S.attention_for([("Kettle whistle", 0.6)])
        assert a is not None and a.level == "listen" and "Kettle" in a.clue

    def test_doorbell_is_a_listen(self):
        a = S.attention_for([("Doorbell", 0.5)])
        assert a is not None and "door" in a.clue.lower()

    def test_watchout_outranks_listen(self):
        # both present → the urgent one wins regardless of confidence order
        a = S.attention_for([("Doorbell", 0.95),
                             ("Glass, shatter", 0.4)])
        assert a is not None and a.level == "watchout"

    def test_higher_confidence_wins_within_a_level(self):
        a = S.attention_for([("Doorbell", 0.3), ("Dog, bark", 0.9)])
        assert a is not None and "dog" in a.clue.lower()

    def test_below_threshold_is_ignored(self):
        assert S.attention_for([("Smoke alarm", 0.05)]) is None

    def test_unmapped_sound_is_none(self):
        assert S.attention_for([("Music", 0.99), ("Piano", 0.8)]) is None

    def test_speech_is_vetoed_never_a_tap(self):
        # the whole posture: this rung never acts on people talking
        assert S.attention_for([("Speech", 0.99)]) is None
        assert S.attention_for([("Conversation", 0.9)]) is None
        assert S.attention_for([("Male speech, man speaking", 0.9)]) is None

    def test_malformed_detections_never_raise(self):
        assert S.attention_for([None, (), ("only-label",), ("x", "NaN")]) is None
        assert S.attention_for([{"a": 1}]) is None        # a dict item (KeyError) is swallowed
        assert S.attention_for([("x", object())]) is None
        assert S.attention_for([]) is None
        assert S.attention_for(None) is None

    def test_nan_confidence_does_not_fire_a_false_alarm(self):
        # a NaN confidence on a MAPPED label must NOT defeat the threshold and
        # raise the loudest alert Juno can make (refute 2026-07-21).
        assert S.attention_for([("Smoke alarm", float("nan"))]) is None
        assert S.attention_for([("Doorbell", float("nan"))]) is None

    def test_alert_key_is_stable_for_cooldown(self):
        a = S.attention_for([("Smoke alarm", 0.8)])
        b = S.attention_for([("Smoke alarm", 0.7)])
        assert a is not None and b is not None and a.key == b.key


class TestDetectorFallback:
    def test_detect_is_empty_without_the_wheel(self):
        d = S.SoundEventDetector()
        assert d.detect(np.zeros(32000, np.float32), 32000) == []

    def test_listen_is_none_without_the_wheel(self):
        d = S.SoundEventDetector()
        assert d.listen(np.zeros(32000, np.float32), 32000) is None

    def test_default_detector_none_without_wheel(self):
        assert S.default_sound_detector() is None


class TestAudioCoerce:
    def test_resample_to_32k(self):
        out = S._to_mono(np.linspace(-0.5, 0.5, 16000, dtype=np.float32), 16000, 32000)
        assert out is not None and abs(out.size - 32000) <= 1

    def test_empty_is_none(self):
        assert S._to_mono(np.zeros(0, np.float32), 16000, 32000) is None

    def test_channels_first_stereo_is_not_destroyed(self):
        out = S._to_mono(np.zeros((2, 200), dtype=np.float32), 32000, 32000)
        assert out is not None and out.size == 200

    def test_hot_float_not_mistaken_for_int16(self):
        out = S._to_mono(np.array([-2.0, 2.0], dtype=np.float32), 32000, 32000)
        assert out is not None and float(np.max(np.abs(out))) >= 0.9


def test_sound_events_capability_registered():
    from dreamlayer import capabilities as C
    cap = {c.key: c for c in C.CAPABILITIES}.get("sound_events")
    assert cap is not None, "sound_events capability missing"
    assert cap.extra == "sound-events"
    assert "panns_inference" in cap.modules
    assert cap.seam == "orchestrator/sound_events.py"
