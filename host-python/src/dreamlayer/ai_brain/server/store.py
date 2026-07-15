"""ai_brain/server/store.py — the Brain's own state: config + query history.

This is the "load your info / connect your stuff" layer. Everything the
control panel edits lives here, persisted as plain JSON so it's easy to
inspect, back up, or hand-edit.
"""
from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

CONFIG_FILE = "brain_config.json"
HISTORY_FILE = "brain_history.jsonl"
ACTIVITY_FILE = "brain_activity.jsonl"


def _is_allowed_root(path: str) -> bool:
    """True if `path` may be indexed by the Brain.

    Default-deny allow-list: the path must resolve to somewhere under the
    user's own home tree, or under the OS temp tree (used by legitimate
    export/scratch workflows and the test harness). Anything else — a system
    directory (/etc, /var, /usr, /System), another user's home, or the
    filesystem root — is refused. The path is fully resolved first so `..`
    and symlink escapes can't smuggle a disallowed target past the check.
    Non-existent paths are permitted as long as they resolve under an allowed
    root, so a temporarily-missing folder can still be watched.
    """
    try:
        p = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    try:
        allowed_roots = [Path.home().resolve(),
                         Path(tempfile.gettempdir()).resolve()]
    except (OSError, RuntimeError, ValueError):
        return False
    for root in allowed_roots:
        if p == root or root in p.parents:
            return True
    return False


