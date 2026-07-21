"""Piper on-device neural TTS — give Juno a real spoken voice, offline.

ADD-alongside: new module, the write-counterpart of asr_faster_whisper.py.
Lazy-imports piper (extras group `voice`); when piper — or a voice model, or an
output device — is absent, synthesize() returns None and speak() is a silent
no-op, so Juno behaves exactly as today (text on the glass, no audio). Nothing
here ever raises into the reply path.

A voice is a Piper model pair: `<name>.onnx` + its sibling `<name>.onnx.json`.
Point at one with $DL_PIPER_VOICE, pass a path, or drop it in <cfg>/voices/.
"""
from __future__ import annotations

import io
import logging
import os
import threading
import wave
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("dreamlayer.tts_piper")

try:  # optional dep — extras group `voice`
    from piper.voice import PiperVoice  # type: ignore
    _HAS_PIPER = True
except Exception:  # ImportError, or a half-built native wheel — never take us down
    _HAS_PIPER = False


def find_voice_model(explicit: Optional[str] = None,
                     dirs: tuple[Path, ...] = ()) -> Optional[Path]:
    """First usable Piper voice: an explicit path, then $DL_PIPER_VOICE, then the
    first `*.onnx` (with a sibling `*.onnx.json`) under any of `dirs`. A voice
    without its json config is unusable, so it's skipped, not half-loaded."""
    cands: list[Path] = []
    if explicit:
        cands.append(Path(explicit))
    env = os.environ.get("DL_PIPER_VOICE")
    if env:
        cands.append(Path(env))
    search: list[Path] = list(dirs)
    vdir = os.environ.get("DL_VOICES_DIR")
    if vdir:
        search.append(Path(vdir))
    for d in search:
        try:
            cands.extend(sorted(Path(d).glob("*.onnx")))
        except OSError:
            continue
    for p in cands:
        try:
            if p.suffix == ".onnx" and p.is_file() and \
                    p.with_suffix(".onnx.json").is_file():
                return p
        except OSError:
            continue
    return None


class PiperTTS:
    """Wrap one Piper voice. `available` is True only when piper imports AND a
    voice model actually loaded — so callers can gate on a single flag."""

    available = _HAS_PIPER

    def __init__(self, voice_model: Optional[str] = None,
                 dirs: tuple[Path, ...] = ()):
        self._voice = None
        self._rate = 22050
        if not _HAS_PIPER:
            return
        model = find_voice_model(voice_model, dirs)
        if model is None:
            log.info("[tts] piper is installed but no voice model was found "
                     "(set $DL_PIPER_VOICE or drop a *.onnx in <cfg>/voices/)")
            return
        try:
            self._voice = PiperVoice.load(str(model))
            cfg = getattr(self._voice, "config", None)
            self._rate = int(getattr(cfg, "sample_rate", 0) or 22050)
        except Exception as exc:                       # noqa: BLE001
            log.error("[tts] piper voice load failed: %s; silent fallback", exc)
            self._voice = None

    @property
    def ready(self) -> bool:
        return self._voice is not None

    def _raw_pcm(self, text: str) -> Optional[bytes]:
        """int16 mono PCM for `text`, across piper API generations. Returns None
        on any failure — the caller degrades to silence, never crashes."""
        v = self._voice
        if v is None:
            return None
        # piper <=1.1: a generator of raw int16 byte chunks
        raw = getattr(v, "synthesize_stream_raw", None)
        if callable(raw):
            try:
                return b"".join(bytes(c) for c in raw(text))
            except Exception as exc:                   # noqa: BLE001
                log.error("[tts] synthesize_stream_raw failed: %s", exc)
                return None
        # piper >=1.2: synthesize() writes into a wave.Wave_write
        try:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                v.synthesize(text, wf)
            buf.seek(0)
            with wave.open(buf, "rb") as wf:
                self._rate = wf.getframerate() or self._rate
                return wf.readframes(wf.getnframes())
        except Exception as exc:                       # noqa: BLE001
            log.error("[tts] synthesize failed: %s", exc)
            return None

    def synthesize(self, text: str) -> Optional[bytes]:
        """Speech for `text` as self-describing WAV bytes (mono int16), or None
        when TTS is unavailable. WAV so a caller can also stream it to a phone
        or panel that has a speaker even when the Brain has none."""
        text = (text or "").strip()
        if not text or self._voice is None:
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
        """Blocking playback of WAV bytes via sounddevice. Guarded: no device,
        no sounddevice, or a decode error is a silent no-op."""
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


def make_speak_fn(voice_model: Optional[str] = None,
                  dirs: tuple[Path, ...] = ()) -> Callable[[str], None]:
    """A ready-to-wire `speak(text)` callable (mirrors rosetta's make_translate_fn).

    Synthesizes and plays on a daemon thread so a reply never blocks on audio.
    When piper or a voice model is missing, the returned callable is a no-op —
    so `orchestrator._juno_say` can call it unconditionally."""
    tts = PiperTTS(voice_model, dirs)
    if not tts.ready:
        noop: Callable[[str], None] = lambda _text: None
        noop.ready = False        # type: ignore[attr-defined]
        return noop

    def speak(text: str) -> None:
        wav = tts.synthesize(text)
        if not wav:
            return
        threading.Thread(target=tts.play, args=(wav,), daemon=True).start()

    speak.ready = True            # type: ignore[attr-defined]
    return speak
