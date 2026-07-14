"""The capture path: PCM → VAD-gated segments → ASR → the hub, veil-gated, with
failures recorded; the synthetic mic source drains a fixture; real vision
backends fall back cleanly; dismissal telemetry lifts the proactive floor."""

from dreamlayer.bridge.emulator_bridge import EmulatorBridge
from dreamlayer.orchestrator.capture import (
    CapturePipeline, SyntheticMicSource,
)
from dreamlayer.orchestrator.orchestrator import Orchestrator


class FakeVAD:
    """Speech iff any sample is non-zero (so a fixture can encode silence)."""
    def is_speech(self, samples):
        return any(abs(x) > 1e-6 for x in samples)


class FakeASR:
    def __init__(self, text="hey layer what's the time"):
        self.text = text
        self.calls = 0

    def transcribe(self, segment):
        self.calls += 1
        return self.text


class TestCapturePipeline:
    def _orch(self):
        return Orchestrator(EmulatorBridge())

    def test_speech_then_silence_endpoints_and_routes(self):
        orch = self._orch()
        heard = []
        orch.hear = lambda text, now=None: heard.append(text) or {}
        cap = CapturePipeline(orch, vad=FakeVAD(), asr=FakeASR("what time is it"))
        # three speech windows, then a silence window past the hang time
        assert cap.push_pcm([0.5] * 100, ts=0.0) is None
        assert cap.push_pcm([0.5] * 100, ts=0.2) is None
        assert cap.push_pcm([0.5] * 100, ts=0.4) is None
        text = cap.push_pcm([0.0] * 100, ts=1.2)          # silence → endpoint
        assert text == "what time is it"
        assert heard == ["what time is it"]

    def test_veil_drops_in_flight_audio(self):
        orch = self._orch()
        orch.privacy.pause()                              # doors shut
        cap = CapturePipeline(orch, vad=FakeVAD(), asr=FakeASR())
        assert cap.push_pcm([0.5] * 100, ts=0.0) is None
        assert cap._seg == []                             # nothing accumulated

    def test_veil_fails_closed_when_gate_raises(self):
        # Re-audit: _veiled() returned False (capture ON) if the privacy gate
        # raised or was missing — failing OPEN on the one path that must never
        # leak. A broken gate must veil, not un-veil, and the failure is recorded.
        orch = self._orch()

        class BoomGate:
            def allow_capture(self):
                raise RuntimeError("gate exploded")

        orch.privacy = BoomGate()
        cap = CapturePipeline(orch, vad=FakeVAD(), asr=FakeASR("should not route"))
        assert cap.push_pcm([0.5] * 100, ts=0.0) is None   # veiled, dropped
        assert cap._seg == []                               # nothing accumulated
        assert orch.health.failures("asr") >= 1             # broken gate is visible

    def test_max_segment_endpoints_a_monologue(self):
        orch = self._orch()
        orch.hear = lambda text, now=None: {}
        cap = CapturePipeline(orch, vad=FakeVAD(), asr=FakeASR("on and on"),
                              max_segment_ms=500)
        cap.push_pcm([0.5] * 10, ts=0.0)
        text = cap.push_pcm([0.5] * 10, ts=0.6)           # exceeds 500ms cap
        assert text == "on and on"

    def test_asr_failure_recorded_not_fatal(self):
        orch = self._orch()

        class BadASR:
            def transcribe(self, seg):
                raise RuntimeError("model exploded")

        cap = CapturePipeline(orch, vad=FakeVAD(), asr=BadASR())
        cap.push_pcm([0.5] * 10, ts=0.0)
        assert cap.push_pcm([0.0] * 10, ts=1.0) is None   # no crash
        assert orch.health.failures("asr") >= 1

    def test_speaker_resolver_labels_the_caption(self):
        orch = self._orch()
        captions = []
        orch.hear = lambda t, now=None: {}
        orch.ingest_caption = lambda text, speaker="": captions.append((text, speaker))

        class Emb:
            def embed(self, seg):
                return [1.0, 0.0]

        cap = CapturePipeline(orch, vad=FakeVAD(), asr=FakeASR("hi"),
                              speaker=Emb(), speaker_resolver=lambda e: "them")
        cap.push_pcm([0.5] * 10, ts=0.0)
        cap.push_pcm([0.0] * 10, ts=1.0)
        assert captions and captions[0] == ("hi", "them")

    def test_daemon_loop_drains_a_synthetic_source(self):
        import time
        orch = self._orch()
        heard = []
        orch.hear = lambda text, now=None: heard.append(text) or {}
        cap = CapturePipeline(orch, vad=FakeVAD(), asr=FakeASR("drained"))
        src = SyntheticMicSource(windows=[[0.5] * 10, [0.5] * 10, [0.0] * 10])
        cap.start(src)
        # let the daemon consume the fixture, then stop
        for _ in range(50):
            if heard:
                break
            time.sleep(0.01)
        cap.stop()
        assert heard == ["drained"]


class TestWakeword:
    def test_engine_unavailable_falls_back(self):
        from dreamlayer.orchestrator.wakeword import OpenWakeWordEngine
        eng = OpenWakeWordEngine()
        if not OpenWakeWordEngine.available:
            assert eng.detect([0.1] * 100) == (False, 0.0)  # graceful
        else:
            fired, score = eng.detect([0.0] * 1600)
            assert isinstance(fired, bool) and 0.0 <= score <= 1.0


class TestRealVisionBackends:
    def test_backends_return_none_without_deps(self):
        # with no vision deps installed, every real backend degrades to None so
        # ObjectRecognizer's mock stays authoritative — the whole suite unaffected
        from dreamlayer.object_lens.classify_backends import (
            ClipClassifier, MoondreamClassifier, default_classifier,
        )
        import numpy as np
        frame = np.zeros((8, 8, 3), dtype=np.uint8)
        if not ClipClassifier.available:
            assert ClipClassifier(["mug", "plant"])(frame) is None
        if not MoondreamClassifier.available:
            assert MoondreamClassifier()(frame) is None
        # the ladder returns None when nothing real is installed
        clf = default_classifier(["mug"])
        assert clf is None or callable(clf)

    def test_orchestrator_uses_mock_when_no_backend(self):
        # constructing the orchestrator must not fail regardless of vision deps
        orch = Orchestrator(EmulatorBridge())
        assert orch.object_lens is not None


class TestDismissalLearning:
    def test_swatting_a_card_type_lifts_the_proactive_floor(self):
        orch = Orchestrator(EmulatorBridge())
        base = orch.proactive._effective_min()
        # flood dismissals for the proactive card type
        for _ in range(6):
            orch._on_event("TEL", {"event": "CARD_SHOWN",
                                   "card_type": "ProactiveMemoryCard"})
            orch._on_event("TEL", {"event": "CARD_DISMISSED", "method": "tap",
                                   "card_type": "ProactiveMemoryCard"})
        lifted = orch.proactive._effective_min()
        assert lifted > base                    # the floor rose after dismissals
