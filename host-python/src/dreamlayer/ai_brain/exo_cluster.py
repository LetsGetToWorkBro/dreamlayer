"""ai_brain/exo_cluster.py — run the knowledge model on an exo cluster.

exo (exo-explore/exo) stitches a handful of everyday machines into one
OpenAI-compatible inference endpoint, so a big model runs across the devices you
already own. This adapter speaks that endpoint.

Same shape as OllamaBackend — `chat(prompt)->str` over an injectable
`http_post(url, payload)->dict`. exo is a runtime service (not a pip dep), so
there is nothing to import; the "fallback" is the transport declining: with no
reachable cluster the call returns "" and the owning tier moves on.

WHY THIS GREW A POSTURE GATE. For a long time this file was importable and
constructed by nothing but its own test — `capability_reachability.py` reported
the capability as reachable because the module sits in the Brain's import
closure, which answers "can this load", not "does anything use it". Wiring it to
`Brain._wire_model` is what makes the capability real, and the wiring is only
safe with the gate `OllamaBackend._endpoint` already carries, for a sharper
version of the same reason:

  * Ollama is presented as the on-device tier and a remote `ollama_url` quietly
    broke that promise — the wearer's notes left the machine, reported tier
    "laptop", and left the egress counter at 0.
  * exo is a CLUSTER. Reaching another box is not an edge case here, it is the
    entire point of the capability. So the locality check, the veil gate and the
    receipt are not defensive garnish — they are the normal path.

`config` is optional so a bare backend still works, and the gate FAILS CLOSED
when it is absent: with no config there is no posture to read, so a non-local
endpoint is refused rather than reached on a guess. The default endpoint is
loopback, so a bare backend pointed at a local cluster is unaffected.

NO VISION. exo serves `/v1/chat/completions` text; this adapter deliberately
exposes no `vision()`, and `_BrainVisionRouter.has_vision()` tests for the
method rather than for a backend being present, so a look reports honestly
blind instead of raising into a swallowed AttributeError.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

log = logging.getLogger("dreamlayer.exo_cluster")

DEFAULT_EXO_URL = "http://127.0.0.1:52415"    # exo's default ChatGPT-API port
DEFAULT_EXO_MODEL = "llama-3.2-3b"


class ExoClusterBackend:
    """Chat via an exo cluster's OpenAI-compatible /v1/chat/completions.

    `http_post(url, payload)->dict` is injectable for tests and remote hosts.
    `config` (a BrainConfig) supplies the privacy posture; `on_egress(url,
    remote)` is called immediately before a request that leaves this machine so
    the Brain can count and log it.
    """

    def __init__(self, base_url: str = DEFAULT_EXO_URL,
                 model: str = DEFAULT_EXO_MODEL,
                 http_post: Optional[Callable] = None,
                 timeout: float = 60.0, config=None,
                 on_egress: Optional[Callable] = None):
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self._timeout = timeout
        self._post = http_post
        self.config = config
        self._on_egress = on_egress

    def _poster(self) -> Callable:
        if self._post is not None:
            return self._post
        from .server.backends import _urllib_post
        return lambda u, p: _urllib_post(u, p, self._timeout)

    def _note(self, url: str, remote: bool) -> None:
        if self._on_egress is None:
            return
        try:
            self._on_egress(url, remote)
        except TypeError:                    # a 1-arg hook (tests, older callers)
            try:
                self._on_egress(url)
            except Exception:                # noqa: BLE001
                pass
        except Exception:                    # noqa: BLE001 — never break the ask
            pass

    def _endpoint(self, path: str) -> Optional[str]:
        """Resolve a cluster URL, refusing the ones we must not reach.

        Returns None when the request must not be made — which the callers treat
        as "the cluster declined", the same as an unreachable node.
        """
        from .server.backends import (is_blocked_endpoint, is_local_endpoint,
                                      _is_loopback, _posture_forbids_egress)
        url = self.base_url
        if not url:
            return None
        # Link-local / cloud-metadata space is never a model endpoint.
        if is_blocked_endpoint(url):
            log.warning("[exo] endpoint refused: link-local / metadata address")
            return None
        if not is_local_endpoint(url):
            if self.config is None:
                # Fail closed: an off-LAN cluster with no posture to consult.
                log.warning("[exo] refusing a remote endpoint with no posture")
                return None
            if _posture_forbids_egress(self.config):
                return None                  # the shield is up: do not reach out
            self._note(url, remote=True)
        elif not _is_loopback(url):
            # A LAN node is NOT "on your device". That is exactly what an exo
            # cluster is for, and `lan_only` permits it — but the prompt still
            # crossed the room to another computer, so the receipt shows it.
            self._note(url, remote=False)
        return url + path

    def chat(self, prompt: str) -> str:
        url = self._endpoint("/v1/chat/completions")
        if url is None:
            return ""
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
        """Best-effort reachability probe; never raises.

        Gated like `chat`: a probe is a request too, and one that leaks the
        cluster's existence to a remote host while the veil is up would be the
        same failure in a smaller package.
        """
        url = self._endpoint("/v1/models")
        if url is None:
            return False
        getter = http_get
        if getter is None:
            try:
                from .server.backends import _urllib_get
                getter = lambda u: _urllib_get(u, 3.0)   # noqa: E731
            except Exception:
                return False
        try:
            getter(url)
            return True
        except Exception:
            return False
