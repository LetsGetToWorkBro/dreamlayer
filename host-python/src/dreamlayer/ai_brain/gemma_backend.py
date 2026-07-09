"""ai_brain/gemma_backend.py — a Gemma chat backend over the local Ollama API.

ADD-alongside: `ai_brain/server/backends.py` (OllamaBackend, cloud_chat,
PROVIDER_PRESETS) is untouched. Gemma runs locally through Ollama, so this is a
thin wrapper that pins the Ollama chat model to a Gemma tag and otherwise reuses
the existing, injectable `http_post` transport — no new hard dependency.

Fallback: the transport is injectable (`http_post(url, payload)->dict`), so with
no reachable Ollama server the call returns "" rather than raising, and the host
tier that owns it can decline gracefully — exactly like OllamaBackend.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

log = logging.getLogger("dreamlayer.gemma_backend")

DEFAULT_GEMMA_MODEL = "gemma2"


class GemmaBackend:
    """Chat via a local Gemma model served by Ollama. `model` overrides the tag
    (e.g. 'gemma2:2b'). `http_post(url, payload)->dict` is injectable for tests
    and for pointing at a remote Ollama host."""

    def __init__(self, config=None, http_post: Optional[Callable] = None,
                 model: str = DEFAULT_GEMMA_MODEL, timeout: float = 30.0):
        self.config = config
        self.model = model
        self._timeout = timeout
        self._post = http_post

    def _ollama_url(self) -> str:
        base = getattr(self.config, "ollama_url", None) or "http://127.0.0.1:11434"
        return base.rstrip("/") + "/api/generate"

    def _poster(self) -> Callable:
        if self._post is not None:
            return self._post
        # Lazy default transport reuses backends' urllib helper.
        from .server.backends import _urllib_post
        return lambda u, p: _urllib_post(u, p, self._timeout)

    def chat(self, prompt: str) -> str:
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        try:
            out = self._poster()(self._ollama_url(), payload)
        except Exception as exc:
            log.warning("[gemma] chat transport failed: %s", exc)
            return ""
        return (out or {}).get("response", "").strip()
