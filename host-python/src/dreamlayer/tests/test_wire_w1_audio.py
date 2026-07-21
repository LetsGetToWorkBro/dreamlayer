"""W1 — the always-on ear, wired end to end.

Until this batch the capture seams (VAD, ASR, tagger, bird lens, interpreter)
existed but nothing drove them: no code opened a mic, pooled the world's sound,
or carried a foreign utterance across. These tests pin the glue:

  * CapturePipeline's ambient path pools NON-speech PCM and hands a window to
    the hub's `note_acoustic_context` (tags) and `note_ambient_audio` (raw).
  * A speech segment endpoints to `note_speech_audio` for the live interpreter.
  * The orchestrator turns tags → an attention hark (watch-outs first, per-key
    cooldown), a bird-lens read → a gentle hark, and a foreign segment → a
    spoken line — all Veil-gated.
  * The ASR ladder (`make_asr`) and lifecycle (`start/stop/status`) degrade
    honestly when no engine or mic is present.

Everything runs offline: no wheel, no mic, no model.
"""
from __future__ import annotations

from dreamlayer.orchestrator.capture import CapturePipeline, SyntheticMicSource
from dreamlayer.orchestrator.asr_select import make_asr, asr_engine_name
from dreamlayer.orchestrator.vad_gate import default_vad, SileroVADGate
from dreamlayer.orchestrator import sound_events
from dreamlayer.orchestrator.attention import Alert
from dreamlayer.tests.test_integration_dream_suite import FakeBridge


def _orc():
    from dreamlayer.orchestrator.orchestrator import Orchestrator
    return Orchestrator(FakeBridge())


def _cards(orc):
    return [c for c in orc.bridge.raw
            if isinstance(c, dict) and c.get("t") == "card"]


# ---- capture: the ambient (non-speech) path ------------------------------

class _Tagger:
    def __init__(self, tags):
        self.tags = tags
        self.seen = []

    def tag(self, audio, sample_rate=16000):
        self.seen.append(len(list(audio)))
        return self.tags


class _Priv:
    def __init__(self, ok=True):
        self.ok = ok

    def allow_capture(self):
        return self.ok


class _Hub:
    """A minimal duck-typed hub: records what the pipeline routes to it."""
    def __init__(self):
        self.privacy = _Priv()
        self.acoustic = []
        self.ambient = []
        self.speech = []
        self.heard = []
        self.captions = []

    def note_acoustic_context(self, tags):
        self.acoustic.append(tags)

    def note_ambient_audio(self, audio, sr):
        self.ambient.append((len(list(audio)), sr))

    def note_speech_audio(self, seg, sr):
        self.speech.append((len(list(seg)), sr))

    def hear(self, text):
        self.heard.append(text)

    def ingest_caption(self, text, speaker=""):
        self.captions.append((text, speaker))


def test_ambient_window_flushes_tags_and_raw_to_hub():
    hub = _Hub()
    tagger = _Tagger([("Doorbell", 0.8)])
    pipe = CapturePipeline(hub, tagger=tagger, bird=object(),
                           sample_rate=16000, ambient_window_ms=1000)
    # under a second of silence: pooled, not yet flushed
    pipe._accumulate_ambient([0.0] * 8000)
    assert hub.acoustic == [] and hub.ambient == []
    # crossing the window flushes once
    pipe._accumulate_ambient([0.0] * 8000)
    assert hub.acoustic == [[("Doorbell", 0.8)]]
    assert hub.ambient and hub.ambient[0][1] == 16000


def test_ambient_buffer_is_drop_oldest_capped():
    hub = _Hub()
    # no tagger AND no bird → ambient path is a no-op (nothing to pool for)
    pipe = CapturePipeline(hub, sample_rate=16000)
    pipe._accumulate_ambient([0.1] * 16000)
    assert pipe._ambient == []
    # with a bird lens, it pools but never grows past AMBIENT_MAX_MS
    from dreamlayer.orchestrator import capture as capmod
    pipe2 = CapturePipeline(hub, bird=object(), sample_rate=16000,
                            ambient_window_ms=99_000)  # never flushes here
    cap = int(16000 * capmod.AMBIENT_MAX_MS / 1000.0)
    pipe2._accumulate_ambient([0.1] * (cap * 3))
    assert len(pipe2._ambient) <= cap


