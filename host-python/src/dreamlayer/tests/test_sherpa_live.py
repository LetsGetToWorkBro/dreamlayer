"""test_sherpa_live.py — one ONNX engine under every voice seam.

`orchestrator/sherpa_backend.py` was a complete six-adapter wrapper around
sherpa-onnx with no caller. The report's reading of it was subtler than the
usual case: `onnx_speech` sits in `EAR_CAPS`, so it LOOKED driven — while
`ear.py`'s own comment said *"make_asr picks Moonshine XOR faster-whisper
(never sherpa/onnx), so onnx_speech is never on the ear's path"*. `EAR_CAPS` is
the set the ear FILTERS against, not the set it claims. The ear was honest; the
capability simply had no rung.

The sharp edge here is that EVERY adapter degrades to a null rather than to an
error, and one of those nulls is `True`: `SherpaVAD.is_speech` with no model
answers "yes, speech" to everything, which is the seam rule (no gate means do
not drop audio) and would silently disable voice detection for a whole session
if it were handed to the pipeline as an engine. Most of what follows is about
never letting a null wear an engine's contract.

sherpa-onnx is absent in CI, so the model handles are fakes. That is deliberate
rather than a compromise: what needs proving is which rung is offered, which is
withheld, and what counts as an answer — none of which is sherpa's behaviour.
"""
from __future__ import annotations

import tempfile

import pytest

from dreamlayer.ai_brain.server.ear import EarHost
from dreamlayer.ai_brain.server.server import Brain
from dreamlayer.ai_brain.server.sherpa_live import (
    ENV_DIR, LAYOUT, SherpaStack, build_config, stack)
from dreamlayer.orchestrator.sherpa_backend import SherpaConfig, SherpaSpeech


@pytest.fixture
def brain():
    return Brain(tempfile.mkdtemp())


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv(ENV_DIR, raising=False)


class _FakeASR:
    def __init__(self, text="the deposit clears Friday"):
        self.text = text

    def create_stream(self):
        return self

    def accept_waveform(self, rate, audio):
        pass

    def decode_stream(self, stream):
        pass

    @property
    def result(self):
        return type("R", (), {"text": self.text})()


def _speech(**loaded) -> SherpaSpeech:
    """A `SherpaSpeech` whose handles are exactly the ones named."""
    from dreamlayer.orchestrator.sherpa_backend import _Loaded
    return SherpaSpeech(SherpaConfig(), _fake=_Loaded(**loaded))


def _dir_with(tmp_path, *groups):
    d = tmp_path / "models"
    d.mkdir(exist_ok=True)
    for g in groups:
        for f in LAYOUT[g]:
            (d / f).write_bytes(b"x")
    return str(d)


class TestANullNeverWearsAnEnginesContract:
    """The trap this whole module exists to avoid."""

    def test_an_unloaded_adapter_is_not_offered(self, brain):
        s = SherpaStack(brain, _stack=_speech())      # nothing loaded
        assert s.asr() is None
        assert s.vad() is None
        assert s.wake() is None
        assert s.tagger() is None
        assert s.offers() == []

    def test_the_vad_null_is_the_dangerous_one(self, brain):
        """`SherpaVAD.is_speech` with no model returns TRUE — the seam rule
        (no gate, do not drop audio) — so handing it over as an engine would
        turn voice detection off for the session while every status surface
        reported a VAD running."""
        bare = _speech().vad
        assert bare.is_speech([0.0] * 100) is True
        assert SherpaStack(brain, _stack=_speech()).vad() is None

    def test_a_loaded_adapter_is_offered(self, brain):
        s = SherpaStack(brain, _stack=_speech(asr=_FakeASR()))
        assert s.asr() is not None
        assert s.offers() == ["asr"]

    def test_each_rung_is_independent(self, brain):
        s = SherpaStack(brain, _stack=_speech(asr=_FakeASR(), vad=object()))
        assert sorted(s.offers()) == ["asr", "vad"]
        assert s.wake() is None


