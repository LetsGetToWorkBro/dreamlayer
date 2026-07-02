"""ai_brain/server/store.py — the Brain's own state: config + query history.

This is the "load your info / connect your stuff" layer. Everything the
control panel edits lives here, persisted as plain JSON so it's easy to
inspect, back up, or hand-edit.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

CONFIG_FILE = "brain_config.json"
HISTORY_FILE = "brain_history.jsonl"


@dataclass
class BrainConfig:
    """Everything the Brain reads and how it thinks. Editable from the panel."""
    folders: list[str] = field(default_factory=list)   # watched directories
    model: str = "keyword"          # "keyword" | "ollama"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_chat_model: str = "llama3.2"
    ollama_vision_model: str = "llama3.2-vision"
    ollama_embed_model: str = "nomic-embed-text"
    email_enabled: bool = False     # macOS Mail / iMessage read (Phase 3 seam)
    # network posture (product default = connected): "connected" reaches the
    # internet + cloud; "lan_only" is the advanced home-only mode.
    network_mode: str = "connected"
    cloud_enabled: bool = True      # cloud tier allowed by default
    token: str = ""                 # pairing secret the phone must send

    @property
    def lan_only(self) -> bool:
        return self.network_mode == "lan_only"

    def add_folder(self, path: str) -> bool:
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

    # -- persistence -----------------------------------------------------

    @classmethod
    def load(cls, cfg_dir: Path | str) -> "BrainConfig":
        p = Path(cfg_dir) / CONFIG_FILE
        if p.exists():
            try:
                data = json.loads(p.read_text())
                known = {f.name for f in field_list(cls)}
                return cls(**{k: v for k, v in data.items() if k in known})
            except (ValueError, TypeError, json.JSONDecodeError):
                pass
        return cls()

    def save(self, cfg_dir: Path | str) -> None:
        d = Path(cfg_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / CONFIG_FILE).write_text(json.dumps(asdict(self), indent=2))

    def public(self) -> dict:
        """Config for the panel — never leaks the token."""
        d = asdict(self)
        d["token"] = "set" if self.token else ""
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
