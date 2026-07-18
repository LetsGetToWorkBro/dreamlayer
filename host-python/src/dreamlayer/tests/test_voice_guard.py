"""voice_guard — never voiceprint a stranger (B4).

person_guard refuses to identify a stranger's face; voice_guard is its twin for
speaker biometrics. The capture pipeline used to compute AND retain an ECAPA
voiceprint for EVERY speech segment — including bystanders who never consented
(refute 2026-07-18: `last_speaker_embedding = emb` ran unconditionally, even with
no resolver to ever use it). These pin the new rule: a voiceprint is retained only
for an ENROLLED speaker; a stranger's is discarded, and when identification is
impossible none is computed at all.
"""
from __future__ import annotations

import pytest

from dreamlayer.orchestrator import voice_guard
from dreamlayer.orchestrator.capture import CapturePipeline


# --- the label classifier ----------------------------------------------------

@pytest.mark.parametrize("label", ["me", "Me", "SELF", "wearer", "owner", "I"])
def test_self_is_always_enrolled(label):
    assert voice_guard.is_self(label) is True
    assert voice_guard.is_enrolled_label(label) is True
    assert voice_guard.retain_voiceprint(label) is True


@pytest.mark.parametrize("label", [
    "", "them", "They", "other", "unknown", "stranger", "guest", "someone",
    "speaker0", "speaker 1", "spk_3", "voice-2", "s1", "?", "none",
])
def test_placeholders_are_strangers(label):
    assert voice_guard.is_enrolled_label(label) is False
    assert voice_guard.defers_speaker(label) is True
    assert voice_guard.retain_voiceprint(label) is False


@pytest.mark.parametrize("label", ["Priya", "Maya", "Dr. Chen", "alex"])
def test_a_resolved_name_is_enrolled_by_default(label):
    # With no explicit registry, a non-placeholder name means the resolver
    # matched a registered voiceprint — enrolled.
    assert voice_guard.is_enrolled_label(label) is True
    assert voice_guard.retain_voiceprint(label) is True


def test_explicit_enrolled_set_is_authoritative():
    enrolled = ["Priya", "Sam"]
    assert voice_guard.retain_voiceprint("Priya", enrolled) is True
    assert voice_guard.retain_voiceprint("me", enrolled) is True         # self always
    # a name NOT in the registry is a stranger even though it looks like a name
    assert voice_guard.retain_voiceprint("Mallory", enrolled) is False
    assert voice_guard.defers_speaker("Mallory", enrolled) is True


def test_guard_embedding_keeps_enrolled_drops_stranger():
    vec = [0.1, 0.2, 0.3]
    assert voice_guard.guard_embedding(vec, "Priya") == vec
    assert voice_guard.guard_embedding(vec, "them") is None
    assert voice_guard.guard_embedding(vec, "") is None


def test_should_attempt_needs_a_resolver():
    assert voice_guard.should_attempt_voiceprint(has_resolver=False) is False
    assert voice_guard.should_attempt_voiceprint(has_resolver=True) is True
    # an empty explicit registry means no one to match → don't compute
    assert voice_guard.should_attempt_voiceprint(True, enrolled=[]) is False
    assert voice_guard.should_attempt_voiceprint(True, enrolled=["Priya"]) is True


# --- the capture pipeline actually applies it --------------------------------

class _Orch:
    class _Priv:
        def allow_capture(self):
            return True

    def __init__(self):
        self.privacy = self._Priv()
        self.captions = []

    def hear(self, text, now=None):
        return {}

    def ingest_caption(self, text, speaker=""):
        self.captions.append((text, speaker))


class _ASR:
    def __init__(self, text):
        self._t = text

    def transcribe(self, seg):
        return self._t


class _VAD:
    def is_speech(self, samples):
        return any(abs(x) > 0.1 for x in samples)


class _Emb:
    def embed(self, seg):
        return [1.0, 0.0, 0.0]


def _drive(cap):
    cap.push_pcm([0.5] * 10, ts=0.0)      # speech
    cap.push_pcm([0.0] * 10, ts=1.0)      # trailing silence → endpoint


def test_no_resolver_means_no_voiceprint_is_even_computed():
    orch = _Orch()
    cap = CapturePipeline(orch, vad=_VAD(), asr=_ASR("hi"), speaker=_Emb())
    _drive(cap)
    assert orch.captions == [("hi", "")]
    assert cap.last_speaker_embedding is None      # nothing to identify against


def test_stranger_voiceprint_is_discarded_not_retained():
    orch = _Orch()
    cap = CapturePipeline(orch, vad=_VAD(), asr=_ASR("hi"), speaker=_Emb(),
                          speaker_resolver=lambda e: "them")   # unresolved → placeholder
    _drive(cap)
    assert orch.captions == [("hi", "them")]        # caption still diarized
    assert cap.last_speaker_embedding is None       # but the biometric is dropped


def test_enrolled_speaker_voiceprint_is_kept():
    orch = _Orch()
    cap = CapturePipeline(orch, vad=_VAD(), asr=_ASR("hi"), speaker=_Emb(),
                          speaker_resolver=lambda e: "Priya")
    _drive(cap)
    assert orch.captions == [("hi", "Priya")]
    assert cap.last_speaker_embedding == [1.0, 0.0, 0.0]


def test_explicit_registry_gate_in_the_pipeline():
    orch = _Orch()
    # "Priya" resolves but is NOT in the enrolled allowlist → treat as stranger
    cap = CapturePipeline(orch, vad=_VAD(), asr=_ASR("hi"), speaker=_Emb(),
                          speaker_resolver=lambda e: "Priya",
                          enrolled_speakers=["Sam"])
    _drive(cap)
    assert cap.last_speaker_embedding is None