class TestWhatCountsAsAnAnswer:
    """The promotion proof. Every adapter has a null it returns forever with no
    model, so counting calls — or counting nulls — would put us straight back
    at "the wheel is installed"."""

    def test_a_transcript_counts(self, brain):
        s = SherpaStack(brain, _stack=_speech(asr=_FakeASR()))
        assert s.driving() is False
        assert s.asr().transcribe([0.1] * 100)
        assert s.outputs == 1
        assert s.driving() is True

    def test_an_empty_transcript_does_not(self, brain):
        s = SherpaStack(brain, _stack=_speech(asr=_FakeASR(text="")))
        s.asr().transcribe([0.1] * 100)
        assert s.outputs == 0
        assert s.driving() is False

    def test_a_wake_miss_does_not_count(self, brain):
        class _KWS:
            def create_stream(self):
                return object()

            def is_ready(self, st):
                return False

        s = SherpaStack(brain, _stack=_speech(wake=_KWS()))
        assert s.wake().detect([0.1] * 100) == (False, 0.0)
        assert s.outputs == 0

    def test_a_negative_vad_verdict_is_the_proof_not_a_positive_one(self,
                                                                   brain):
        """`is_speech` returning True is BOTH a real verdict and the null, so
        only False is unambiguous evidence a model ran. Under-counting here is
        the correct direction: a silent room proves the gate; a loud one cannot
        tell you anything."""
        class _V:
            def __init__(self, verdict):
                self.verdict = verdict

            def accept_waveform(self, a):
                pass

            def is_speech(self):
                return self.verdict

        yes = SherpaStack(brain, _stack=_speech(vad=_V(True)))
        yes.vad().is_speech([0.1] * 100)
        assert yes.outputs == 0

        no = SherpaStack(brain, _stack=_speech(vad=_V(False)))
        no.vad().is_speech([0.0] * 100)
        assert no.outputs == 1


class TestTheWrapperDoesNotBreakTheSeamContract:
    def test_the_taggers_signature_survives_wrapping(self, brain):
        """`CapturePipeline._tag` probes the tagger's SIGNATURE to decide
        whether to pass `sample_rate=` — written precisely because
        `SherpaAudioTagger.tag` does not take one. A bare `(*a, **kw)` wrapper
        advertises `**kwargs`, so the probe would start passing an argument the
        real method rejects."""
        import inspect

        class _T:
            def create_stream(self):
                return self

            def accept_waveform(self, rate, audio):
                pass

            def compute(self, stream, top_k=3):
                return [type("E", (), {"name": "doorbell", "prob": 0.9})()]

        tagger = SherpaStack(brain, _stack=_speech(tagger=_T())).tagger()
        params = inspect.signature(tagger.tag).parameters
        assert "sample_rate" not in params
        assert not any(p.kind is inspect.Parameter.VAR_KEYWORD
                       for p in params.values()), (
            "the wrapper advertises **kwargs, so the pipeline will pass "
            "sample_rate= to a method that rejects it")

    def test_the_pipeline_tags_through_the_wrapper(self, brain):
        """End to end, because the signature assertion above is a proxy for
        this and a proxy is not the thing."""
        from dreamlayer.orchestrator.capture import CapturePipeline

        class _T:
            def create_stream(self):
                return self

            def accept_waveform(self, rate, audio):
                pass

            def compute(self, stream, top_k=3):
                return [type("E", (), {"name": "doorbell", "prob": 0.9})()]

        s = SherpaStack(brain, _stack=_speech(tagger=_T()))

        class _Hub:
            def __init__(self):
                self.tags = []

            def hear(self, text, addressed=None):
                pass

            def ingest_caption(self, text, speaker=None):
                pass

            def note_acoustic_context(self, tags):
                self.tags.append(tags)

        hub = _Hub()
        p = CapturePipeline(hub, tagger=s.tagger())
        p._acoustic_context([0.1] * 100)
        assert hub.tags == [[("doorbell", 0.9)]]
        assert s.outputs == 1


