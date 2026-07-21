"""rosetta_seamless.py — the EAR half of Rosetta: a live interpreter (SeamlessM4T).

ADD-alongside, the voice twin of rosetta_argos.py. Where Argos translates text you
*look at*, SeamlessM4T translates conversation you're *in*: someone speaks Japanese,
this turns their speech into English text (S2TT) that Juno then speaks into your ear
in her own Piper voice — and turns your English reply into Japanese speech (T2ST) to
play back. Fully on-device (Meta's SeamlessM4T-v2 ships in `transformers`); the audio
never leaves the Brain.

Two clean seams, both lazy and graceful:
  * `RosettaLens(interpret_fn=make_interpret_fn())` — `hear(audio)` → translated text.
  * `to_speech(text, tgt)` → WAV bytes → the same `_juno_say` path Piper uses.

When transformers/torch/the model is absent, `available` is False, `to_text`
returns "" and `to_speech` returns None — so the caller behaves exactly as today.
"""
from __future__ import annotations

import io
import logging
import wave
from typing import Any, Callable, Optional, Tuple

log = logging.getLogger("dreamlayer.rosetta_seamless")

_MODEL = "facebook/seamless-m4t-v2-large"
_SR = 16000                      # SeamlessM4T works at 16 kHz mono

# RosettaLens speaks 2-letter codes; SeamlessM4T wants 3-letter ISO-639-3.
_LANG3 = {
    "en": "eng", "es": "spa", "fr": "fra", "de": "deu", "it": "ita",
    "pt": "por", "nl": "nld", "ja": "jpn", "zh": "cmn", "ko": "kor",
    "ar": "arb", "ru": "rus", "hi": "hin", "el": "ell", "he": "heb",
    "tr": "tur", "vi": "vie", "th": "tha", "pl": "pol", "uk": "ukr",
}


def _lang3(code: str) -> str:
    c = (code or "en").strip().lower()
    return _LANG3.get(c, _LANG3.get(c[:2], "eng"))


def _has_transformers() -> bool:
    try:
        import transformers  # noqa: F401
        return True
    except Exception:
        return False


def _to_mono16k(audio, sample_rate: int):
    """Coerce arbitrary audio to a float32 mono ndarray at 16 kHz in [-1, 1], or
    None. Linear resample keeps this dependency-light (no torchaudio needed)."""
    try:
        import numpy as np
        raw = np.asarray(audio)
        is_int = np.issubdtype(raw.dtype, np.integer)
        a = raw.astype(np.float32)
        if a.size == 0:
            return None
        if a.ndim == 2:                          # stereo → mono: collapse the
            a = a.mean(axis=1) if a.shape[1] <= a.shape[0] else a.mean(axis=0)
        a = a.reshape(-1)
        # integer PCM → scale by its own full-scale; a float array is assumed
        # already in [-1, 1] UNLESS its peak is far beyond any real float mic
        # signal (hundreds+), which means int16 values were handed in as float
        # (refute 2026-07-21: a plain peak>1.5 test wrecked legitimately-hot float).
        if is_int:
            info = np.iinfo(raw.dtype)
            a = a / float(max(abs(int(info.min)), int(info.max)))
        elif a.size and float(np.max(np.abs(a))) > 32.0:
            a = a / 32768.0
        sr = int(sample_rate or _SR)
        if sr != _SR and a.size:
            n_out = int(round(a.size * _SR / sr))
            if n_out <= 0:
                return None
            xp = np.linspace(0.0, 1.0, num=a.size, endpoint=False)
            xq = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
            a = np.interp(xq, xp, a).astype(np.float32)
        return np.clip(a, -1.0, 1.0)
    except Exception as exc:                     # noqa: BLE001
        log.debug("[interpret] audio coerce failed: %s", exc)
        return None


def _wav_bytes(samples, rate: int) -> Optional[bytes]:
    """float [-1,1] mono → self-describing 16-bit WAV bytes."""
    try:
        import numpy as np
        pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
               * 32767.0).astype("<i2").tobytes()
        if not pcm:
            return None
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(int(rate or _SR))
            wf.writeframes(pcm)
        return buf.getvalue()
    except Exception as exc:                     # noqa: BLE001
        log.error("[interpret] wav encode failed: %s", exc)
        return None


