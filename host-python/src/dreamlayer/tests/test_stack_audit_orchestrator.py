"""Full-stack audit, orchestrator slice — regressions for confirmed findings.

Every test here was written to FAIL against the code as it stood before the
matching fix, and each pins a defect that the 4400-test suite was green over.
The through-line is that none of these were crashes: they were an engine that
returned "" instead of a transcript, a rate limiter that muted a smoke alarm, a
bid three hundredths below a floor, and a veil that cleared one of its two
buffers. Silent wrongness is the failure mode this file exists to catch.
"""
from __future__ import annotations

import numpy as np
import pytest

from dreamlayer.orchestrator import glance as gl
from dreamlayer.orchestrator._ops_helpers import _parse_scene_reply
from dreamlayer.orchestrator.capture import AMBIENT_MAX_MS, CapturePipeline


# --------------------------------------------------------------------------
# B1 — the faster-whisper rung must accept what the pipeline actually produces
# --------------------------------------------------------------------------

class _RecordingModel:
    """Stands in for WhisperModel, recording the shape it was handed."""

    def __init__(self):
        self.seen = None

    def transcribe(self, audio, language="en"):
        self.seen = audio
        if not isinstance(audio, np.ndarray):
            # This is what faster_whisper.decode_audio really does with a list:
            # `av.open(list)` -> ValueError: File object has no read() method.
            raise ValueError("File object has no read() method")

        class _Seg:
            text = "hola mundo"
        return [_Seg()], None


def _fw_with(model):
    from dreamlayer.orchestrator.asr_faster_whisper import FasterWhisperASR
    asr = FasterWhisperASR.__new__(FasterWhisperASR)
    asr._model = model
    asr.last_error = None
    return asr


def test_faster_whisper_accepts_the_plain_list_the_pipeline_accumulates():
    # CapturePipeline._endpoint extends a plain list from the mic sources, both
    # of which return lists. Before the fix this reached WhisperModel untouched
    # and every window died in decode_audio -> the ear transcribed nothing.
    model = _RecordingModel()
    assert _fw_with(model).transcribe([0.05] * 1600) == "hola mundo"
    assert isinstance(model.seen, np.ndarray)
    assert model.seen.dtype == np.float32


def test_faster_whisper_coerces_int16_stereo_at_a_foreign_rate():
    model = _RecordingModel()
    stereo = np.zeros((4410, 2), dtype=np.int16)
    _fw_with(model).transcribe(stereo, sample_rate=44100)
    assert model.seen.ndim == 1                      # mono
    assert model.seen.dtype == np.float32
    assert abs(model.seen.size - 1600) <= 2          # resampled 44.1k -> 16k


def test_faster_whisper_still_passes_a_path_through_untouched():
    model = _RecordingModel()
    asr = _fw_with(model)
    # A bad path must not raise (callers rely on "no transcript = no-op") but it
    # must be visible on last_error rather than looking like silence.
    assert asr.transcribe("some.wav") == ""
    assert model.seen == "some.wav"                  # str reaches the model as-is
    assert isinstance(asr.last_error, ValueError)


def test_a_swallowed_asr_error_reaches_the_health_ledger():
    """An engine that logs its failure and returns "" is indistinguishable from
    silence. That is exactly how the broken rung stayed invisible."""
    class _Health:
        def __init__(self):
            self.failures = []

        def record_failure(self, seam, exc):
            self.failures.append((seam, exc))

    class _Hub:
        pass

    hub, health = _Hub(), _Health()
    hub.health = health

    class _Broken:
        last_error = None

        def transcribe(self, seg):
            self.last_error = RuntimeError("model exploded")
            return ""

    pipe = CapturePipeline(hub, asr=_Broken(), sample_rate=16000)
    pipe._seg = [0.2] * 800
    assert pipe._endpoint(now=1.0) is None
    assert [s for s, _ in health.failures] == ["asr"]


# --------------------------------------------------------------------------
# B2 — the world-sound tagger is told the pipeline's real sample rate
# --------------------------------------------------------------------------

class _RateSpy:
    """A tagger with SoundEventDetector's signature, recording the rate."""

    def __init__(self):
        self.rates = []

    def tag(self, audio, sample_rate: int = 32000):
        self.rates.append(sample_rate)
        return [("Doorbell", 0.9)]


class _NoRateTagger:
    """SherpaAudioTagger's signature: it reads its own config, takes no rate."""

    def __init__(self):
        self.calls = 0

    def tag(self, audio):
        self.calls += 1
        return []


def test_the_tagger_is_told_the_pipeline_sample_rate_not_its_own_default():
    # 32000 was PANNs' native rate and the parameter default, so a one-argument
    # call presented every sound an octave up and 2x time-compressed -- on the
    # input to the watch-out map and to the one hark allowed to pierce the Veil.
    spy = _RateSpy()

    class _Hub:
        def note_acoustic_context(self, tags):
            pass

    pipe = CapturePipeline(_Hub(), tagger=spy, sample_rate=16000,
                           ambient_window_ms=100)
    pipe._seg = [0.2] * 400
    pipe._acoustic_context([0.2] * 400)
    pipe._accumulate_ambient([0.0] * 3200)
    assert spy.rates, "the tagger was never called"
    assert set(spy.rates) == {16000}