class TestTheModelDirectory:
    def test_nothing_configured_is_not_a_fault(self, brain):
        s = SherpaStack(brain)
        assert s.stack() is None
        assert s.offers() == []
        assert s.status()["configured"] is False

    def test_the_config_field_beats_the_environment(self, brain, monkeypatch,
                                                    tmp_path):
        """`dream_model_path` was added for exactly this reason: the bundled
        .app has no environment of its own to edit, so an env-only switch is
        one no shipped surface can reach."""
        monkeypatch.setenv(ENV_DIR, str(tmp_path / "from-env"))
        brain.config.sherpa_model_dir = _dir_with(tmp_path, "vad")
        cfg = build_config(brain.config.sherpa_model_dir)
        assert cfg.vad_model
        from dreamlayer.ai_brain.server.sherpa_live import _dir
        assert _dir(brain) == brain.config.sherpa_model_dir

    def test_the_environment_still_works_when_no_field_is_set(self, brain,
                                                              monkeypatch,
                                                              tmp_path):
        monkeypatch.setenv(ENV_DIR, str(tmp_path / "m"))
        from dreamlayer.ai_brain.server.sherpa_live import _dir
        assert _dir(brain) == str(tmp_path / "m")

    def test_a_partial_export_disables_only_its_own_rung(self, tmp_path):
        """Never half-loads one — the rule `find_moonshine_dir` already holds
        for the Moonshine export."""
        root = _dir_with(tmp_path, "vad")
        (tmp_path / "models" / "tokens.txt").write_bytes(b"x")   # ASR, partial
        cfg = build_config(root)
        assert cfg.vad_model
        assert cfg.asr_tokens is None, "a half-complete ASR export was loaded"

    @pytest.mark.parametrize("group", sorted(LAYOUT))
    def test_a_complete_group_populates_its_fields(self, tmp_path, group):
        cfg = build_config(_dir_with(tmp_path, group))
        fields = {"asr": "asr_tokens", "vad": "vad_model",
                  "speaker": "speaker_model", "kws": "kws_tokens",
                  "tag": "tag_model"}
        assert getattr(cfg, fields[group]) is not None

    def test_a_missing_directory_is_not_a_crash(self, brain, tmp_path):
        brain.config.sherpa_model_dir = str(tmp_path / "nope")
        assert SherpaStack(brain).offers() == []


