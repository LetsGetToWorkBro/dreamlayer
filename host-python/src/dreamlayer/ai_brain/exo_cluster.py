"""ai_brain/exo_cluster.py — run the knowledge/vision model on an exo cluster.

exo (exo-explore/exo) stitches a handful of everyday machines into one
OpenAI-compatible inference endpoint, so a big model runs across the devices you
already own. This adapter speaks that endpoint.

ADD-alongside: `ai_brain/server/backends.py` is untouched. Same shape as
OllamaBackend/cloud_chat — `chat(prompt)->str` over an injectable
`http_post(url, payload)->dict`. exo is a runtime service (not a pip dep), so
there is nothing to import; the "fallback" is the transport declining: with no
reachable cluster the call returns "" and the owning tier moves on.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

log = logging.getLogger("dreamlayer.exo_cluster")

DEFAULT_EXO_URL = "http://127.0.0.1:52415"    # exo's default ChatGPT-API port


class ExoClusterBackend:
    """Chat via an exo cluster's OpenAI-compatible /v1/chat/completions.
    `http_post(url, payload)->dict` is injectable for tests and remote hosts."""

    def __init__(self, base_url: str = DEFAULT_EXO_URL,
                 model: str = "llama-3.2-3b", http_post: Optional[Callable] = None,
                 timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._timeout = timeout
        self._post = http_post

    def _poster(self) -> Callable:
        if self._post is not None:
            return self._post
        from .server.backends import _urllib_post
        return lambda u, p: _urllib_post(u, p, self._timeout)

    def chat(self, prompt: str) -> str:
        url = self.base_url + "/v1/chat/completions"
        payload = {"model": self.model,
                   "messages": [{"role": "user", "content": prompt}]}
        try:
            out = self._poster()(url, payload) or {}
        except Exception as exc:
            log.warning("[exo] chat transport failed: %s", exc)
            return ""
        try:
            return out["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError, AttributeError):
            # Some exo builds return a plain {"text": ...}
            return str(out.get("text", "")).strip()

    def available(self, http_get: Optional[Callable] = None) -> bool:
        """Best-effort reachability probe; never raises."""
        getter = http_get
        if getter is None:
            try:
                from .server.backends import _urllib_get
                getter = lambda u: _urllib_get(u, 3.0)
            except Exception:
                return False
        try:
            getter(self.base_url + "/v1/models")
            return True
        except Exception:
            return False
