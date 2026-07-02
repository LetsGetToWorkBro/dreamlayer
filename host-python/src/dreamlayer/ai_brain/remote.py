"""ai_brain/remote.py — phone-side clients for the Mac mini Brain.

These are the Tier-2 (laptop) brains: they POST to the Brain server's
/dreamlayer/brain/* endpoints and hand the answer back to the router. Wrap
them in nothing special — the router already prefers them below cloud and
above nothing. `http_post(url, payload, headers)` is injectable for tests.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Callable, Optional

from .schema import Answer

TOKEN_HEADER = "X-DreamLayer-Token"


def _urllib_post(url: str, payload: dict, headers: dict,
                 timeout: float = 30.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    h = {"Content-Type": "application/json", **headers}
    req = urllib.request.Request(url, data=data, headers=h)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class _RemoteBrain:
    tier = "laptop"
    is_cloud = False
    is_remote = True             # reachable over the network, not on-device

    def __init__(self, base_url: str, token: str = "",
                 http_post: Optional[Callable] = None, timeout: float = 30.0):
        self._url = base_url.rstrip("/")
        self._headers = {TOKEN_HEADER: token} if token else {}
        self._post = http_post or (lambda u, p, h: _urllib_post(u, p, h, timeout))

    def _call(self, path: str, payload: dict) -> Optional[Answer]:
        try:
            out = self._post(self._url + path, payload, self._headers) or {}
        except Exception:
            return None
        text = (out.get("text") or "").strip()
        if not text:
            return None
        return Answer(text=text, tier=out.get("tier") or self.tier,
                      sources=out.get("sources") or [],
                      confidence=float(out.get("confidence") or 0.0))


class RemoteKnowledgeBrain(_RemoteBrain):
    def ask(self, query: str) -> Optional[Answer]:
        return self._call("/dreamlayer/brain/ask", {"query": query})


class RemoteVisionBrain(_RemoteBrain):
    def __init__(self, base_url, token="", http_post=None, timeout=30.0,
                 encode_frame: Optional[Callable] = None):
        super().__init__(base_url, token, http_post, timeout)
        # encode_frame(frame) -> base64 JPEG string; without it, the Brain
        # explains from the label alone (still useful, less precise).
        self._encode = encode_frame

    def explain(self, frame, label: str, want: str = "quick") -> Optional[Answer]:
        payload = {"label": label, "want": want}
        if self._encode is not None and frame is not None:
            try:
                payload["image"] = self._encode(frame)
            except Exception:
                pass
        return self._call("/dreamlayer/brain/explain", payload)


def connect_brain(router, base_url: str, token: str = "",
                  http_post: Optional[Callable] = None,
                  encode_frame: Optional[Callable] = None) -> None:
    """Register the Mac mini Brain as the laptop tier on a router."""
    router.add_vision(RemoteVisionBrain(base_url, token, http_post,
                                        encode_frame=encode_frame))
    router.add_knowledge(RemoteKnowledgeBrain(base_url, token, http_post))
