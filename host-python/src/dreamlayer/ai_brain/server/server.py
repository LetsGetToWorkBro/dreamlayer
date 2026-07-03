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
import socket
import urllib.parse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

import threading
import time

from ..schema import Answer
from .store import BrainConfig, QueryHistory, ActivityLog
from .index import FileIndex
from .backends import OllamaBackend, make_synthesizer, vision_answer, probe_ollama
from .macos_sources import collect_documents
from .panel import render_panel

TOKEN_HEADER = "X-DreamLayer-Token"


def lan_ip() -> str:
    """This machine's LAN address — the one the phone can actually reach.

    Uses a UDP socket to discover the outbound interface without sending
    anything. Falls back to loopback if there's no network.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class Brain:
    """The Brain's live state: config + index + history, rebuilt on change."""

    def __init__(self, cfg_dir: Path | str, sources_fn=None, messages_fn=None):
        self.cfg_dir = Path(cfg_dir)
        self.config = BrainConfig.load(self.cfg_dir)
        self.history = QueryHistory(self.cfg_dir)
        self.activity = ActivityLog(self.cfg_dir)
        self.index = FileIndex(self.config)
        # macOS message/mail documents (folded in when email is enabled)
        self._sources_fn = sources_fn or collect_documents
        # the live feed the glasses read hands-free (the Mac is the bridge)
        from .macos_sources import recent_messages
        self._messages_fn = messages_fn or recent_messages
        self._sig = None
        self._last_phone_ts = 0.0        # last authed request from off-box (the phone)
        self._started_ts = time.time()
        self.last_index_ts = 0.0
        self.email_docs = 0
        self._watch_stop: threading.Event | None = None
        # retention: drop logs older than the configured window on boot
        if self.config.retention_days:
            self.history.prune(self.config.retention_days)
            self.activity.prune(self.config.retention_days)
        self._wire_model()
        self.reindex()

    def reindex(self) -> dict:
        self.index.reindex()
        self.email_docs = 0
        if self.config.email_enabled:
            try:
                docs = self._sources_fn(self.config)
                self.email_docs = len(docs)
                self.index.add_documents(docs)
            except Exception:
                pass
        self._sig = self._signature()
        self.last_index_ts = time.time()
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
            self.index.embedder = (self._backend.embed
                                   if self.config.semantic_search else None)
        else:
            self._backend = None
            self.index.synthesizer = None
            self.index.embedder = None

    def save(self) -> None:
        self.config.save(self.cfg_dir)

    def apply_config(self, updates: dict) -> None:
        for k in ("model", "ollama_url", "ollama_chat_model",
                  "ollama_vision_model", "ollama_embed_model",
                  "email_enabled", "summarize_emails", "cloud_enabled",
                  "network_mode", "cloud_base_url", "cloud_api_key", "cloud_model",
                  "semantic_search", "index_extensions", "max_file_kb",
                  "exclude_globs", "quiet_hours", "retention_days"):
            if k in updates:
                setattr(self.config, k, updates[k])
        self._wire_model()
        self.save()

    def incognito_now(self) -> bool:
        """Effective privacy shield: manual LAN-only OR a quiet-hours window."""
        from .store import in_quiet_hours
        return self.config.lan_only or in_quiet_hours(self.config.quiet_hours)

    def missing_folders(self) -> list:
        return [f for f in self.config.folders
                if not Path(f).expanduser().is_dir()]

    def ask(self, query: str) -> Optional[Answer]:
        ans = self.index.ask(query)
        if ans is None and self.config.cloud_ready() and not self.incognito_now():
            ans = self._ask_cloud(query)
        if ans is not None:
            self.history.add(query, ans.text, ans.tier, ans.sources)
        return ans

    def _ask_cloud(self, query: str) -> Optional[Answer]:
        """The one place data leaves the device — logged every single time."""
        from .backends import cloud_chat
        try:
            text = cloud_chat(self.config, query)
        except Exception:
            text = ""
        if not text:
            return None
        self.config.cloud_calls += 1
        self.save()
        self.activity.add("cloud-egress", f"Asked the cloud: {query[:70]}")
        return Answer(text=text, tier="cloud", sources=["cloud"], confidence=0.6)

    def explain(self, label: str, image_b64, want: str) -> Optional[Answer]:
        return vision_answer(self._backend, label, image_b64, want)

    def summarize(self, text: str, max_chars: int = 220) -> str:
        """One-glance summary of a long email. Uses the local model when there
        is one; otherwise clips to the first sentence — never blocks the feed."""
        text = (text or "").strip()
        if len(text) <= max_chars:
            return text
        if self._backend is not None:
            try:
                s = self._backend.chat(
                    "Summarize this email in one short sentence a person can "
                    "read at a glance. Just the sentence:\n\n" + text[:2000])
                if s and s.strip():
                    return s.strip()
            except Exception:
                pass
        head = text.split(". ")[0].strip()
        return head if 0 < len(head) <= max_chars else text[:max_chars].rstrip() + "…"


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
            tok = brain.config.token        # read live so token rotation applies
            ok = not tok or self.headers.get(TOKEN_HEADER) == tok
            # a successful token-carrying request from off-box is the phone
            if ok and tok and not self._from_localhost():
                brain._last_phone_ts = time.time()
            return ok

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
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)
            if path == "/":
                html = render_panel(brain.config.token if self._from_localhost() else "")
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
            elif path == "/dreamlayer/status":
                ago = None
                if brain._last_phone_ts:
                    ago = max(0, int(time.time() - brain._last_phone_ts))
                idx_ago = (int(time.time() - brain.last_index_ts)
                           if brain.last_index_ts else None)
                self._json(200, {
                    "brain": True,
                    "model": brain.config.model,
                    "cloud": bool(brain.config.cloud_enabled) and not brain.config.lan_only,
                    "cloud_ready": brain.config.cloud_ready(),
                    "cloud_calls": brain.config.cloud_calls,
                    "incognito": brain.incognito_now(),
                    "quiet": brain.incognito_now() and not brain.config.lan_only,
                    "phone_ago": ago,
                    "index_ago": idx_ago,
                    "missing": brain.missing_folders(),
                    "email_docs": brain.email_docs,
                    "stats": brain.index.stats(),
                })
            elif path == "/dreamlayer/token":
                if not self._from_localhost():
                    self._json(403, {"error": "local-only"}); return
                self._json(200, {"token": brain.config.token})
            elif path == "/dreamlayer/health":
                import shutil
                try:
                    du = sum(f.stat().st_size for f in brain.cfg_dir.rglob("*") if f.is_file())
                except OSError:
                    du = 0
                oms = None
                if brain.config.model == "ollama":
                    t0 = time.time()
                    if probe_ollama(brain.config, timeout=3).get("reachable"):
                        oms = int((time.time() - t0) * 1000)
                self._json(200, {"version": _version(), "disk_kb": du // 1000,
                                 "ollama_ms": oms,
                                 "uptime_s": int(time.time() - brain._started_ts)})
            elif path == "/dreamlayer/history":
                self._json(200, {"items": _activity_feed(brain, 40)})
            elif path == "/dreamlayer/messages/recent":
                # the live Messages/Mail feed the glasses read hands-free
                if not brain.config.email_enabled:
                    self._json(200, {"items": [], "enabled": False}); return
                try:
                    items = brain._messages_fn(brain.config, 20)
                except Exception:
                    items = []
                if brain.config.summarize_emails:
                    for it in items:
                        if it.get("channel") == "email":
                            it["summary"] = brain.summarize(it.get("text", ""))
                self._json(200, {"items": items, "enabled": True,
                                 "summarize_emails": brain.config.summarize_emails})
            elif path == "/dreamlayer/model/status":
                self._json(200, probe_ollama(brain.config))
            elif path == "/dreamlayer/browse":
                # a server-side folder picker (the panel navigates the Mac's
                # own filesystem) — local-only, like pairing
                if not self._from_localhost():
                    self._json(403, {"error": "browse is local-only"}); return
                self._json(200, _browse_dir(qs.get("path", [""])[0]))
            elif path == "/dreamlayer/pair":
                # a pairing code for the phone — only handed to the local panel
                if not self._from_localhost():
                    self._json(403, {"error": "pairing is local-only"}); return
                from ...pairing import PairingBundle, encode_pairing
                # the code must point the phone at an address it can reach on the
                # LAN — never the loopback/Host the local browser used.
                port = self.server.server_address[1]
                ip = lan_ip()
                if ip and ip != "127.0.0.1":
                    url = f"http://{ip}:{port}"
                else:
                    url = "http://" + (self.headers.get("Host") or f"127.0.0.1:{port}")
                bundle = PairingBundle(brain_url=url, token=brain.config.token)
                brain.activity.add("pair", "Generated a pairing code for the phone")
                self._json(200, {"code": encode_pairing(bundle), "url": url})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
            if not self._authed():
                self._json(401, {"error": "unauthorised"}); return
            if path == "/dreamlayer/folders":
                b = self._body()
                p = b.get("path", "")
                if b.get("action") == "add":
                    if brain.config.add_folder(p):
                        brain.activity.add("folder", f"Added folder {p}")
                elif b.get("action") == "remove":
                    brain.config.remove_folder(p)
                    brain.activity.add("folder", f"Removed folder {p}")
                brain.save(); brain.reindex()
                self._json(200, {"config": brain.config.public(),
                                 "stats": brain.index.stats()})
            elif path == "/dreamlayer/config":
                body = self._body()
                before = (brain.config.model, brain.config.cloud_enabled,
                          brain.config.network_mode, brain.config.email_enabled)
                brain.apply_config(body)
                brain.reindex()
                if "model" in body and brain.config.model != before[0]:
                    brain.activity.add("model", f"Model set to {brain.config.model}")
                if "cloud_enabled" in body and brain.config.cloud_enabled != before[1]:
                    brain.activity.add("cloud", "Cloud enabled" if brain.config.cloud_enabled else "Cloud disabled")
                if "network_mode" in body and brain.config.network_mode != before[2]:
                    brain.activity.add("privacy", "Incognito on" if brain.config.lan_only else "Incognito off")
                if "email_enabled" in body and brain.config.email_enabled != before[3]:
                    brain.activity.add("config", "Email & iMessage " + ("on" if brain.config.email_enabled else "off"))
                self._json(200, {"config": brain.config.public()})
            elif path == "/dreamlayer/upload":
                folder = (qs.get("folder", [""])[0])
                name = Path(qs.get("name", ["dropped.txt"])[0]).name
                ok = _write_upload(brain, folder, name, self._raw())
                if ok:
                    brain.activity.add("upload", f"Added {name}")
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
            elif path == "/dreamlayer/reindex":
                stats = brain.reindex()
                brain.activity.add("index", "Re-indexed your folders")
                self._json(200, {"stats": stats, "missing": brain.missing_folders()})
            elif path == "/dreamlayer/token/rotate":
                if not self._from_localhost():
                    self._json(403, {"error": "local-only"}); return
                import secrets
                brain.config.token = secrets.token_hex(8)
                brain.save()
                brain.activity.add("privacy", "Rotated the pairing token — devices must re-pair")
                self._json(200, {"token": brain.config.token})
            elif path == "/dreamlayer/clear":
                if not self._from_localhost():
                    self._json(403, {"error": "local-only"}); return
                what = self._body().get("what", "")
                if what in ("history", "all"): brain.history.clear()
                if what in ("activity", "all"): brain.activity.clear()
                if what in ("folders", "all"):
                    brain.config.folders = []; brain.save(); brain.reindex()
                # don't re-seed the activity log we just cleared
                if what in ("history", "folders"):
                    brain.activity.add("config", f"Cleared {what}")
                self._json(200, {"ok": True, "stats": brain.index.stats()})
            elif path == "/dreamlayer/cloud/test":
                if not self._from_localhost():
                    self._json(403, {"error": "local-only"}); return
                from .backends import cloud_test
                self._json(200, cloud_test(brain.config))
            elif path == "/dreamlayer/message/draft":
                from .macos_sources import MessageDraft, build_send_script
                b = self._body()
                d = MessageDraft(channel=b.get("channel", "imessage"),
                                 to=b.get("to", ""), subject=b.get("subject", ""),
                                 text=b.get("text", ""))
                self._json(200, {"script": build_send_script(d)})
            elif path == "/dreamlayer/message/send":
                if not self._from_localhost():
                    self._json(403, {"error": "local-only"}); return
                from .macos_sources import MessageDraft, send_message
                b = self._body()
                d = MessageDraft(channel=b.get("channel", "imessage"),
                                 to=b.get("to", ""), subject=b.get("subject", ""),
                                 text=b.get("text", ""))
                try:
                    res = send_message(d, approved=bool(b.get("approved")))
                    brain.activity.add("message", f"Sent a {d.channel} to {d.to}")
                    self._json(200, res)
                except Exception as e:  # noqa: BLE001
                    self._json(400, {"error": str(e)[:200]})
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


