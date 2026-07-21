"""Kokoro on-device neural TTS — Juno's voice, offline (Kokoro-82M, Apache-2.0).

ADD-alongside, the higher-quality sibling of tts_piper.py. Kokoro-82M is a tiny
(82M-param) but remarkably natural TTS that runs on CPU with no cloud — so Juno
sounds far better than Piper while staying fully on-device. Same discipline as
tts_piper: lazy-imports `kokoro` (extras group `voice`); when kokoro — or its
model, or an output device — is absent, synthesize() returns None and speak() is
a silent no-op, so Juno behaves exactly as today (text on the glass, no audio).
Nothing here ever raises into the reply path.

Voice + language are pickable: $DL_KOKORO_VOICE (default "af_heart") and
$DL_KOKORO_LANG (default "a" = American English; "b" British, "j" Japanese, …).
Kokoro fetches its 82M model on first construction — a model-weights download,
posture-gated like the other local models; audio itself never leaves the Brain.
"""
from __future__ import annotations

import io
import logging
import os
import threading
import wave
from typing import Any, Callable, Optional

log = logging.getLogger("dreamlayer.tts_kokoro")

_RATE = 24000                    # Kokoro synthesizes at 24 kHz mono

try:  # optional dep — extras group `voice`
    import kokoro  # type: ignore  # noqa: F401
    _HAS_KOKORO = True
except Exception:  # ImportError, or a half-built native wheel — never take us down
    _HAS_KOKORO = False


class KokoroTTS:
    """Wrap one Kokoro voice. `available` is True only when kokoro imports AND the
    pipeline actually built — so callers gate on a single flag, exactly like
    PiperTTS."""

    available = _HAS_KOKORO

    def __init__(self, voice: Optional[str] = None, lang_code: Optional[str] = None):
        self._pipe: Any = None
        self._rate = _RATE
        self.voice_name = ""
        if not _HAS_KOKORO:
            return
        voice = (voice or os.environ.get("DL_KOKORO_VOICE") or "af_heart").strip()
        lang = (lang_code or os.environ.get("DL_KOKORO_LANG") or "a").strip() or "a"
        try:
            from kokoro import KPipeline  # type: ignore
            self._pipe = KPipeline(lang_code=lang)
            self.voice_name = voice
        except Exception as exc:                       # noqa: BLE001
            log.error("[tts] kokoro pipeline build failed: %s; silent fallback", exc)
            self._pipe = None

    @property
    def ready(self) -> bool:
        return self._pipe is not None

    def _raw_pcm(self, text: str) -> Optional[bytes]:
        """int16 mono PCM for `text`, or None on any failure — the caller degrades
        to silence, never crashes. Kokoro yields (graphemes, phonemes, audio)
        chunks; we concatenate the audio (a float32 tensor/array in [-1, 1])."""
        if self._pipe is None:
            return None
        try:
            import numpy as np
            chunks = []
            for item in self._pipe(text, voice=self.voice_name):
                audio = item[2] if isinstance(item, (list, tuple)) and len(item) >= 3 \
                    else getattr(item, "audio", item)
                if audio is None:
                    continue
                arr = np.asarray(getattr(audio, "cpu", lambda: audio)()
                                 if hasattr(audio, "cpu") else audio,
                                 dtype=np.float32).reshape(-1)
                if arr.size:
                    chunks.append(arr)
            if not chunks:
                return None
            wav = np.clip(np.concatenate(chunks), -1.0, 1.0)
            return (wav * 32767.0).astype("<i2").tobytes()
        except Exception as exc:                       # noqa: BLE001
            log.error("[tts] kokoro synth failed: %s", exc)
            return None

    def synthesize(self, text: str) -> Optional[bytes]:
        """Speech for `text` as self-describing WAV bytes (mono int16), or None
        when TTS is unavailable — WAV so a caller can also stream it to a phone or
        panel that has a speaker even when the Brain has none."""
        text = (text or "").strip()
        if not text or self._pipe is None:
            return None
        pcm = self._raw_pcm(text)
        if not pcm:
            return None
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._rate)
            wf.writeframes(pcm)
        return buf.getvalue()

    def play(self, wav_bytes: bytes) -> None:
        """Blocking playback of WAV bytes via sounddevice. Guarded: no device, no
        sounddevice, or a decode error is a silent no-op (identical to PiperTTS)."""
        if not wav_bytes:
            return
        try:
            import numpy as np  # numpy is a base dependency
            import sounddevice as sd  # optional — same `voice` extra
        except Exception:                              # noqa: BLE001
            return
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                rate = wf.getframerate()
                frames = wf.readframes(wf.getnframes())
            samples = np.frombuffer(frames, dtype=np.int16)
            sd.play(samples, rate)
            sd.wait()
        except Exception as exc:                       # noqa: BLE001
            log.error("[tts] playback failed: %s", exc)


def make_speak_fn(voice: Optional[str] = None,
                  lang_code: Optional[str] = None) -> Callable[[str], None]:
    """A ready-to-wire `speak(text)` callable (mirrors tts_piper.make_speak_fn).

    speak(text) only ENQUEUES — it never blocks the caller and never spawns a
    thread per reply. A single daemon worker synthesizes AND plays one utterance
    at a time, so the neural inference is off the reply thread and two replies
    can't fight over sounddevice's one output stream. Under a burst the bounded
    queue drops the newest rather than pile up. When kokoro or its model is
    missing, the returned callable is a silent no-op with `.ready = False`, so a
    caller can fall through to another engine."""
    tts = KokoroTTS(voice, lang_code)
    if not tts.ready:
        noop: Callable[[str], None] = lambda _text: None
        noop.ready = False        # type: ignore[attr-defined]
        return noop

    import queue as _queue
    q: "_queue.Queue[str]" = _queue.Queue(maxsize=8)

    def _worker() -> None:
        while True:
            text = q.get()
            try:
                wav = tts.synthesize(text)
                if wav:
                    tts.play(wav)               # blocking, but on THIS worker only
            except Exception as exc:             # noqa: BLE001 — the worker never dies
                log.error("[tts] speak failed: %s", exc)

    threading.Thread(target=_worker, daemon=True).start()

    def speak(text: str) -> None:
        try:
            q.put_nowait(text)                   # non-blocking; never stalls the reply
        except _queue.Full:
            pass                                 # a backlog of speech → drop, don't pile up

    speak.ready = True            # type: ignore[attr-defined]
    return speak
