"""ai_brain/server/backends.py — the model backend (Ollama on the Mac mini).

The Brain's smarts are pluggable. Default is keyword-only (no model, works
everywhere). Point it at Ollama and it gains a chat model (to write answers
from retrieved passages) and a vision model (to explain what you look at).

OllamaBackend speaks Ollama's local HTTP API; `http_post(url, payload)` is
injectable so it's testable without Ollama running.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Callable, Optional

from ..schema import Answer


# Cloud providers the panel offers. `wire` is the on-the-wire format the
# adapter speaks; `base_url`/`model` are pre-fills the panel suggests (still
# user-editable). `needs_key` drives whether the panel shows the API-key field
# — Ollama runs locally with no key (free + private).
PROVIDER_PRESETS: dict[str, dict] = {
    "openai": {
        "label": "OpenAI", "base_url": "https://api.openai.com",
        "model": "gpt-4o-mini", "needs_key": True, "wire": "openai"},
    "anthropic": {
        "label": "Anthropic", "base_url": "https://api.anthropic.com",
        "model": "claude-3-5-haiku-latest", "needs_key": True, "wire": "anthropic"},
    "gemini": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "model": "gemini-1.5-flash", "needs_key": True, "wire": "gemini"},
    "openrouter": {
        "label": "OpenRouter", "base_url": "https://openrouter.ai/api",
        "model": "openai/gpt-4o-mini", "needs_key": True, "wire": "openai"},
    "ollama": {
        "label": "Ollama · local", "base_url": "http://localhost:11434",
        "model": "llama3.2", "needs_key": False, "wire": "openai"},
    "custom": {
        "label": "Custom (OpenAI-compatible)", "base_url": "",
        "model": "", "needs_key": True, "wire": "openai"},
}


def _build_cloud_request(config, prompt: str):
    """Return (wire, url, body_dict, headers) for the configured provider.

    Three wire formats, all hand-rolled (no SDK): OpenAI-compatible chat
    completions (openai/openrouter/ollama/custom), Anthropic messages, and
    Gemini generateContent. Pure — unit-testable without a network.
    """
    provider = getattr(config, "cloud_provider", "openai") or "openai"
    preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["custom"])
    wire = preset["wire"]
    base = (config.cloud_base_url or preset["base_url"]).rstrip("/")
    model = config.cloud_model
    key = config.cloud_api_key or ""
    if wire == "anthropic":
        url = base + "/v1/messages"
        body = {"model": model, "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}]}
        headers = {"Content-Type": "application/json", "x-api-key": key,
                   "anthropic-version": "2023-06-01"}
    elif wire == "gemini":
        url = (f"{base}/v1beta/models/{model}:generateContent"
               f"?key={urllib.parse.quote(key)}")
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        headers = {"Content-Type": "application/json"}
    else:  # openai-compatible
        url = base + "/v1/chat/completions"
        body = {"model": model,
                "messages": [{"role": "user", "content": prompt}]}
        headers = {"Content-Type": "application/json"}
        if key:  # Ollama-local sends no key
            headers["Authorization"] = "Bearer " + key
    return wire, url, body, headers


def _parse_cloud_response(wire: str, d: dict) -> str:
    """Pull the answer text out of a provider's JSON response."""
    if wire == "anthropic":
        parts = d.get("content") or []
        return "".join(p.get("text", "") for p in parts
                       if isinstance(p, dict)).strip()
    if wire == "gemini":
        cands = d.get("candidates") or [{}]
        parts = ((cands[0].get("content") or {}).get("parts")) or [{}]
        return "".join(p.get("text", "") for p in parts
                       if isinstance(p, dict)).strip()
    choices = d.get("choices") or [{}]
    return ((choices[0].get("message") or {}).get("content") or "").strip()


def _urllib_post(url: str, payload: dict, timeout: float = 30.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _urllib_get(url: str, timeout: float = 4.0) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(urllib.request.Request(url), timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def probe_ollama(config, timeout: float = 4.0) -> dict:
    """Is Ollama up, and which of the configured models are pulled?

    Returns {reachable, url, models, want, have} so the panel can show a live
    setup status per model instead of failing silently.
    """
    url = (getattr(config, "ollama_url", "") or "http://127.0.0.1:11434").rstrip("/")
    want = {"chat":   getattr(config, "ollama_chat_model", "") or "",
            "vision": getattr(config, "ollama_vision_model", "") or "",
            "embed":  getattr(config, "ollama_embed_model", "") or ""}
    try:
        data = _urllib_get(url + "/api/tags", timeout)
        names = [m.get("name", "") for m in (data.get("models") or [])]
    except Exception:
        return {"reachable": False, "url": url, "models": [], "want": want,
                "have": {k: False for k in want}}

    def present(name: str) -> bool:
        if not name:
            return False
        base = name.split(":")[0]
        return any(n == name or n.split(":")[0] == base for n in names)

    return {"reachable": True, "url": url, "models": names, "want": want,
            "have": {k: present(v) for k, v in want.items()}}


def pull_model(config, name: str, poster: Optional[Callable[[str, dict, float], dict]] = None
               ) -> dict:
    """Pull an Ollama model by name via the local HTTP API (no CLI needed).

    Blocking; Ollama streams progress but we wait for completion. `poster` is
    injectable for tests. Returns {ok, status, model}.
    """
    name = (name or "").strip()
    if not name:
        return {"ok": False, "status": "no model name", "model": ""}
    url = (getattr(config, "ollama_url", "") or "http://127.0.0.1:11434").rstrip("/")
    post = poster or (lambda u, p, t: _urllib_post(u, p, t))
    try:
        # stream:false makes Ollama return once the pull finishes
        res = post(url + "/api/pull", {"name": name, "stream": False}, 1800.0)
    except Exception as e:
        return {"ok": False, "status": f"could not reach Ollama: {e}", "model": name}
    status = (res or {}).get("status", "")
    ok = status == "success" or "success" in str(status).lower()
    return {"ok": ok, "status": status or "unknown", "model": name}


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

    def embed(self, text: str) -> list:
        out = self._post(self.config.ollama_url.rstrip("/") + "/api/embeddings",
                         {"model": self.config.ollama_embed_model, "prompt": text})
        return (out or {}).get("embedding", []) or []


def cloud_chat(config, prompt: str, http_post: Optional[Callable] = None,
               timeout: float = 30.0) -> str:
    """Ask the configured cloud model. Supports OpenAI, Anthropic, Gemini,
    OpenRouter, Ollama-local, and any custom OpenAI-compatible endpoint —
    dispatched on config.cloud_provider. The call is injectable for tests."""
    if http_post is not None:
        out = http_post(config.cloud_base_url, {"model": config.cloud_model,
                                                "prompt": prompt})
        return (out or {}).get("text", "").strip()
    wire, url, body, headers = _build_cloud_request(config, prompt)
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        d = json.loads(resp.read().decode("utf-8"))
    return _parse_cloud_response(wire, d)


def cloud_test(config, http_post: Optional[Callable] = None) -> dict:
    """A tiny round-trip so the panel can say 'connected' or show the error."""
    try:
        txt = cloud_chat(config, "Reply with the single word: OK",
                         http_post=http_post, timeout=15.0)
        return {"ok": bool(txt), "reply": txt[:80]}
    except Exception as e:  # noqa: BLE001 — surface any provider error verbatim
        return {"ok": False, "error": str(e)[:200]}


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
