"""Silero VAD gate — decide whether an audio window contains speech BEFORE any
downstream compute ("always-on" without "always-draining").

ADD-alongside: new module. NOTE (from exploration): the Python host currently
receives already-transcribed text — there is no in-process ASR to gate. This
gate is therefore a boundary utility: wire it at the audio-capture edge (e.g.
around orchestrator.on_audio_frame's mic arrays) or in a future capture path.
Lazy-imports silero-vad (extras group `voice`); when absent it falls back to a
cheap energy-threshold VAD so callers always get a decision.
"""
from __future__ import annotations
import logging

log = logging.getLogger("dreamlayer.vad_gate")

try:  # optional dep — extras group `voice`
    from silero_vad import load_silero_vad, get_speech_timestamps  # type: ignore
    _HAS_SILERO = True
except ImportError:
    _HAS_SILERO = False


class SileroVADGate:
    """`is_speech(samples)` on a mono 16k float/int PCM window.

    Parameters
    ----------
    threshold : float
        Energy fallback threshold (RMS) used when silero-vad is unavailable.
    """
    available = _HAS_SILERO

    def __init__(self, sample_rate: int = 16000, threshold: float = 0.02):
        self.sample_rate = sample_rate
        self.threshold = threshold
        self._model = None
        if _HAS_SILERO:
            try:
                self._model = load_silero_vad()
            except Exception as exc:
                log.error("[vad_gate] silero load failed: %s; energy fallback", exc)
                self._model = None

    def is_speech(self, samples) -> bool:
        if self._model is not None:
            try:
                import torch
                t = samples if hasattr(samples, "dim") else torch.tensor(samples, dtype=torch.float32)
                ts = get_speech_timestamps(t, self._model, sampling_rate=self.sample_rate)
                return len(ts) > 0
            except Exception as exc:
                log.error("[vad_gate] silero infer failed: %s; energy fallback", exc)
        return self._energy(samples)

    def _energy(self, samples) -> bool:
        vals = list(samples) if not isinstance(samples, (list, tuple)) else samples
        if not vals:
            return False
        # normalize ints to [-1,1] if needed
        peak = max(abs(float(v)) for v in vals) or 1.0
        scale = 1.0 if peak <= 1.0 else peak
        rms = (sum((float(v) / scale) ** 2 for v in vals) / len(vals)) ** 0.5
        return rms >= self.threshold