class SeamlessInterpreter:
    """Wrap SeamlessM4T-v2. `available` reflects only the wheel; `ready` is True
    once the (large) model+processor have actually loaded. Loading is lazy — the
    first call pays for it — so importing this module is cheap."""

    dep = "transformers"
    available = _has_transformers()

    def __init__(self, model: str = _MODEL):
        self._model_name = model
        self._model: Any = None
        self._proc: Any = None
        self._loaded = False

    def _load(self) -> bool:
        if self._loaded:
            return self._model is not None
        self._loaded = True
        if not self.available:
            return False
        try:
            from transformers import (AutoProcessor,  # type: ignore
                                       SeamlessM4Tv2Model)
            self._proc = AutoProcessor.from_pretrained(self._model_name)
            self._model = SeamlessM4Tv2Model.from_pretrained(self._model_name)
        except Exception as exc:                 # noqa: BLE001 — torch/model/sentencepiece absent
            log.info("[interpret] SeamlessM4T load failed: %s; interpreter off", exc)
            self._model = self._proc = None
        return self._model is not None

    @property
    def ready(self) -> bool:
        return self._load()

    def to_text(self, audio, sample_rate: int = _SR, tgt_lang: str = "en") -> str:
        """Someone's speech → its meaning as text in `tgt_lang` (S2TT). "" when
        unavailable or on any failure — never raises into the capture loop."""
        if not self._load():
            return ""
        mono = _to_mono16k(audio, sample_rate)
        if mono is None:
            return ""
        try:
            inp = self._proc(audios=mono, sampling_rate=_SR, return_tensors="pt")
            toks = self._model.generate(**inp, tgt_lang=_lang3(tgt_lang),
                                        generate_speech=False)
            seq = toks[0].tolist()[0] if not isinstance(toks, (list, tuple)) \
                else toks[0]
            return str(self._proc.decode(seq, skip_special_tokens=True)).strip()
        except Exception as exc:                 # noqa: BLE001
            log.error("[interpret] speech→text failed: %s", exc)
            return ""

    def to_speech(self, text: str, tgt_lang: str,
                  src_lang: str = "en") -> Optional[bytes]:
        """Your reply text → speech in `tgt_lang` (T2ST) as WAV bytes for the
        _juno_say path, or None when unavailable."""
        text = (text or "").strip()
        if not text or not self._load():
            return None
        try:
            import numpy as np
            inp = self._proc(text=text, src_lang=_lang3(src_lang),
                             return_tensors="pt")
            out = self._model.generate(**inp, tgt_lang=_lang3(tgt_lang))
            wav = np.asarray(out[0].cpu().numpy().squeeze(), dtype=np.float32)
            rate = int(getattr(self._model.config, "sampling_rate", _SR) or _SR)
            return _wav_bytes(wav, rate)
        except Exception as exc:                 # noqa: BLE001
            log.error("[interpret] text→speech failed: %s", exc)
            return None


def make_interpret_fn(model: str = _MODEL) -> Callable[..., str]:
    """A ready-to-wire `hear(audio, sample_rate=16000, target="en") -> str`
    callable for `RosettaLens(interpret_fn=...)` (mirrors make_translate_fn). When
    SeamlessM4T is absent the callable returns "" (Rosetta then no-ops the ear),
    and `.ready` is False so a caller can gate on it."""
    interp = SeamlessInterpreter(model)

    def hear(audio, sample_rate: int = _SR, target: str = "en") -> str:
        return interp.to_text(audio, sample_rate, target)

    # readiness is resolved lazily on first real use; expose the wheel presence
    # now so wiring code can decide whether to bother.
    hear.ready = SeamlessInterpreter.available     # type: ignore[attr-defined]
    hear.interpreter = interp                      # type: ignore[attr-defined]
    return hear


def default_interpreter(model: str = _MODEL) -> Optional[SeamlessInterpreter]:
    """The interpreter when the wheel is present, else None (so `_juno_say`'s
    reverse T2ST path stays off exactly as today)."""
    it = SeamlessInterpreter(model)
    return it if it.available else None


def _codes() -> Tuple[str, ...]:
    """The 2-letter languages this interpreter maps (for tests/introspection)."""
    return tuple(_LANG3.keys())
