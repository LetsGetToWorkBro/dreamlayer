"""orchestrator/capture.py — the missing loop: microphone → text → the hub.

Every voice surface (Juno wake, Veritas, captions, Name Capture, Timbre,
Puente) consumes *transcribed text*, and until now nothing produced it — the
seams existed (VAD, ASR, speaker id) but no code read a mic or drove `hear()`.
This is that glue.

The pipeline is push-based and endpoint-driven: `push_pcm(samples, ts)` feeds
short PCM windows; a VAD gate decides speech-vs-silence; speech windows
accumulate into a segment; trailing silence (or a max length) *endpoints* the
segment, which is transcribed once, optionally speaker-embedded, and routed to
the hub — `hear()` for the wake/command path and `ingest_caption()` for the
conversation ledger. Everything is veil-gated at the door and every failure
lands in the health ledger; nothing raw is ever stored.

`MicSource` is the hardware seam: `SoundDeviceMic` (lazy `sounddevice`) on a
real machine, `SyntheticMicSource` (feed it PCM/segments) everywhere else, so
the whole path tests offline. `start()/stop()` run the pull loop on a daemon
thread, matching the `start_message_polling` idiom (see docs/CONCURRENCY.md).
"""
from __future__ import annotations

import threading
import time

SAMPLE_RATE = 16000
WINDOW_MS = 200                      # per push window
SILENCE_HANG_MS = 600                # trailing silence that ends a segment
MAX_SEGMENT_MS = 12000               # hard cap so a monologue still endpoints


class CapturePipeline:
    """VAD-gated speech → ASR → speaker → hub. Providers are injected (all
    optional); with none installed the pipeline still runs and simply produces
    no transcript — same graceful-degradation contract as every seam."""

    def __init__(self, orch, vad=None, asr=None, speaker=None, wake=None,
                 speaker_resolver=None,
                 sample_rate: int = SAMPLE_RATE,
                 silence_hang_ms: float = SILENCE_HANG_MS,
                 max_segment_ms: float = MAX_SEGMENT_MS,
                 now_fn=None):
        self.orch = orch
        self.vad = vad
        self.asr = asr
        self.speaker = speaker           # ECAPASpeaker (embedding), optional
        # embedding → diarization label ("them"/"me"/a name); None → unknown "".
        # Speaker embeddings identify; the ledger wants a label, so keep them
        # separate rather than mislabelling a caption with a raw vector.
        self.speaker_resolver = speaker_resolver
        self.wake = wake
        self.last_speaker_embedding = None
        self.sample_rate = sample_rate
        self.silence_hang_ms = silence_hang_ms
        self.max_segment_ms = max_segment_ms
        self._now = now_fn or time.monotonic
        self._seg: list = []             # accumulated speech samples
        self._seg_started = 0.0
        self._last_speech = 0.0
        self._source = None
        self._stop = None
        self._thread = None

    # ------------------------------------------------------------------

    def _health(self):
        return getattr(self.orch, "health", None)

    def _record(self, exc):
        h = self._health()
        if h is not None:
            h.record_failure("asr", exc)

    def _veiled(self) -> bool:
        try:
            return not self.orch.privacy.allow_capture()
        except Exception:
            return False

    def push_pcm(self, samples, ts: float | None = None) -> str | None:
        """Feed one PCM window. Returns the transcript when this window
        *endpointed* a segment, else None. Veil-gated: while paused, nothing
        accumulates and any in-flight segment is dropped."""
        now = self._now() if ts is None else ts
        if self._veiled():
            self._seg = []
            return None

        speech = True
        if self.vad is not None:
            try:
                speech = bool(self.vad.is_speech(samples))
            except Exception as exc:
                self._record(exc)
                speech = True                # don't lose audio on a VAD error

        if speech:
            if not self._seg:
                self._seg_started = now
            self._seg.extend(samples)
            self._last_speech = now
            # hard cap: a long talker still endpoints
            if (now - self._seg_started) * 1000.0 >= self.max_segment_ms:
                return self._endpoint(now)
            return None

        # silence: end the segment once the hang time has passed
        if self._seg and (now - self._last_speech) * 1000.0 >= self.silence_hang_ms:
            return self._endpoint(now)
        return None

    def flush(self) -> str | None:
        """Force-endpoint any pending segment now (a source drained, or stop()).
        Real mics never drain; a fixture does, so a trailing utterance isn't
        lost waiting for a silence window that never comes."""
        if not self._seg or self._veiled():
            self._seg = []
            return None
        return self._endpoint(self._now())

    def _endpoint(self, now: float) -> str | None:
        """Transcribe the accumulated segment, route it, reset."""
        segment, self._seg = self._seg, []
        if not segment or self.asr is None:
            return None
        try:
            text = (self.asr.transcribe(segment) or "").strip()
        except Exception as exc:
            self._record(exc)
            return None
        if not text:
            return None

        label = ""
        if self.speaker is not None:
            try:
                emb = self.speaker.embed(segment)
                self.last_speaker_embedding = emb
                if self.speaker_resolver is not None:
                    label = self.speaker_resolver(emb) or ""
            except Exception as exc:
                if self._health() is not None:
                    self._health().record_failure("asr", exc)
        self._route(text, label)
        return text

    def _route(self, text: str, speaker_label: str) -> None:
        """Feed the hub: the wake/command path AND the conversation ledger.
        Both are veil-gated inside the orchestrator already; failures recorded."""
        # wake / command path
        try:
            self.orch.hear(text)
        except Exception as exc:
            self._record(exc)
        # conversation ledger (captions, commitments, veritas ride on this)
        try:
            self.orch.ingest_caption(text, speaker=speaker_label)
        except Exception as exc:
            self._record(exc)

    # ------------------------------------------------------------------
    # background pull loop (daemon thread, start/stop idiom)

    def start(self, source) -> None:
        """Pull PCM windows off `source` (a MicSource) on a daemon thread."""
        if self._thread is not None:
            return
        self._source = source
        self._stop = threading.Event()
        source.open(self.sample_rate,
                    int(self.sample_rate * WINDOW_MS / 1000))

        def loop():
            idle = 0
            while not self._stop.is_set():
                try:
                    window = source.read()
                except Exception as exc:
                    self._record(exc)
                    break
                if window is None:
                    idle += 1
                    # a few empty reads in a row = the source went quiet; flush
                    # any pending utterance so a drained fixture isn't stuck
                    if idle == 3 and self._seg:
                        self.flush()
                    if self._stop.wait(0.01):
                        break
                    continue
                idle = 0
                self.push_pcm(window)

        self._thread = threading.Thread(target=loop, daemon=True,
                                        name="dreamlayer-capture")
        self._thread.start()

    def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        self.flush()                     # don't lose a trailing utterance
        if self._source is not None:
            try:
                self._source.close()
            except Exception:
                pass
        self._thread = None
        self._source = None