def test_push_pcm_silence_feeds_ambient_path():
    hub = _Hub()
    tagger = _Tagger([("Kettle whistle", 0.7)])
    # VAD forced to "silence" so every window is ambient
    class _Silent:
        def is_speech(self, s):
            return False
    pipe = CapturePipeline(hub, vad=_Silent(), tagger=tagger,
                           sample_rate=16000, ambient_window_ms=500)
    for _ in range(4):
        pipe.push_pcm([0.0] * 4000)     # 4 × 250ms = 1s > 500ms window
    assert hub.acoustic and hub.acoustic[0] == [("Kettle whistle", 0.7)]


# ---- capture: the speech path → the interpreter seam ---------------------

class _ASR:
    def transcribe(self, seg):
        return "hola mundo"


def test_speech_segment_routes_to_interpreter_seam():
    hub = _Hub()
    pipe = CapturePipeline(hub, asr=_ASR())
    pipe._seg = [0.2] * 1600
    out = pipe._endpoint(now=1.0)
    assert out == "hola mundo"
    # the transcript went to hear()+caption AND the raw segment to note_speech_audio
    assert hub.heard == ["hola mundo"]
    assert hub.speech and hub.speech[0][0] == 1600


def test_speech_audio_seam_is_optional():
    # a hub without note_speech_audio must not break the endpoint
    class Bare:
        def __init__(self):
            self.heard = []
        def hear(self, t):
            self.heard.append(t)
        def ingest_caption(self, t, speaker=""):
            pass
    bare = Bare()
    pipe = CapturePipeline(bare, asr=_ASR())
    pipe._seg = [0.2] * 800
    assert pipe._endpoint(now=1.0) == "hola mundo"
    assert bare.heard == ["hola mundo"]


# ---- ASR ladder + VAD default --------------------------------------------

def test_make_asr_none_when_no_engine_installed():
    # neither Moonshine nor faster-whisper is present in CI
    assert make_asr() is None
    assert asr_engine_name(None) == "none"


def test_asr_engine_name_maps_known_classes():
    class MoonshineASR:
        pass
    class FasterWhisperASR:
        pass
    assert asr_engine_name(MoonshineASR()) == "moonshine"
    assert asr_engine_name(FasterWhisperASR()) == "faster-whisper"


def test_default_vad_always_non_none():
    vad = default_vad()
    assert isinstance(vad, SileroVADGate)
    # energy fallback gives a real decision even without silero
    assert vad.is_speech([0.5] * 1000) in (True, False)


def test_sound_detector_tag_alias_matches_detect():
    det = sound_events.SoundEventDetector()
    # no wheel/model → both are empty, but the alias must exist and agree
    assert det.tag([0.0] * 100) == det.detect([0.0] * 100)


# ---- orchestrator: tags → hark, bird → hark, cooldowns -------------------

def test_note_acoustic_context_harks_a_watchout():
    o = _orc()
    o.note_acoustic_context([("Smoke detector, smoke alarm", 0.9)])
    cards = _cards(o)
    assert len(cards) == 1
    assert cards[0]["importance"] == "urgent"
    assert "alarm" in cards[0]["primary"].lower()


def test_harken_orders_watchouts_before_listens():
    o = _orc()
    listen = Alert("listen", "Someone's at the door", "", "sound:door")
    watch = Alert("watchout", "Smoke alarm", "", "sound:smoke")
    card = o.harken([listen, watch])
    assert card is not None and card["importance"] == "urgent"