@dataclass
class BrainConfig:
    """Everything the Brain reads and how it thinks. Editable from the panel."""
    folders: list[str] = field(default_factory=list)   # watched directories
    model: str = "keyword"          # "keyword" | "ollama" | "mlx" | "api"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_chat_model: str = "llama3.2"
    ollama_vision_model: str = "llama3.2-vision"
    ollama_embed_model: str = "nomic-embed-text"
    email_enabled: bool = False     # macOS Mail / iMessage read (Phase 3 seam)
    summarize_emails: bool = False  # shorten emails to a glance before relaying
    # network posture (product default = connected): "connected" reaches the
    # internet + cloud; "lan_only" is the advanced home-only mode.
    network_mode: str = "connected"
    cloud_enabled: bool = False     # cloud tier is opt-in — off until enabled
    token: str = ""                 # pairing secret the phone must send
    # billing tier (seam only — no paywall). "free" = local & open, grants
    # everything today. A future "cloud" plan is where hosted capabilities
    # (managed AI, sync, relay) would attach. See server.PLAN_CAPS.
    plan: str = "free"
    # -- cloud provider (batch 2) — the tier that leaves the device ------
    # provider: openai | anthropic | gemini | openrouter | ollama | custom
    # (see backends.PROVIDER_PRESETS). Ollama is local + free + needs no key.
    cloud_provider: str = "openai"
    cloud_base_url: str = "https://api.openai.com"
    cloud_api_key: str = ""
    cloud_model: str = "gpt-4o-mini"
    cloud_calls: int = 0            # lifetime count of cloud egress
    # -- primary API brain — plug in your own agent as the MAIN answerer -----
    # When model == "api", the first-pass answer is routed to this endpoint
    # (OpenClaw, Hermes, LM Studio, vLLM, a local Ollama, any OpenAI-compatible
    # / Anthropic / Gemini API) instead of the on-device keyword/Ollama tier.
    # Distinct from cloud_* (the escalation tier) so the two can point at
    # different places. Egress is decided by the endpoint's LOCALITY, not by
    # this being a "cloud" field: a localhost/LAN endpoint answers freely and
    # is not egress; a remote one is counted, logged, and veil-gated exactly
    # like the cloud tier (see Brain._ask_primary_api).
    api_provider: str = "custom"    # a PROVIDER_PRESETS key (wire format)
    api_base_url: str = ""
    api_key: str = ""
    api_model: str = ""
    # -- knowledge depth (batch 3) --------------------------------------
    semantic_search: bool = False   # embed + rank (needs an embed model)
    index_extensions: list[str] = field(default_factory=list)   # [] = defaults
    max_file_kb: int = 2000
    exclude_globs: list[str] = field(default_factory=list)
    # -- ops (batch 4) ---------------------------------------------------
    quiet_hours: str = ""           # "22:00-07:00" → auto-incognito window
    retention_days: int = 0         # 0 = keep forever
    brief_hour: int = -1            # deliver the morning brief at this hour; -1 = off
    # -- calendar sync (macOS Calendar.app → agenda) --------------------
    calendar_sync: bool = False     # pull events from Calendar.app on a poll
    calendar_names: list[str] = field(default_factory=list)  # [] = all calendars
    calendar_days: int = 14         # how far ahead to pull
    # -- contacts + reminders sync (macOS) ------------------------------
    contacts_sync: bool = False     # pull Contacts.app into the People registry
    reminders_sync: bool = False    # pull open Reminders.app to-dos
    reminder_lists: list[str] = field(default_factory=list)  # [] = all lists
    # -- optional capabilities (dreamlayer/capabilities.py) --------------
    # keys the panel switched OFF — the persisted twin of DL_DISABLE_<KEY>,
    # so the bundled app remembers the choice across restarts
    disabled_caps: list[str] = field(default_factory=list)

    @property
    def lan_only(self) -> bool:
        return self.network_mode == "lan_only"

    def cloud_ready(self) -> bool:
        """Cloud can actually answer: allowed by posture AND configured.

        Ollama-local runs on-device with no key, so it only needs a model;
        every other provider also needs an API key.
        """
        if self.network_mode == "lan_only" or not self.cloud_enabled:
            return False
        if not self.cloud_model:
            return False
        if self.cloud_provider == "ollama":
            return True
        return bool(self.cloud_api_key)

    def api_configured(self) -> bool:
        """Is a primary API brain wired (base URL present)?"""
        return bool((self.api_base_url or "").strip())

    def api_is_local(self) -> bool:
        """Does the primary API endpoint live on this machine / LAN? If so it is
        NOT cloud egress and stays reachable while incognito; if remote, it is
        gated and logged like the cloud tier. Drives the panel's privacy
        warning. Unconfigured → False (nothing to reach)."""
        if not self.api_configured():
            return False
        from .backends import is_local_endpoint      # lazy: avoid import cycle
        return is_local_endpoint(self.api_base_url)

    def add_folder(self, path: str) -> bool:
        # SECURITY: default-deny allow-list. A token holder must not be able to
        # point the Brain at /etc, another user's home, or the filesystem root
        # (audit 2026-07-14 — "accepts any path with no allow-list"). This is a
        # fast-fail at the front door; _is_allowed_root is also re-checked at the
        # walk sink (index.reindex) and on every other writer (sanitize_folders,
        # called from load + import_backup), so the allow-list holds no matter
        # how a path reaches config.folders — not just via this handler
        # (refute-remediation 2026-07). Storage stays expanduser-only
        # (unresolved) so downstream comparisons — missing_folders,
        # _write_upload, the index — see the same string they always did.
        if not _is_allowed_root(path):
            return False
        p = str(Path(path).expanduser())
        if p not in self.folders:
            self.folders.append(p)
            return True
        return False

    def remove_folder(self, path: str) -> bool:
        p = str(Path(path).expanduser())
        if p in self.folders:
            self.folders.remove(p)
            return True
        return False

    def sanitize_folders(self) -> None:
        """Drop any watched folder that isn't allow-listed. Called on load and
        after a restore, so a hand-edited/pre-remediation config file or a
        crafted backup cannot reintroduce a path the add-folder gate would have
        refused (refute-remediation 2026-07)."""
        self.folders = [f for f in self.folders if _is_allowed_root(f)]

    # -- persistence -----------------------------------------------------

    @classmethod
    def load(cls, cfg_dir: Path | str) -> "BrainConfig":
        p = Path(cfg_dir) / CONFIG_FILE
        if p.exists():
            try:
                data = json.loads(p.read_text())
                known = {f.name for f in field_list(cls)}
                inst = cls(**{k: v for k, v in data.items() if k in known})
                inst.sanitize_folders()   # a tampered/legacy file can't smuggle disallowed roots
                return inst
            except (ValueError, TypeError, json.JSONDecodeError):
                pass
        return cls()

    def save(self, cfg_dir: Path | str) -> None:
        d = Path(cfg_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / CONFIG_FILE).write_text(json.dumps(asdict(self), indent=2))

    def public(self) -> dict:
        """Config for the panel — never leaks the token or any provider key."""
        d = asdict(self)
        d["token"] = "set" if self.token else ""
        d["cloud_api_key"] = "set" if self.cloud_api_key else ""
        d["api_key"] = "set" if self.api_key else ""
        d["cloud_ready"] = self.cloud_ready()
        d["api_configured"] = self.api_configured()
        d["api_is_local"] = self.api_is_local()
        return d