# ---------------------------------------------------------------------------
# Mic sources (the hardware seam)

class MicSource:
    """A pull source of mono PCM windows. open(rate, frames) then read() → a
    window (list/array) or None when nothing is ready; close() to release."""

    def open(self, sample_rate: int, frames: int) -> None: ...
    def read(self): ...
    def close(self) -> None: ...


class SyntheticMicSource(MicSource):
    """Test/offline source: hand it a list of PCM windows (or one flat PCM
    buffer split into `frames`-sized windows). read() yields them once, then
    returns None forever — so a pipeline drains a fixture deterministically."""

    def __init__(self, windows=None, pcm=None):
        self._preset = list(windows) if windows is not None else None
        self._pcm = list(pcm) if pcm is not None else None
        self._queue: list = []

    def open(self, sample_rate: int, frames: int) -> None:
        if self._preset is not None:
            self._queue = list(self._preset)
        elif self._pcm is not None:
            self._queue = [self._pcm[i:i + frames]
                           for i in range(0, len(self._pcm), frames)]
        else:
            self._queue = []

    def read(self):
        return self._queue.pop(0) if self._queue else None

    def close(self) -> None:
        self._queue = []


class SoundDeviceMic(MicSource):
    """Real microphone via `sounddevice` (lazy). Absent → open() raises, which
    the caller treats as 'no capture available' (the seam stays a seam)."""

    available = False

    def __init__(self):
        self._stream = None
        try:
            import sounddevice  # noqa: F401
            SoundDeviceMic.available = True
        except Exception:
            pass

    def open(self, sample_rate: int, frames: int) -> None:
        import sounddevice as sd
        self._frames = frames
        self._stream = sd.InputStream(
            samplerate=sample_rate, channels=1, dtype="float32")
        self._stream.start()

    def read(self):
        if self._stream is None:
            return None
        data, _overflowed = self._stream.read(self._frames)
        return [float(x[0]) for x in data]

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop(); self._stream.close()
            self._stream = None