def test_a_tagger_without_a_rate_parameter_is_still_called_correctly():
    plain = _NoRateTagger()

    class _Hub:
        pass

    pipe = CapturePipeline(_Hub(), tagger=plain, sample_rate=16000)
    pipe._acoustic_context([0.2] * 400)
    assert plain.calls == 1


# --------------------------------------------------------------------------
# B11 / B15 — the Veil clears BOTH pools; a big window does not disable the path
# --------------------------------------------------------------------------

class _VeiledHub:
    class privacy:
        @staticmethod
        def allow_capture():
            return False


def test_the_veil_drops_the_ambient_pool_not_just_the_speech_segment():
    # `_ambient` is the other accumulation of the wearer's surroundings, up to
    # AMBIENT_MAX_MS of it, and the bird lens writes its buffer to a temp WAV.
    pipe = CapturePipeline(_VeiledHub(), bird=object(), sample_rate=16000,
                           ambient_window_ms=6000)
    pipe._seg = [0.3] * 4000
    pipe._ambient = [0.3] * 92800                     # 5.8 s of pre-veil audio
    assert pipe.push_pcm([0.0] * 320, ts=1.0) is None
    assert pipe._seg == []
    assert pipe._ambient == []


def test_an_oversized_ambient_window_still_flushes():
    # The drop-oldest cap is the RAM bound; comparing against an UNCLAMPED
    # window made the trigger unreachable, so the whole world-sound path went
    # quietly dead instead of the window being clamped.
    flushed = []

    class _Hub:
        def note_ambient_audio(self, buf, sr):
            flushed.append(len(buf))

    pipe = CapturePipeline(_Hub(), bird=object(), sample_rate=16000,
                           ambient_window_ms=AMBIENT_MAX_MS * 4)
    for _ in range(400):                              # 8 s of audio, 20 ms each
        pipe._accumulate_ambient([0.0] * 320)
    assert flushed, "an oversized window silenced the world-sound path"
    cap = int(16000 * AMBIENT_MAX_MS / 1000.0)
    assert len(pipe._ambient) <= cap                  # the bound still holds


# --------------------------------------------------------------------------
# B9 — the fallback owner for a bare look at text must clear the floor
# --------------------------------------------------------------------------

def test_a_bare_look_at_sparse_text_resolves_to_someone():
    arb = gl.GlanceArbiter(gl.DEFAULT_CANDIDATES)
    for density in (0.12, 0.30, 0.45):
        reading = gl.classify_coarse({"text_density": density})
        d = arb.arbitrate(reading, gl.GlanceContext(dwell_ms=0))
        assert d.kind != "none", (
            f"density={density} scene={reading.scene} left the look with no owner")


def test_the_juno_fallback_bid_clears_the_arbiter_floor():
    arb = gl.GlanceArbiter(gl.DEFAULT_CANDIDATES)
    juno = next(c for c in gl.DEFAULT_CANDIDATES
                if getattr(c, "lens", "") == "juno")
    bid = juno.bid(gl.GlanceReading("text", 0.4, {"text_density": 0.3}),
                   gl.GlanceContext())
    assert bid is not None and bid.salience >= arb.floor


# --------------------------------------------------------------------------
# B10 — an explicit question= tag beats a stray question mark
# --------------------------------------------------------------------------

@pytest.mark.parametrize("reply", [
    "SCENE: text - density=0.7 lang=en fields=0 items=0 question=no. Anything else?",
    "SCENE: text - dense legal text, no question=no (are you sure?)",
    "SCENE: text - density=0.7 question=false? ",
])
def test_an_explicit_question_no_is_not_overridden_by_a_stray_mark(reply):
    reading = _parse_scene_reply(reply)
    assert reading.signals.get("question") is False
    assert reading.scene != "question"


def test_a_bare_question_mark_still_counts_when_the_tag_is_absent():
    reading = _parse_scene_reply("SCENE: text - density=0.7. What is this?")
    assert reading.signals.get("question") is True


def test_unknown_field_counts_written_as_marks_do_not_invent_a_question():
    reading = _parse_scene_reply("SCENE: text density=0.7 fields=? items=? question=no")
    assert reading.signals.get("question") is False


# --------------------------------------------------------------------------
# B14 — reinforce_at normalises `amount` away, exactly as reinforce does
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# B3 — a chatty hark must not be able to mute a safety hark
# --------------------------------------------------------------------------

def _hub():
    from dreamlayer.orchestrator.orchestrator import Orchestrator
    from dreamlayer.tests.test_integration_dream_suite import FakeBridge
    return Orchestrator(FakeBridge())