def field_list(cls):
    import dataclasses
    return dataclasses.fields(cls)


class QueryHistory:
    """An append-only log of what you asked and what came back."""

    def __init__(self, cfg_dir: Path | str, limit: int = 500):
        self.path = Path(cfg_dir) / HISTORY_FILE
        self.limit = limit

    def add(self, query: str, answer: str, tier: str,
            sources: Optional[list[str]] = None, ts: Optional[float] = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": ts if ts is not None else time.time(), "query": query,
               "answer": answer, "tier": tier, "sources": sources or []}
        with self.path.open("a") as f:
            f.write(json.dumps(rec) + "\n")

    def recent(self, n: int = 20) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text().splitlines()
        out = []
        for line in lines[-n:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(out))

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def prune(self, days: int) -> int:
        return _prune_jsonl(self.path, days)

    def restore(self, items) -> None:
        _restore_jsonl(self.path, items)


class ActivityLog:
    """Everything the Brain did — folders, files, searches, cloud/incognito
    toggles, pairing — as a single newest-first feed for the panel."""

    def __init__(self, cfg_dir: Path | str):
        self.path = Path(cfg_dir) / ACTIVITY_FILE

    def add(self, kind: str, text: str, ts: Optional[float] = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": ts if ts is not None else time.time(),
               "kind": kind, "text": text}
        with self.path.open("a") as f:
            f.write(json.dumps(rec) + "\n")

    def recent(self, n: int = 40) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines()[-n:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(out))

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def prune(self, days: int) -> int:
        return _prune_jsonl(self.path, days)

    def restore(self, items) -> None:
        _restore_jsonl(self.path, items)


def _restore_jsonl(path: Path, items) -> None:
    """Rewrite a jsonl log from a newest-first list (as recent() returns)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for rec in reversed(list(items or [])):
            f.write(json.dumps(rec) + "\n")


def _prune_jsonl(path: Path, days: int) -> int:
    """Drop records older than `days` from a jsonl log. Returns rows removed."""
    if days <= 0 or not path.exists():
        return 0
    cutoff = time.time() - days * 86400
    kept, removed = [], 0
    for line in path.read_text().splitlines():
        try:
            if json.loads(line).get("ts", 0) >= cutoff:
                kept.append(line)
            else:
                removed += 1
        except json.JSONDecodeError:
            continue
    if removed:
        path.write_text("\n".join(kept) + ("\n" if kept else ""))
    return removed


def in_quiet_hours(spec: str, now: Optional[float] = None) -> bool:
    """True if `now` falls in a "HH:MM-HH:MM" window (wraps past midnight)."""
    if not spec or "-" not in spec:
        return False
    try:
        a, b = spec.split("-", 1)
        ah, am = (int(x) for x in a.split(":"))
        bh, bm = (int(x) for x in b.split(":"))
    except (ValueError, TypeError):
        return False
    lt = time.localtime(now if now is not None else time.time())
    cur = lt.tm_hour * 60 + lt.tm_min
    start, end = ah * 60 + am, bh * 60 + bm
    if start == end:
        return False
    return start <= cur < end if start < end else (cur >= start or cur < end)
