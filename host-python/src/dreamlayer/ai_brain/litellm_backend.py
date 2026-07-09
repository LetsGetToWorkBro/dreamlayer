"""LiteLLM unified backend — one call over OpenAI + Anthropic + Gemini + Ollama
+ 100 more, matching the existing hand-rolled cloud dispatch.

ADD-alongside: new sibling. server/backends.py (cloud_chat, PROVIDER_PRESETS,
OllamaBackend) is untouched. `litellm_chat` has the same (config, prompt)
surface as backends.cloud_chat; it lazy-imports litellm (extras group `llm`)
and, when absent or on any error, delegates to the existing cloud_chat — so the
three-switch architecture keeps working with zero new deps.
"""
from __future__ import annotations
import logging

from .server.backends import cloud_chat as _builtin_cloud_chat

log = logging.getLogger("dreamlayer.litellm_backend")

try:  # optional dep — extras group `llm`
    import litellm  # type: ignore
    _HAS_LITELLM = True
except ImportError:
    _HAS_LITELLM = False

available = _HAS_LITELLM


def _model_for(config) -> str:
    """Map the config's provider/model to a litellm model string."""
    provider = (getattr(config, "cloud_provider", "") or "openai").lower()
    model = getattr(config, "cloud_model", "") or "gpt-4o-mini"
    if provider in ("openai", "openrouter", "custom"):
        return model if "/" not in model or provider == "openrouter" else model
    if provider == "anthropic":
        return model if model.startswith("anthropic/") else f"anthropic/{model}"
    if provider == "gemini":
        return model if model.startswith("gemini/") else f"gemini/{model}"
    if provider == "ollama":
        return model if model.startswith("ollama/") else f"ollama/{model}"
    return model


def litellm_chat(config, prompt: str, http_post=None, timeout: float = 30.0) -> str:
    """Same contract as backends.cloud_chat(config, prompt). Falls back to the
    built-in dispatch when litellm isn't installed or errors."""
    if not _HAS_LITELLM:
        return _builtin_cloud_chat(config, prompt, http_post=http_post, timeout=timeout)
    try:
        api_key = getattr(config, "cloud_api_key", "") or None
        base_url = getattr(config, "cloud_base_url", "") or None
        resp = litellm.completion(
            model=_model_for(config),
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
            api_base=base_url,
            timeout=timeout,
        )
        return (resp["choices"][0]["message"]["content"] or "").strip()
    except Exception as exc:
        log.error("[litellm] call failed: %s; built-in dispatch fallback", exc)
        return _builtin_cloud_chat(config, prompt, http_post=http_post, timeout=timeout)