def test_harken_per_key_cooldown_suppresses_repeat():
    o = _orc()
    a = Alert("listen", "A dog barking", "", "sound:bark")
    assert o.harken(a, now=1000.0) is not None
    # same key inside the window: suppressed even though the sound persists
    assert o.harken(a, now=1000.0 + 100.0) is None
    # past the window: fires again
    assert o.harken(a, now=1000.0 + 400.0) is not None


def test_note_ambient_audio_builds_bird_lens_once():
    o = _orc()
    calls = {"n": 0}

    class _Lens:
        def listen(self, audio, sr):
            calls["n"] += 1
            return Alert("listen", "A goldfinch", "", "bird:goldfinch")
    # inject a fake lens and mark built so no wheel is needed
    o._bird_lens = _Lens()
    o._bird_built = True
    o.note_ambient_audio([0.0] * 16000, 16000)
    assert calls["n"] == 1
    assert any("goldfinch" in c["primary"].lower() for c in _cards(o))


def test_note_ambient_audio_no_lens_is_silent():
    o = _orc()
    o._bird_lens = None
    o._bird_built = True
    o.note_ambient_audio([0.0] * 16000, 16000)
    assert _cards(o) == []


def test_world_sound_hark_is_veil_gated():
    o = _orc()
    o.set_incognito(True)
    o.note_acoustic_context([("Fire alarm", 0.95)])
    assert _cards(o) == []


# ---- orchestrator: the live interpreter ----------------------------------

class _Rosetta:
    """Stand-in RosettaLens with a wired interpreter."""
    _interpret = object()

    def __init__(self, line):
        self.line = line
        self.calls = []

    def hear(self, audio, sample_rate=16000, target="en"):
        self.calls.append((len(list(audio)), sample_rate, target))
        from dreamlayer.rosetta import RosettaResult
        return RosettaResult("", self.line, "", target, engine="seam")


def test_interpreter_off_by_default_is_noop():
    o = _orc()
    o.rosetta = _Rosetta("hello friend")
    o.note_speech_audio([0.1] * 1600, 16000)
    assert _cards(o) == []


def test_set_interpret_then_speech_voices_the_meaning():
    o = _orc()
    o.rosetta = _Rosetta("hello friend")
    assert o.set_interpret(True, "en") is True     # _interpret is wired
    o.note_speech_audio([0.1] * 1600, 16000)
    cards = _cards(o)
    assert cards and any("hello friend" in c.get("primary", "") for c in cards)
    assert o.rosetta.calls and o.rosetta.calls[0][2] == "en"


def test_interpreter_veil_gated():
    o = _orc()
    o.rosetta = _Rosetta("secret")
    o.set_interpret(True, "en")
    o.set_incognito(True)
    o.note_speech_audio([0.1] * 1600, 16000)
    assert _cards(o) == []


def test_can_interpret_false_without_wire():
    o = _orc()
    class Bare:
        _interpret = None
    o.rosetta = Bare()
    assert o.set_interpret(True, "en") is False


# ---- lifecycle: start/stop/status ---------------------------------------

def test_start_listening_reports_no_asr():
    o = _orc()
    st = o.start_listening()
    assert st["ok"] is False and st["reason"] == "no-asr"
    assert o.listening_status()["listening"] is False


def test_start_listening_with_fake_engine_and_mic():
    o = _orc()
    mic = SyntheticMicSource(pcm=[0.0] * 320)

    class _Engine:
        def transcribe(self, seg):
            return ""
    # start_listening imports make_asr from asr_select inside the method;
    # patch it at the source module so the fake engine is chosen.
    import dreamlayer.orchestrator.asr_select as asrmod
    orig = asrmod.make_asr
    asrmod.make_asr = lambda *a, **k: _Engine()
    try:
        st = o.start_listening(mic=mic)
    finally:
        asrmod.make_asr = orig
    assert st["ok"] is True
    assert o.listening_status()["listening"] is True
    o.stop_listening()
    assert o.listening_status()["listening"] is False


def test_stop_listening_safe_when_idle():
    o = _orc()
    o.stop_listening()      # no-op, must not raise
    assert o.listening_status()["ok"] is False
