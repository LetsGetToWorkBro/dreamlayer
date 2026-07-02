"""ai_brain/server/backends.py — the model backend (Ollama on the Mac mini).

The Brain's smarts are pluggable. Default is keyword-only (no model, works
everywhere). Point it at Ollama and it gains a chat model (to write answers
from retrieved passages) and a vision model (to explain what you look at).

OllamaBackend speaks Ollama's local HTTP API; `http_post(url, payload)` is
injectable so it's testable without Ollama running.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Callable, Optional

from ..schema import Answer


def _urllib_post(url: str, payload: dict, timeout: float = 30.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class OllamaBackend:
    """Chat + vision + embeddings via a local Ollama server."""

    def __init__(self, config, http_post: Optional[Callable] = None,
                 timeout: float = 30.0):
        self.config = config
        self._post = http_post or (lambda u, p: _urllib_post(u, p, timeout))

    def _gen(self, model: str, prompt: str, images=None) -> str:
        payload = {"model": model, "prompt": prompt, "stream": False}
        if images:
            payload["images"] = images
        out = self._post(self.config.ollama_url.rstrip("/") + "/api/generate",
                         payload)
        return (out or {}).get("response", "").strip()

    def chat(self, prompt: str) -> str:
        return self._gen(self.config.ollama_chat_model, prompt)

    def vision(self, label: str, image_b64: Optional[str], want: str) -> str:
        detail = "one rich, useful sentence" if want == "more" else "a few words"
        prompt = (f"You are looking at what appears to be a {label}. In "
                  f"{detail}, say what it is and the single most useful thing "
                  f"to know about it. Be concrete.")
        imgs = [image_b64] if image_b64 else None
        return self._gen(self.config.ollama_vision_model, prompt, images=imgs)


def make_synthesizer(backend: OllamaBackend) -> Callable:
    """Turn retrieved passages into a written answer via the chat model."""
    def synth(query: str, passages: list[tuple[str, str]]) -> str:
        context = "\n\n".join(f"[{name}] {text}" for name, text in passages)
        prompt = (f"Answer the question using only the notes below. Cite "
                  f"nothing you can't see. If they don't answer it, say so.\n\n"
                  f"Notes:\n{context}\n\nQuestion: {query}\nAnswer:")
        return backend.chat(prompt)
    return synth


def vision_answer(backend: Optional[OllamaBackend], label: str,
                  image_b64: Optional[str], want: str) -> Optional[Answer]:
    """Explain an object. With no backend, return None (the tier declines)."""
    if backend is None:
        return None
    try:
        text = backend.vision(label, image_b64, want)
    except Exception:
        return None
    if not text:
        return None
    return Answer(text=text, tier="laptop", sources=["vision"], confidence=0.7)
