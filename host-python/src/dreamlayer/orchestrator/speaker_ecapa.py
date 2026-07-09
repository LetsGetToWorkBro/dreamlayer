"""ECAPA-TDNN speaker embeddings (speechbrain) — 192-d voice vectors that let
the host learn who is speaking and feed UserModel.observe(speaker=...).

ADD-alongside: new module (user_model.py untouched). Lazy-imports speechbrain
(extras group `intelligence`); when absent, `embed()` returns a deterministic
hash-based 192-d vector so speaker bookkeeping still works offline/for tests.
"""
from __future__ import annotations
import hashlib
import logging
import math

log = logging.getLogger("dreamlayer.speaker_ecapa")

try:
    from speechbrain.inference.speaker import EncoderClassifier  # type: ignore
    _HAS_SB = True
except ImportError:
    _HAS_SB = False

DIM = 192


class ECAPASpeaker:
    available = _HAS_SB

    def __init__(self):
        self._model = None
        if _HAS_SB:
            try:
                self._model = EncoderClassifier.from_hparams(
                    source="speechbrain/spkrec-ecapa-voxceleb")
            except Exception as exc:
                log.error("[ecapa] load failed: %s; hash fallback", exc)
                self._model = None

    def embed(self, audio, key: str | None = None) -> list[float]:
        """Return a 192-d speaker embedding. `audio` = waveform/path when the
        model is present; `key` = a stable id used by the deterministic fallback
        (e.g. a transcript or speaker label)."""
        if self._model is not None:
            try:
                import torch
                sig = audio if hasattr(audio, "dim") else torch.tensor(audio)
                vec = self._model.encode_batch(sig).squeeze().tolist()
                return [float(x) for x in vec][:DIM]
            except Exception as exc:
                log.error("[ecapa] encode failed: %s; hash fallback", exc)
        return self._hash_vec(key or (str(audio)[:64]))

    @staticmethod
    def _hash_vec(key: str) -> list[float]:
        vec = [0.0] * DIM
        for i, tok in enumerate((key or "").split() or [key or ""]):
            h = int(hashlib.md5(f"{i}:{tok}".encode()).hexdigest(), 16)
            vec[h % DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    @staticmethod
    def similarity(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))