class TestTheEarActuallyReachesEachRung:
    """Asserted by RUNNING `EarHost.start()` and reading what the pipeline was
    built WITH — not by checking the ladder's neighbours.

    Written this way because a mutation survived: deleting the VAD rung from
    the ear outright changed nothing any test could see. The tests around it
    asserted that `default_vad()` is non-None and that `_model` exists, which
    are facts about the fallback, not about the wiring. Same shape as the
    capabilities themselves — the thing that needs proving is the LINK.
    """

    def _pipe(self, brain, monkeypatch, *, has_asr=True, has_silero=True,
              has_oww=True, has_tagger=True, **loaded):
        """Start an ear with the named dedicated engines present/absent and a
        sherpa stack holding `loaded`. Returns the CapturePipeline built.

        The `has_*` flags are the DEDICATED engines; `**loaded` is what the
        sherpa export contains. Two different namespaces on purpose — naming
        both `asr` is how the first draft collided with itself."""
        import dreamlayer.orchestrator.asr_select as sel
        import dreamlayer.orchestrator.sound_events as se
        import dreamlayer.orchestrator.vad_gate as vg
        import dreamlayer.orchestrator.wakeword as ww

        monkeypatch.setattr(sel, "make_asr",
                            lambda *a, **k: object() if has_asr else None)
        monkeypatch.setattr(vg, "default_vad",
                            lambda *a, **k: _Gate(loaded_model=has_silero))
        monkeypatch.setattr(ww, "OpenWakeWordEngine",
                            (lambda: _Spot(True)) if has_oww else (lambda: _Spot(False)))
        monkeypatch.setattr(se, "default_sound_detector",
                            lambda: _Tagger(has_tagger) if has_tagger else None)

        ear = EarHost(brain)
        brain._sherpa_stack = SherpaStack(brain, _stack=_speech(**loaded))
        from dreamlayer.orchestrator.capture import SyntheticMicSource
        assert ear.start(mic=SyntheticMicSource(windows=[]))["ok"]
        return ear._pipe

    def test_the_asr_rung_is_reached_when_no_engine_is_installed(
            self, brain, monkeypatch):
        p = self._pipe(brain, monkeypatch, has_asr=False,
                       **{"asr": _FakeASR()})
        assert p.asr is not None
        assert p.asr.transcribe([0.1] * 100) == "the deposit clears Friday"

    def test_the_asr_rung_does_not_displace_a_live_engine(self, brain,
                                                          monkeypatch):
        p = self._pipe(brain, monkeypatch, has_asr=True, **{"asr": _FakeASR()})
        assert p.asr.__class__ is object, (
            "the sherpa rung displaced a working ASR engine")

    def test_the_vad_rung_is_reached_when_silero_did_not_load(self, brain,
                                                              monkeypatch):
        """The one the mutation walked through. `default_vad()` is NEVER None —
        with silero absent it returns a gate running the energy heuristic — so
        the condition has to read `_model`, and `default_vad() or …` would have
        made this rung unreachable forever."""
        v = _V(False)
        p = self._pipe(brain, monkeypatch, has_silero=False, vad=v)
        assert p.vad.is_speech([0.0] * 100) is False
        assert getattr(p.vad, "_impl", None) is v, (
            "the pipeline got the energy fallback, not the sherpa gate")

    def test_the_vad_rung_does_not_displace_a_loaded_silero(self, brain,
                                                            monkeypatch):
        p = self._pipe(brain, monkeypatch, has_silero=True, vad=_V(False))
        assert isinstance(p.vad, _Gate), "sherpa took a loaded Silero's place"

    def test_the_wake_rung_is_reached_when_openwakeword_is_absent(
            self, brain, monkeypatch):
        p = self._pipe(brain, monkeypatch, has_oww=False, wake=_KWSHit())
        assert p.wake is not None
        assert p.wake.detect([0.1] * 100)[0] is True

    def test_the_wake_rung_does_not_displace_openwakeword(self, brain,
                                                          monkeypatch):
        p = self._pipe(brain, monkeypatch, has_oww=True, wake=_KWSHit())
        assert isinstance(p.wake, _Spot)

    def test_the_tagger_rung_is_reached_when_no_tagger_is_ready(
            self, brain, monkeypatch):
        """`SoundEventDetector` has its own sherpa rung, but it reads a SECOND
        directory ($DL_AUDIO_TAG_DIR) and env-only, which the bundled .app
        cannot set. One configured export should cover tagging too."""
        p = self._pipe(brain, monkeypatch, has_tagger=False,
                       **{"tagger": _T()})
        assert p.tagger is not None
        assert p.tagger.tag([0.1] * 100) == [("doorbell", 0.9)]

    def test_the_tagger_rung_is_reached_when_the_tagger_has_no_model(
            self, brain, monkeypatch):
        """`available` is the WHEEL and `ready` is a MODEL — the distinction
        `ear.py` already draws for `sound_events`. A tagger that is not ready
        returns [] forever."""
        p = self._pipe(brain, monkeypatch, has_tagger="not-ready",
                       **{"tagger": _T()})
        assert p.tagger.tag([0.1] * 100) == [("doorbell", 0.9)]

    def test_the_tagger_rung_does_not_displace_a_ready_one(self, brain,
                                                           monkeypatch):
        p = self._pipe(brain, monkeypatch, has_tagger=True, **{"tagger": _T()})
        assert isinstance(p.tagger, _Tagger)

    def test_nothing_configured_leaves_every_ladder_alone(self, brain,
                                                          monkeypatch):
        p = self._pipe(brain, monkeypatch)              # empty sherpa stack
        assert isinstance(p.vad, _Gate)
        assert isinstance(p.wake, _Spot)
        assert isinstance(p.tagger, _Tagger)


class _Gate:
    """Stands in for `SileroVADGate`. `_model` is the loaded-or-not bit the
    ear's rung condition reads."""

    def __init__(self, loaded_model=True):
        self._model = object() if loaded_model else None

    def is_speech(self, samples):
        return True


class _Spot:
    def __init__(self, loaded=True):
        self._model = object() if loaded else None

    def detect(self, samples):
        return (False, 0.0)


