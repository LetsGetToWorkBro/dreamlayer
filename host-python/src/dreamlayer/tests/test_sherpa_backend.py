"""sherpa-onnx unified backend: degradation contract + adapter mapping.

No model download and no sherpa wheel required — absence degrades to the same
empty/fallback results the pure-Python seams return, and fake model handles
exercise the mapping logic deterministically.
"""
import pytest

np = pytest.importorskip("numpy")

from dreamlayer.orchestrator.sherpa_backend import (   # noqa: E402
    SherpaConfig, SherpaSpeech, SherpaASR, SherpaVAD, SherpaSpeakerEmbedding,
    SherpaWakeWord, SherpaDiarizer, SherpaAudioTagger, _Loaded,
)

CFG = SherpaConfig()
PCM = [0.0, 0.1, -0.1, 0.2] * 64


# ---- degradation contract (no impl wired) --------------------------------

class TestDegradesWhenAbsent:
    def test_asr_returns_empty(self):
        assert SherpaASR(CFG).transcribe(PCM) == ""

    def test_vad_never_drops_audio(self):
        assert SherpaVAD(CFG).is_speech(PCM) is True

    def test_speaker_returns_empty(self):
        assert SherpaSpeakerEmbedding(CFG).embed(PCM) == []

    def test_wake_no_hit(self):
        assert SherpaWakeWord(CFG).detect(PCM) == (False, 0.0)

    def test_diarize_empty(self):
        assert SherpaDiarizer(CFG).diarize(PCM) == []

    def test_tag_empty(self):
        assert SherpaAudioTagger(CFG).tag(PCM) == []

    def test_speech_factory_builds_all_six_adapters(self):
        s = SherpaSpeech(CFG)            # no wheel → all adapters degrade
        for a in (s.asr, s.vad, s.speaker, s.wake, s.diarizer, s.tagger):
            assert a is not None

    def test_similarity_is_cosine(self):
        sim = SherpaSpeakerEmbedding.similarity
        assert sim([1, 0], [1, 0]) == pytest.approx(1.0)
        assert sim([1, 0], [0, 1]) == pytest.approx(0.0)
        assert sim([], [1]) == 0.0


# ---- fake model handles: verify the adapter mapping ----------------------

class _Stream:
    def __init__(self):
        self.result = type("R", (), {"text": "", "keyword": ""})()
        self.got = None
    def accept_waveform(self, rate, samples): self.got = (rate, len(samples))
    def input_finished(self): pass


class _FakeASR:
    def create_stream(self): return _Stream()
    def decode_stream(self, st): st.result.text = "hello world"


class _FakeVAD:
    def __init__(self, speech): self._speech = speech; self.reset_called = False
    def accept_waveform(self, s): pass
    def is_speech(self): return self._speech
    def empty(self): return True
    def reset(self): self.reset_called = True


class _FakeSpeaker:
    def create_stream(self): return _Stream()
    def compute(self, st): return np.array([0.5, 0.25, 0.75], dtype="float32")


class _FakeKWS:
    def __init__(self): self._fired = False
    def create_stream(self): return _Stream()
    def accept_waveform(self, *a): pass
    def is_ready(self, st):
        if not self._fired:
            self._fired = True
            st.result.keyword = "hey juno"
            return True
        return False
    def decode_stream(self, st): pass


class _Seg:
    def __init__(self, s, e, spk): self.start, self.end, self.speaker = s, e, spk


class _DiarResult:
    def __init__(self, segs): self._segs = segs
    def sort_by_start_time(self): return sorted(self._segs, key=lambda x: x.start)


class _FakeDiar:
    def process(self, audio):
        return _DiarResult([_Seg(1.0, 2.0, 1), _Seg(0.0, 1.0, 0)])


class _Ev:
    def __init__(self, name, prob): self.name, self.prob = name, prob


class _FakeTagger:
    def create_stream(self): return _Stream()
    def compute(self, st, top_k=3):
        return [_Ev("Doorbell", 0.9), _Ev("Speech", 0.4)][:top_k]


class TestAdapterMapping:
    def test_asr_maps_result_text(self):
        assert SherpaASR(CFG, _impl=_FakeASR()).transcribe(PCM) == "hello world"

    def test_vad_reads_is_speech(self):
        assert SherpaVAD(CFG, _impl=_FakeVAD(True)).is_speech(PCM) is True
        assert SherpaVAD(CFG, _impl=_FakeVAD(False)).is_speech(PCM) is False

    def test_speaker_maps_vector(self):
        v = SherpaSpeakerEmbedding(CFG, _impl=_FakeSpeaker()).embed(PCM)
        assert v == [0.5, 0.25, 0.75] and all(isinstance(x, float) for x in v)

    def test_wake_detects_keyword(self):
        hit, score = SherpaWakeWord(CFG, _impl=_FakeKWS()).detect(PCM)
        assert hit is True and score == 1.0

    def test_diarize_sorts_and_maps(self):
        out = SherpaDiarizer(CFG, _impl=_FakeDiar()).diarize(PCM)
        assert out == [(0.0, 1.0, 0), (1.0, 2.0, 1)]

    def test_tag_maps_topk_events(self):
        CFG2 = SherpaConfig(tag_top_k=1)
        out = SherpaAudioTagger(CFG2, _impl=_FakeTagger()).tag(PCM)
        assert out == [("Doorbell", 0.9)]

    def test_speech_from_fake_wires_every_adapter(self):
        loaded = _Loaded(asr=_FakeASR(), vad=_FakeVAD(True),
                         speaker=_FakeSpeaker(), wake=_FakeKWS(),
                         diarizer=_FakeDiar(), tagger=_FakeTagger())
        s = SherpaSpeech(CFG, _fake=loaded)
        assert s.available is True
        assert s.asr.transcribe(PCM) == "hello world"
        assert s.wake.detect(PCM)[0] is True
        assert s.tagger.tag(PCM)[0][0] == "Doorbell"


# ---- capture pipeline routes acoustic context ----------------------------

class _Privacy:
    def allow_capture(self): return True


class _Orch:
    def __init__(self): self.privacy = _Privacy(); self.heard = []; self.ctx = []
    def hear(self, t): self.heard.append(t)
    def ingest_caption(self, t, speaker=""): pass
    def note_acoustic_context(self, tags): self.ctx.append(tags)


class TestCaptureAcousticContext:
    def test_tagger_routes_to_hub(self):
        from dreamlayer.orchestrator.capture import CapturePipeline

        class _ASR:
            def transcribe(self, seg, language="en"): return "someone knocked"

        orch = _Orch()
        cap = CapturePipeline(orch, asr=_ASR(),
                              tagger=SherpaAudioTagger(SherpaConfig(),
                                                       _impl=_FakeTagger()))
        cap.push_pcm(PCM)
        cap.flush()
        assert cap.last_acoustic[0][0] == "Doorbell"
        assert orch.ctx and orch.ctx[-1][0][0] == "Doorbell"

    def test_no_tagger_is_a_noop(self):
        from dreamlayer.orchestrator.capture import CapturePipeline

        class _ASR:
            def transcribe(self, seg, language="en"): return "hi"

        orch = _Orch()
        cap = CapturePipeline(orch, asr=_ASR())
        cap.push_pcm(PCM); cap.flush()
        assert cap.last_acoustic == [] and orch.ctx == []