def test_a_dog_bark_cannot_silence_a_smoke_alarm():
    # The global 120 s cooldown was applied before and independently of
    # `importance`, so urgent pierced Focus but not the rate limiter -- the one
    # hark documented to break through for safety was the one birdsong blocked.
    for t in (30.0, 60.0, 119.0):
        o = _hub()
        assert o.hark("dog barking", importance="normal", now=0.0) is not None
        assert o.hark("SMOKE ALARM", importance="urgent", now=t) is not None, (
            f"an urgent safety hark was dropped at t={t} by an earlier normal hark")


def test_a_normal_hark_still_cannot_nag():
    o = _hub()
    assert o.hark("kettle", importance="normal", now=0.0) is not None
    assert o.hark("kettle again", importance="normal", now=30.0) is None
    assert o.hark("kettle later", importance="normal", now=121.0) is not None


def test_an_urgent_hark_still_cannot_spam_either():
    o = _hub()
    assert o.hark("SMOKE ALARM", importance="urgent", now=0.0) is not None
    assert o.hark("SMOKE ALARM", importance="urgent", now=30.0) is None
    assert o.hark("SMOKE ALARM", importance="urgent", now=121.0) is not None


# --------------------------------------------------------------------------
# B5 — the Veil gates the user model's learning
# --------------------------------------------------------------------------

def test_the_veil_stops_the_user_model_learning_from_a_spoken_line():
    # docs/gitbook/privacy.md lists "the user model's learning" among the things
    # a pause stops. `hear()` reached user.learn/user.observe with no gate.
    o = _hub()
    o.privacy.pause()
    assert o.privacy.allow_capture() is False
    o.hear("Hey Juno, call me Sam", now=0.0)  # noqa: E501 - see docstring
    o.hear("remember that I prefer aisle seats", now=1.0)
    assert not o.user.name, f"a name was learned under the Veil: {o.user.name!r}"
    assert not o.user._prefs, (
        f"a preference was learned under the Veil: {o.user._prefs!r}")
    # `observe()` writes _topics, and checking only name/_prefs let a mutant that
    # removed the observe gate pass while veiled speech persisted to disk.
    o.hear("Hey Juno, what did the oncologist say about the biopsy", now=2.0)
    assert not o.user._topics, (
        f"topics were learned under the Veil: {o.user._topics!r}")


def test_an_unreadable_posture_is_treated_as_veiled():
    """The gate claims to fail CLOSED, and nothing exercised that: flipping the
    handler to fail OPEN left every veil test green, because none of them used a
    posture that raises."""
    o = _hub()

    class _Broken:
        @staticmethod
        def allow_capture():
            raise RuntimeError("posture unreadable")

        @staticmethod
        def allow_recall():
            return True

        @staticmethod
        def paused():
            return False

    o.privacy = _Broken()
    o.hear("Hey Juno, call me Sam", now=0.0)
    assert not o.user.name, "a broken posture read as permission to learn"
    assert not o.user._topics


def test_incognito_off_is_still_sayable_from_inside_the_shield():
    """The gate is on the WRITES, not at the door, on purpose: "incognito" is a
    spoken command (commands.py:42), and a gate at the door would trap a wearer
    inside the shield with no voice way out. (An explicit `pause()` is a separate
    flag and is deliberately NOT clearable by leaving incognito -- the gesture is
    its own way back -- but incognito must stay voice-reversible.)"""
    o = _hub()
    o.privacy.set_incognito(True)
    assert o.privacy.allow_capture() is False
    res = o.hear("Hey Juno, turn off incognito", now=0.0)
    assert res.get("executed") is True
    assert o.privacy.allow_capture() is True


def test_the_user_model_still_learns_with_the_veil_down():
    o = _hub()
    o.hear("Hey Juno, call me Sam", now=0.0)
    assert o.user.name == "Sam"


def test_reinforce_at_grows_the_daypart_row_at_the_same_rate_as_the_general_one(tmp_path):
    """`reinforce` normalises `amount` away because a decaying row converges on
    `amount/(1 - PRIOR_DECAY)` — so at amount=0.3 the total converges on exactly
    PRIOR_FLOOR and `total >= floor` is reachable only in the limit, i.e. never.
    `reinforce_at` passed the raw amount to the DAYPART key, so the two rows for
    one pick disagreed and the daypart row was permanently unqualifiable.

    Note the general row must be read directly: `confident(part=…)` also
    consults the general row, which masks the daypart row's starvation.
    """
    priors = gl.GlancePriors(path=str(tmp_path / "p.json"))
    for _ in range(40):
        priors.reinforce_at("text", "scholar_explain", "morning", amount=0.3)

    general = priors._c["text"]
    daypart = priors._c["text@morning"]
    assert sum(daypart.values()) == pytest.approx(sum(general.values()), rel=1e-6), (
        "one pick credited the daypart row differently from the general row")
    assert sum(daypart.values()) >= gl.PRIOR_FLOOR, (
        "the daypart row can never reach PRIOR_FLOOR, so a time-of-day habit "
        "can never form, while boost_at still reports the full weight")
