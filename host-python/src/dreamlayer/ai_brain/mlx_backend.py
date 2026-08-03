"""ai_brain/mlx_backend.py — the answer path on Apple Silicon, natively.

The Brain runs on a Mac mini, and Apple's MLX is the first-party inference path
for that hardware — independent benchmarks put MLX ~30–50% faster than
llama.cpp for the 3B–8B models you'd actually run on a mini, at lower power,
because it's built on Apple's own Metal pipeline (WWDC'25 positioned MLX as the
preferred on-device LLM path).

This is a drop-in for OllamaBackend's ``chat(prompt)`` contract, so it slots
straight into ``make_synthesizer`` and the ``ask`` path. It is **Apple-only**:
``available`` is False off macOS or when ``mlx-lm`` isn't installed, and the
server keeps using Ollama/cloud exactly as before. The model loads lazily on
first use; a load or generate failure degrades to an empty string (the tier
declines) so a backend error never breaks an answer — same contract as every
other seam.

    from dreamlayer.ai_brain.mlx_backend import MLXBackend
    b = MLXBackend(config)                 # available only on Apple Silicon
    b.chat("summarize my week")            # -> str (or "" when unavailable)
"""
from __future__ import annotations

import logging
import sys

log = logging.getLogger("dreamlayer.mlx_backend")

_IS_DARWIN = sys.platform == "darwin"
try:
    import mlx_lm  # type: ignore  # noqa: F401
    _HAS_MLX_LM = True
except Exception:
    mlx_lm = None                          # type: ignore
    _HAS_MLX_LM = False

DEFAULT_MODEL = "mlx-community/Llama-3.2-3B-Instruct-4bit"


class MLXBackend:
    """MLX-LM chat backend. Reads ``mlx_model`` and ``mlx_max_tokens`` off the
    config (duck-typed). Apple-Silicon only; degrades to "" when unavailable."""

    available = _HAS_MLX_LM and _IS_DARWIN

    def __init__(self, config=None, _generate=None):
        self.config = config
        self._model_name = (getattr(config, "mlx_model", "") or DEFAULT_MODEL)
        self._max_tokens = int(getattr(config, "mlx_max_tokens", 512) or 512)
        self._model = None
        self._tokenizer = None
        #: Whether the loaded model has the wearer's own LoRA on it. Read by the
        #: status surface, so "the adapter trained" and "the adapter is being
        #: used" stay separable — they are different claims and the second is
        #: the one that changes an answer.
        self.adapter_loaded = False
        # inject a (model, tokenizer, prompt, max_tokens) -> str in tests
        self._generate = _generate

    def adapter_path(self):
        """The wearer's trained adapter, or None.

        Returns a path only when weights are ACTUALLY on disk. `mlx_lm.load`
        raises on an adapter directory that holds nothing, so handing it a
        configured-but-empty path would take the whole MLX tier down — the
        answer path — over an overnight job that has not run yet. A missing
        adapter is the normal state and must cost nothing.
        """
        from pathlib import Path
        raw = (getattr(self.config, "mlx_adapter_dir", "") or "").strip()
        if not raw:
            return None
        d = Path(raw).expanduser()
        try:
            if any(d.glob("*.safetensors")):
                return str(d)
        except OSError:
            pass
        return None

    def _ensure(self) -> bool:
        if self._generate is not None:
            return True
        if self._model is not None:
            return True
        if not self.available:
            return False
        adapter = self.adapter_path()
        try:                               # pragma: no cover - Apple-only path
            if adapter:
                self._model, self._tokenizer = mlx_lm.load(
                    self._model_name, adapter_path=adapter)
                self.adapter_loaded = True
            else:
                self._model, self._tokenizer = mlx_lm.load(self._model_name)
            return True
        except Exception as exc:           # pragma: no cover
            if adapter:
                # A bad adapter must not cost the wearer their local model.
                # Retry BARE once: a stale LoRA (trained against a different
                # base, or half-written by a killed run) is a recoverable
                # nuisance, and refusing to answer at all because last night's
                # job produced something odd is not.
                log.error("[mlx] adapter load failed: %s; base model only", exc)
                self.adapter_loaded = False
                try:
                    self._model, self._tokenizer = mlx_lm.load(self._model_name)
                    return True
                except Exception as exc2:
                    log.error("[mlx] model load failed: %s", exc2)
                    return False
            log.error("[mlx] model load failed: %s", exc)
            return False

    def chat(self, prompt: str) -> str:
        if not self._ensure():
            return ""
        try:
            if self._generate is not None:
                return str(self._generate(self._model, self._tokenizer,
                                          prompt, self._max_tokens) or "").strip()
            # pragma: no cover - Apple-only path
            out = mlx_lm.generate(self._model, self._tokenizer, prompt=prompt,
                                  max_tokens=self._max_tokens, verbose=False)
            return str(out or "").strip()
        except Exception as exc:
            log.error("[mlx] generate failed: %s", exc)
            return ""

    def vision(self, label, image_b64, want) -> str:
        # vision runs through the object-lens classifier ladder (mlx-vlm), not
        # the text LLM; the text backend declines vision so the caller falls
        # back to its vision tier.
        return ""

    def describe(self, prompt, image_b64) -> str:
        # same posture as .vision: the MLX *text* backend does not read images —
        # the World Lens recognizer's own classifier ladder (mlx-vlm) does. Return
        # "" so the recognizer falls back to its dependency-free heuristic.
        return ""

    def embed(self, text: str) -> list:
        # embeddings run through the embedder ladder (Local/Static/Hashing);
        # the MLX text backend does not serve them.
        return []
