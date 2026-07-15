"""orchestrator/sherpa_backend.py — one on-device speech engine for the lot.

DreamLayer's voice seams grew up one model at a time: faster-whisper for ASR
(asr_faster_whisper.py), silero for VAD (vad_gate.py), speechbrain/ECAPA for
speaker embeddings (speaker_ecapa.py), openWakeWord for wake (wakeword.py).
That's four models, four dependency stacks, four glue paths.

`sherpa-onnx` (k2-fsa, Apache-2.0) does all of it — streaming/offline ASR,
Silero VAD, speaker embedding + verification, keyword spotting, speaker
diarization, and audio-event tagging — behind a single offline onnxruntime
core. This module wraps it so **one** optional dependency can back every seam,
and adds two capabilities the old stack never had:

  * **diarization** — "who said what" across a segment, not just one label
  * **audio tagging** — non-speech acoustic context (a doorbell, an alarm,
    running water) so the second brain understands more than words

Design, matching every other seam here:
  * lazy import; ``SherpaSpeech.available`` is False when the wheel or the
    model files are absent, and every adapter degrades to the same empty/
    fallback result the pure-Python seams already return — the suite is
    unaffected when sherpa isn't installed;
  * the adapters are **drop-in** for the existing seam contracts
    (``asr.transcribe``, ``vad.is_speech``, ``speaker.embed`` + ``similarity``,
    ``wake.detect`` + ``reset``), so a caller swaps backends without changing
    the capture pipeline;
  * model handles are lazily built from a ``SherpaConfig`` of file paths and
    can be injected for tests (``_impl=``), so the mapping logic is checked
    without any model download.

Models are not vendored (they're 20–200 MB each); point ``SherpaConfig`` at a
local model dir on the Mac-mini Brain. See docs/PERCEPTION_BACKENDS.md.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger(__name__)

try:
    import sherpa_onnx  # type: ignore
    _HAS_SHERPA = True
except Exception:                       # pragma: no cover - env-dependent
    sherpa_onnx = None                  # type: ignore
    _HAS_SHERPA = False

SAMPLE_RATE = 16000


def _to_float32(audio):
    """Coerce a PCM window (list/np array, int16 or float) to a float32 numpy
    array in [-1, 1] — the form every sherpa-onnx entry point wants."""
    import numpy as np
    a = np.asarray(audio)
    if a.dtype.kind in ("i", "u"):       # int PCM → normalize
        a = a.astype("float32") / 32768.0
    return np.ascontiguousarray(a.astype("float32"))


@dataclass
class SherpaConfig:
    """Paths to the model files sherpa-onnx loads. Everything is optional: a
    field left None simply disables that capability (its adapter degrades).
    On the Brain these point at a downloaded model directory."""
    sample_rate: int = SAMPLE_RATE
    # offline ASR (transducer/paraformer/whisper/sensevoice export)
    asr_tokens: Optional[str] = None
    asr_encoder: Optional[str] = None
    asr_decoder: Optional[str] = None
    asr_joiner: Optional[str] = None
    asr_paraformer: Optional[str] = None
    asr_model_type: str = ""            # "" = let sherpa infer
    # Silero VAD
    vad_model: Optional[str] = None
    vad_threshold: float = 0.5
    # speaker embedding extractor (3d-speaker / nemo / wespeaker export)
    speaker_model: Optional[str] = None
    # keyword spotting (wake) — transducer + a keywords file
    kws_tokens: Optional[str] = None
    kws_encoder: Optional[str] = None
    kws_decoder: Optional[str] = None
    kws_joiner: Optional[str] = None
    kws_keywords_file: Optional[str] = None
    # audio tagging (CED / zipformer AudioSet export) + labels
    tag_model: Optional[str] = None
    tag_labels: Optional[str] = None
    tag_top_k: int = 3
    num_threads: int = 1


# ---------------------------------------------------------------------------
# Adapters — each conforms to an existing seam contract, so they are drop-in.
# ---------------------------------------------------------------------------

class SherpaASR:
    """Drop-in for FasterWhisperASR: ``transcribe(audio, language) -> str``."""

    available = _HAS_SHERPA

    def __init__(self, cfg: SherpaConfig, _impl=None):
        self.cfg = cfg
        self._impl = _impl               # an OfflineRecognizer (or a test fake)

    def transcribe(self, audio, language: str = "en") -> str:
        rec = self._impl
        if rec is None:
            return ""
        try:
            stream = rec.create_stream()
            stream.accept_waveform(self.cfg.sample_rate, _to_float32(audio))
            rec.decode_stream(stream)
            return (stream.result.text or "").strip()
        except Exception as exc:         # pragma: no cover - real-model path
            log.warning("sherpa ASR failed: %s", exc)
            return ""


class SherpaVAD:
    """Drop-in for SileroVADGate: ``is_speech(samples) -> bool``. sherpa's
    detector is segment-oriented; for the window-gate contract we accept the
    window and report whether the detector currently holds speech."""

    available = _HAS_SHERPA

    def __init__(self, cfg: SherpaConfig, _impl=None):
        self.cfg = cfg
        self._impl = _impl               # a VoiceActivityDetector (or fake)

    def is_speech(self, samples) -> bool:
        vad = self._impl
        if vad is None:
            return True                  # no gate → don't drop audio (seam rule)
        try:
            vad.accept_waveform(_to_float32(samples))
            # `is_speech` when the model reports voiced; else any buffered seg
            fn = getattr(vad, "is_speech", None)
            if callable(fn):
                return bool(fn())
            return not bool(vad.empty())
        except Exception as exc:         # pragma: no cover - real-model path
            log.warning("sherpa VAD failed: %s", exc)
            return True

    def reset(self) -> None:
        try:
            if self._impl is not None:
                self._impl.reset()
        except Exception:
            pass


class SherpaSpeakerEmbedding:
    """Drop-in for ECAPASpeaker: ``embed(audio, key) -> list[float]`` plus the
    static ``similarity`` cosine helper the resolver uses."""

    available = _HAS_SHERPA

    def __init__(self, cfg: SherpaConfig, _impl=None):
        self.cfg = cfg
        self._impl = _impl               # a SpeakerEmbeddingExtractor (or fake)

    def embed(self, audio, key: str | None = None) -> list[float]:
        ext = self._impl
        if ext is None:
            return []
        try:
            stream = ext.create_stream()
            stream.accept_waveform(self.cfg.sample_rate, _to_float32(audio))
            stream.input_finished()
            return [float(x) for x in ext.compute(stream)]
        except Exception as exc:         # pragma: no cover - real-model path
            log.warning("sherpa speaker embed failed: %s", exc)
            return []

    @staticmethod
    def similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(y * y for y in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0


class SherpaWakeWord:
    """Drop-in for OpenWakeWordEngine: ``detect(samples) -> (hit, score)``,
    backed by sherpa keyword-spotting — a real acoustic wake path, Apache-
    licensed, versus the text-level matcher or NC-licensed openWakeWord."""

    available = _HAS_SHERPA

    def __init__(self, cfg: SherpaConfig, _impl=None):
        self.cfg = cfg
        self._impl = _impl               # a KeywordSpotter (or fake)
        self._stream: Any = None         # sherpa-onnx stream (untyped optional dep)

    def detect(self, samples) -> tuple[bool, float]:
        kws = self._impl
        if kws is None:
            return (False, 0.0)
        try:
            if self._stream is None:
                self._stream = kws.create_stream()
            self._stream.accept_waveform(self.cfg.sample_rate,
                                         _to_float32(samples))
            hit = False
            while kws.is_ready(self._stream):
                kws.decode_stream(self._stream)
                if getattr(self._stream.result, "keyword", ""):
                    hit = True
            return (hit, 1.0 if hit else 0.0)
        except Exception as exc:         # pragma: no cover - real-model path
            log.warning("sherpa KWS failed: %s", exc)
            return (False, 0.0)

    def reset(self) -> None:
        self._stream = None


class SherpaDiarizer:
    """New capability: ``diarize(audio) -> [(start_s, end_s, speaker_id)]`` —
    who spoke when across a whole segment, so a caption can attribute multiple
    speakers instead of one label. Empty list when unavailable."""

    available = _HAS_SHERPA

    def __init__(self, cfg: SherpaConfig, _impl=None):
        self.cfg = cfg
        self._impl = _impl               # an OfflineSpeakerDiarization (or fake)

    def diarize(self, audio) -> list[tuple[float, float, int]]:
        diar = self._impl
        if diar is None:
            return []
        try:
            result = diar.process(_to_float32(audio)).sort_by_start_time()
            return [(float(s.start), float(s.end), int(s.speaker))
                    for s in result]
        except Exception as exc:         # pragma: no cover - real-model path
            log.warning("sherpa diarization failed: %s", exc)
            return []


class SherpaAudioTagger:
    """New capability: ``tag(audio) -> [(label, score)]`` — non-speech acoustic
    context (AudioSet classes: doorbell, alarm, dog bark, running water…), the
    top-k events in a window. Empty list when unavailable."""

    available = _HAS_SHERPA

    def __init__(self, cfg: SherpaConfig, _impl=None):
        self.cfg = cfg
        self._impl = _impl               # an AudioTagging (or fake)

    def tag(self, audio) -> list[tuple[str, float]]:
        tagger = self._impl
        if tagger is None:
            return []
        try:
            stream = tagger.create_stream()
            stream.accept_waveform(self.cfg.sample_rate, _to_float32(audio))
            events = tagger.compute(stream, top_k=self.cfg.tag_top_k)
            return [(str(e.name), float(e.prob)) for e in events]
        except Exception as exc:         # pragma: no cover - real-model path
            log.warning("sherpa audio tagging failed: %s", exc)
            return []


# ---------------------------------------------------------------------------
# The unified engine: one lazy load, six adapters.
# ---------------------------------------------------------------------------

class SherpaSpeech:
    """Build every seam from one sherpa-onnx install + a `SherpaConfig`.

    Each sub-model is loaded only if its config paths are set; a load failure
    (missing file, wheel-version drift) disables just that capability and is
    logged, never raised — the seam contract. Pass the adapters straight into
    ``CapturePipeline(vad=…, asr=…, speaker=…, wake=…, tagger=…)``."""

    def __init__(self, cfg: SherpaConfig | None = None, *, _fake=None):
        self.cfg = cfg or SherpaConfig()
        self.available = _HAS_SHERPA or _fake is not None
        # _fake lets tests inject a namespace of pre-built model handles
        f = _fake or _Loaded()
        if _fake is None and _HAS_SHERPA:
            f = self._load(self.cfg)
        self.asr = SherpaASR(self.cfg, f.asr)
        self.vad = SherpaVAD(self.cfg, f.vad)
        self.speaker = SherpaSpeakerEmbedding(self.cfg, f.speaker)
        self.wake = SherpaWakeWord(self.cfg, f.wake)
        self.diarizer = SherpaDiarizer(self.cfg, f.diarizer)
        self.tagger = SherpaAudioTagger(self.cfg, f.tagger)

    @staticmethod
    def _load(cfg: SherpaConfig) -> "_Loaded":  # pragma: no cover - real-model
        """Best-effort construction of each sherpa handle from cfg paths.
        Validated on a real install; every branch is independently guarded so a
        missing model only disables its own capability."""
        so = sherpa_onnx
        out = _Loaded()

        def _try(fn):
            try:
                return fn()
            except Exception as exc:
                log.warning("sherpa load skipped: %s", exc)
                return None

        if cfg.asr_tokens and (cfg.asr_encoder or cfg.asr_paraformer):
            out.asr = _try(lambda: so.OfflineRecognizer.from_transducer(
                tokens=cfg.asr_tokens, encoder=cfg.asr_encoder,
                decoder=cfg.asr_decoder, joiner=cfg.asr_joiner,
                num_threads=cfg.num_threads)
                if cfg.asr_encoder else
                so.OfflineRecognizer.from_paraformer(
                    tokens=cfg.asr_tokens, paraformer=cfg.asr_paraformer,
                    num_threads=cfg.num_threads))
        if cfg.vad_model:
            def _mk_vad():
                vc = so.VadModelConfig()
                vc.silero_vad.model = cfg.vad_model
                vc.silero_vad.threshold = cfg.vad_threshold
                vc.sample_rate = cfg.sample_rate
                return so.VoiceActivityDetector(vc, buffer_size_in_seconds=30)
            out.vad = _try(_mk_vad)
        if cfg.speaker_model:
            out.speaker = _try(lambda: so.SpeakerEmbeddingExtractor(
                so.SpeakerEmbeddingExtractorConfig(
                    model=cfg.speaker_model, num_threads=cfg.num_threads)))
        if cfg.kws_tokens and cfg.kws_encoder and cfg.kws_keywords_file:
            out.wake = _try(lambda: so.KeywordSpotter(
                tokens=cfg.kws_tokens, encoder=cfg.kws_encoder,
                decoder=cfg.kws_decoder, joiner=cfg.kws_joiner,
                keywords_file=cfg.kws_keywords_file,
                num_threads=cfg.num_threads))
        if cfg.tag_model and cfg.tag_labels:
            def _mk_tag():
                tc = so.AudioTaggingConfig(
                    model=so.AudioTaggingModelConfig(
                        ced=cfg.tag_model, num_threads=cfg.num_threads),
                    labels=cfg.tag_labels, top_k=cfg.tag_top_k)
                return so.AudioTagging(tc)
            out.tagger = _try(_mk_tag)
        if cfg.speaker_model:
            out.diarizer = _try(lambda: so.OfflineSpeakerDiarization(
                so.OfflineSpeakerDiarizationConfig(
                    segmentation=so.OfflineSpeakerSegmentationModelConfig(),
                    embedding=so.SpeakerEmbeddingExtractorConfig(
                        model=cfg.speaker_model))))
        return out


@dataclass
class _Loaded:
    """The set of built model handles (or Nones). Tests inject one of these to
    exercise the adapter mapping with fakes and no model download."""
    asr: object = None
    vad: object = None
    speaker: object = None
    wake: object = None
    diarizer: object = None
    tagger: object = None