def _version() -> str:
    try:
        import dreamlayer
        return getattr(dreamlayer, "__version__", "0.0.0")
    except Exception:
        return "0.0.0"


def _answer_json(ans: Optional[Answer]) -> dict:
    if ans is None:
        return {"text": "", "tier": "", "sources": [], "confidence": 0.0}
    return {"text": ans.text, "tier": ans.tier, "sources": ans.sources,
            "confidence": ans.confidence}


def _activity_feed(brain: Brain, n: int = 40) -> list[dict]:
    """One newest-first feed: questions + every action the Brain took."""
    items = []
    for h in brain.history.recent(n):
        items.append({"ts": h.get("ts", 0), "kind": "ask",
                      "query": h.get("query", ""), "text": h.get("answer", ""),
                      "tier": h.get("tier", "")})
    for a in brain.activity.recent(n):
        items.append({"ts": a.get("ts", 0), "kind": a.get("kind", "event"),
                      "text": a.get("text", "")})
    items.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return items[:n]


def _browse_dir(raw: str) -> dict:
    """List the subfolders of a directory so the panel can walk the Mac's own
    filesystem — folders only, hidden entries skipped."""
    base = Path(raw).expanduser() if raw else Path.home()
    try:
        base = base.resolve()
    except OSError:
        base = Path.home()
    if not base.is_dir():
        base = Path.home()
    dirs = []
    try:
        for e in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if e.is_dir() and not e.name.startswith("."):
                dirs.append(e.name)
    except OSError:
        pass
    parent = str(base.parent) if base.parent != base else ""
    return {"path": str(base), "parent": parent, "dirs": dirs,
            "home": str(Path.home())}
