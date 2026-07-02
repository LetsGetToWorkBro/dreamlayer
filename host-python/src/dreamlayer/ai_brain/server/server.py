"""ai_brain/server/server.py — the Brain server (runs on your Mac mini).

Serves the control panel and the API the phone and the panel both call:

    GET  /                          control panel
    GET  /dreamlayer/config         config (token-safe) + index stats
    POST /dreamlayer/config         update model / connections
    POST /dreamlayer/folders        {action: add|remove, path}  → reindex
    POST /dreamlayer/upload?folder=&name=   drag-drop a file in → reindex
    POST /dreamlayer/brain/ask      {query} → Answer (logged to history)
    POST /dreamlayer/brain/explain  {label, image?, want?} → Answer
    GET  /dreamlayer/history        recent questions

All /dreamlayer/* calls require the pairing token (when one is set); the
panel page is injected with the token only when opened from localhost.
"""
from __future__ import annotations

import json
import urllib.parse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

import threading
import time

from ..schema import Answer
from .store import BrainConfig, QueryHistory
from .index import FileIndex
from .backends import OllamaBackend, make_synthesizer, vision_answer
from .macos_sources import collect_documents
from .panel import render_panel

TOKEN_HEADER = "X-DreamLayer-Token"


class Brain:
    """The Brain's live state: config + index + history, rebuilt on change."""

    def __init__(self, cfg_dir: Path | str, sources_fn=None):
        self.cfg_dir = Path(cfg_dir)
        self.config = BrainConfig.load(self.cfg_dir)
        self.history = QueryHistory(self.cfg_dir)
        self.index = FileIndex(self.config)
        # macOS message/mail documents (folded in when email is enabled)
        self._sources_fn = sources_fn or collect_documents
        self._sig = None
        self._watch_stop: threading.Event | None = None
        self._wire_model()
        self.reindex()

    def reindex(self) -> dict:
        self.index.reindex()
        if self.config.email_enabled:
            try:
                self.index.add_documents(self._sources_fn(self.config))
            except Exception:
                pass
        self._sig = self._signature()
        return self.index.stats()

    # -- auto-reindex when watched folders change ------------------------

    def _signature(self):
        sig = []
        for folder in self.config.folders:
            base = Path(folder).expanduser()
            if base.is_dir():
                try:
                    for f in base.rglob("*"):
                        if f.is_file():
                            sig.append((str(f), f.stat().st_mtime_ns))
                except OSError:
                    pass
        return tuple(sorted(sig))

    def poll(self) -> bool:
        """Reindex if the watched folders changed since last scan."""
        if self._signature() != self._sig:
            self.reindex()
            return True
        return False

    def start_watching(self, interval: float = 3.0) -> None:
        if self._watch_stop is not None:
            return
        self._watch_stop = threading.Event()

        def loop():
            while not self._watch_stop.wait(interval):
                try:
                    self.poll()
                except Exception:
                    pass
        threading.Thread(target=loop, daemon=True).start()

    def stop_watching(self) -> None:
        if self._watch_stop is not None:
            self._watch_stop.set()
            self._watch_stop = None

    def _wire_model(self) -> None:
        """Point the index/vision at the configured backend."""
        if self.config.model == "ollama":
            self._backend = OllamaBackend(self.config)
            self.index.synthesizer = make_synthesizer(self._backend)
        else:
            self._backend = None
            self.index.synthesizer = None

    def save(self) -> None:
        self.config.save(self.cfg_dir)

    def apply_config(self, updates: dict) -> None:
        for k in ("model", "ollama_url", "ollama_chat_model",
                  "ollama_vision_model", "ollama_embed_model",
                  "email_enabled", "cloud_enabled"):
            if k in updates:
                setattr(self.config, k, updates[k])
        self._wire_model()
        self.save()

    def ask(self, query: str) -> Optional[Answer]:
        ans = self.index.ask(query)
        if ans is not None:
            self.history.add(query, ans.text, ans.tier, ans.sources)
        return ans

    def explain(self, label: str, image_b64, want: str) -> Optional[Answer]:
        return vision_answer(self._backend, label, image_b64, want)


def make_brain_server(brain: Brain, host: str = "127.0.0.1",
                      port: int = 7777) -> ThreadingHTTPServer:
    token = brain.config.token

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        # -- helpers ----------------------------------------------------
        def _json(self, code, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authed(self) -> bool:
            return not token or self.headers.get(TOKEN_HEADER) == token

        def _from_localhost(self) -> bool:
            return self.client_address[0] in ("127.0.0.1", "::1")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(n) if n else b""
            try:
                return json.loads(raw.decode("utf-8")) if raw else {}
            except (ValueError, UnicodeDecodeError):
                return {}

        def _raw(self) -> bytes:
            n = int(self.headers.get("Content-Length", 0) or 0)
            return self.rfile.read(n) if n else b""

        # -- routing ----------------------------------------------------
        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/":
                html = render_panel(token if self._from_localhost() else "")
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if not self._authed():
                self._json(401, {"error": "unauthorised"}); return
            if path == "/dreamlayer/config":
                self._json(200, {"config": brain.config.public(),
                                 "stats": brain.index.stats()})
            elif path == "/dreamlayer/history":
                self._json(200, {"items": brain.history.recent(30)})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
            if not self._authed():
                self._json(401, {"error": "unauthorised"}); return
            if path == "/dreamlayer/folders":
                b = self._body()
                if b.get("action") == "add":
                    brain.config.add_folder(b.get("path", ""))
                elif b.get("action") == "remove":
                    brain.config.remove_folder(b.get("path", ""))
                brain.save(); brain.reindex()
                self._json(200, {"config": brain.config.public(),
                                 "stats": brain.index.stats()})
            elif path == "/dreamlayer/config":
                brain.apply_config(self._body())
                brain.reindex()
                self._json(200, {"config": brain.config.public()})
            elif path == "/dreamlayer/upload":
                folder = (qs.get("folder", [""])[0])
                name = Path(qs.get("name", ["dropped.txt"])[0]).name
                ok = _write_upload(brain, folder, name, self._raw())
                brain.reindex()
                self._json(200 if ok else 400,
                           {"ok": ok, "stats": brain.index.stats()})
            elif path == "/dreamlayer/brain/ask":
                ans = brain.ask(self._body().get("query", ""))
                self._json(200, _answer_json(ans))
            elif path == "/dreamlayer/brain/explain":
                b = self._body()
                ans = brain.explain(b.get("label", ""), b.get("image"),
                                    b.get("want", "quick"))
                self._json(200, _answer_json(ans))
            else:
                self._json(404, {"error": "not found"})

    return ThreadingHTTPServer((host, port), Handler)


def _write_upload(brain: Brain, folder: str, name: str, data: bytes) -> bool:
    # only into a folder the Brain already watches (no arbitrary writes)
    target = str(Path(folder).expanduser())
    if target not in brain.config.folders:
        return False
    dest = Path(target) / name
    try:
        dest.write_bytes(data)
        return True
    except OSError:
        return False


def _answer_json(ans: Optional[Answer]) -> dict:
    if ans is None:
        return {"text": "", "tier": "", "sources": [], "confidence": 0.0}
    return {"text": ans.text, "tier": ans.tier, "sources": ans.sources,
            "confidence": ans.confidence}