class _Tagger:
    def __init__(self, ready=True):
        self.ready = ready is True
        self.available = True

    def tag(self, audio, sample_rate=16000):
        return []


class _V:
    def __init__(self, verdict):
        self.verdict = verdict

    def accept_waveform(self, a):
        pass

    def is_speech(self):
        return self.verdict


class _KWSHit:
    def __init__(self):
        self._n = 0

    def create_stream(self):
        return self

    def accept_waveform(self, rate, audio):
        self._n = 1

    def is_ready(self, st):
        got, self._n = self._n, 0
        return bool(got)

    def decode_stream(self, st):
        pass

    @property
    def result(self):
        return type("R", (), {"keyword": "hey juno"})()


class _T:
    def create_stream(self):
        return self

    def accept_waveform(self, rate, audio):
        pass

    def compute(self, stream, top_k=3):
        return [type("E", (), {"name": "doorbell", "prob": 0.9})()]


class TestThePromotionIsAskedOfTheBrain:
    def _env(self, brain, monkeypatch) -> dict:
        import dreamlayer.capabilities as caps
        seen = {}
        real = caps.report

        def _spy(env=None, **kw):
            seen.update(env or {})
            return real(env=env, **kw)
        monkeypatch.setattr(caps, "report", _spy)
        from dreamlayer.ai_brain.server.server import _capability_payload
        _capability_payload(brain)
        return seen

    def test_a_brain_with_no_engine_is_not_promoted(self, brain, monkeypatch):
        import os
        monkeypatch.delenv("DL_WIRED_ONNX_SPEECH", raising=False)
        brain._sync_ear_wired()
        assert "DL_WIRED_ONNX_SPEECH" not in os.environ

    def test_a_produced_answer_promotes_it(self, brain, monkeypatch):
        import os
        monkeypatch.delenv("DL_WIRED_ONNX_SPEECH", raising=False)
        s = SherpaStack(brain, _stack=_speech(asr=_FakeASR()))
        brain._sherpa_stack = s
        brain._sync_ear_wired()
        assert "DL_WIRED_ONNX_SPEECH" not in os.environ, (
            "a loaded model promoted the capability before it answered")
        s.asr().transcribe([0.1] * 100)
        brain._sync_ear_wired()
        assert os.environ.get("DL_WIRED_ONNX_SPEECH") == "1"

    def test_it_is_not_tied_to_an_open_microphone(self, brain, monkeypatch):
        """One engine backs up to four seams and both ears share it, so asking
        per-ear would double it and tie it to whichever ear happened to open."""
        import os
        monkeypatch.delenv("DL_WIRED_ONNX_SPEECH", raising=False)
        s = SherpaStack(brain, _stack=_speech(asr=_FakeASR()))
        brain._sherpa_stack = s
        s.asr().transcribe([0.1] * 100)
        assert brain._ear is None and brain._remote_ear is None
        brain._sync_ear_wired()
        assert os.environ.get("DL_WIRED_ONNX_SPEECH") == "1"

    def test_the_stack_is_built_once_and_held(self, brain):
        assert stack(brain) is stack(brain)


class TestTheSpeakerRungIsWithheldOnPurpose:
    """The one rung left unwired, and not for lack of effort."""

    def test_it_is_loadable(self, brain):
        s = SherpaStack(brain, _stack=_speech(speaker=object()))
        assert s.speaker() is not None

    def test_it_is_not_in_the_offered_set(self, brain):
        """A voiceprint only means something against prints from the SAME
        model. ECAPA and sherpa embeddings are vectors in unrelated spaces and
        `voice_guard`'s cosine would compare them anyway — so wiring this would
        silently stop matching everyone a wearer had enrolled, or match the
        wrong person at a threshold tuned for a different model."""
        s = SherpaStack(brain, _stack=_speech(speaker=object()))
        assert "speaker" not in SherpaStack.RUNGS
        assert s.offers() == []

    def test_nothing_in_the_ear_consumes_it(self):
        import pathlib

        from dreamlayer.ai_brain.server import ear
        src = pathlib.Path(ear.__file__).read_text(encoding="utf-8")
        assert "_sherpa().speaker()" not in src
