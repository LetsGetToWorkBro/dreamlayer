"""ai_brain/server/index.py — a local index over your chosen folders.

Scans the folders in the config, splits text files into passages, and
answers a question by finding the most relevant passage(s). Retrieval is
keyword-based by default — real, fast, and dependency-free, so "drag a file
into a watched folder and ask about it" works today. A synthesizer (an
Ollama chat model on the Mac mini) can be plugged to turn the retrieved
passages into a written answer; without one, the best passage is returned
verbatim with its source file.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable, Optional

from ..schema import Answer
from .store import _is_allowed_root, _is_index_denied

log = logging.getLogger(__name__)

TEXT_EXTS = {".txt", ".md", ".markdown", ".rst", ".text", ".log", ".csv",
             ".json", ".py", ".org", ".tex"}
MAX_FILE_BYTES = 2_000_000
MAX_PASSAGE_CHARS = 600

_STOP = frozenset({
    "the", "and", "for", "are", "was", "that", "this", "with", "you", "your",
    "what", "how", "who", "why", "when", "where", "does", "did", "from",
    "into", "out", "not", "but", "its", "our", "per", "due", "will", "can",
})


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']{3,}", (text or "").lower())
            if w not in _STOP}


def _passages(text: str) -> list[str]:
    # split on blank lines; fall back to lines; cap length
    blocks = re.split(r"\n\s*\n", text) if "\n\n" in text else text.splitlines()
    out = []
    for b in blocks:
        b = b.strip()
        if b:
            out.append(b[:MAX_PASSAGE_CHARS])
    return out


class FileIndex:
    def __init__(self, config, synthesizer: Optional[Callable] = None,
                 embedder: Optional[Callable] = None):
        self.config = config
        self.synthesizer = synthesizer          # (query, [(path,passage)]) -> str
        self.embedder = embedder                # text -> vector (semantic search)
        self._passages: list[tuple[str, str]] = []   # (path, passage)
        self._vecs: list = []                   # aligned passage embeddings

    # -- filters (configurable from the panel) --------------------------

    def _exts(self) -> set:
        custom = getattr(self.config, "index_extensions", None) or []
        if not custom:
            return TEXT_EXTS
        return {e if e.startswith(".") else "." + e for e in
                (x.strip().lower() for x in custom) if e}

    def _max_bytes(self) -> int:
        kb = getattr(self.config, "max_file_kb", 0) or 0
        return kb * 1000 if kb > 0 else MAX_FILE_BYTES

    def _excluded(self, path: Path) -> bool:
        for g in (getattr(self.config, "exclude_globs", None) or []):
            g = g.strip()
            if g and (path.match(g) or any(part == g for part in path.parts)):
                return True
        return False

    def _semantic_on(self) -> bool:
        return bool(getattr(self.config, "semantic_search", False)) and self.embedder is not None

    # -- building --------------------------------------------------------

    def reindex(self) -> dict:
        self._passages = []
        self._vecs = []
        exts, cap = self._exts(), self._max_bytes()
        for folder in self.config.folders:
            # Re-validate at the walk sink, not just at add_folder: a folder can
            # reach config.folders through import_backup/restore, a hand-edited
            # or pre-remediation config file, or a symlink swapped after the
            # add-time check (TOCTOU). _is_allowed_root re-resolves here, so no
            # path outside the allow-list is ever read regardless of how it got
            # into the list (refute-remediation 2026-07: the add_folder gate was
            # not the only writer). Skip + record rather than index it.
            # _is_index_denied additionally refuses the Brain's OWN state dir
            # (whose brain_config.json holds the token + provider keys in clear)
            # and secret dotdirs even though they pass the home-tree allow-list,
            # so "add ~/.dreamlayer as a watched folder" cannot recall its own
            # secrets via /brain/ask (refute-remediation 2026-07-17).
            if not _is_allowed_root(folder) or _is_index_denied(folder):
                log.warning("reindex: skipping disallowed folder %r", folder)
                continue
            base = Path(folder).expanduser()
            if not base.is_dir():
                continue
            for path in base.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in exts:
                    continue
                if self._excluded(path):
                    continue
                # Per-FILE allow-list re-check at the walk sink. The folder ROOT
                # was allow-listed above, but rglob yields the folder's contents,
                # and a symlink inside an allowed folder can RESOLVE to a target
                # outside the allow-list (~/watched/notes.txt -> /etc/passwd, and
                # .txt matches TEXT_EXTS). The root gate never sees that per-file
                # swap (TOCTOU). _is_allowed_root resolve()s, so the escaping
                # symlink is skipped rather than read, ingested, and surfaced via
                # /brain/ask (refute-remediation 2026-07-17).
                # _is_index_denied also catches a symlink whose target resolves
                # INTO the Brain's state dir or a secret dotdir (e.g.
                # ~/watched/cfg.json -> <statedir>/brain_config.json): that target
                # passes the home-tree allow-list but must never be indexed and
                # recalled (refute-remediation 2026-07-17).
                if not _is_allowed_root(str(path)) or _is_index_denied(str(path)):
                    log.warning("reindex: skipping disallowed file %r", str(path))
                    continue
                try:
                    if path.stat().st_size > cap:
                        continue
                    # explicit utf-8: the locale default is utf-8 on
                    # macOS/Linux but cp1252 on Windows, which would silently
                    # mangle every non-ASCII note there
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for p in _passages(text):
                    self._passages.append((path.name, p))
        self._embed_passages()
        return self.stats()

    def _embed_passages(self) -> None:
        if not self._semantic_on():
            self._vecs = []
            return
        vecs = []
        assert self.embedder is not None   # _semantic_on() is only True with an embedder
        for _, passage in self._passages:
            try:
                vecs.append(self.embedder(passage))
            except Exception:
                vecs.append(None)
        self._vecs = vecs

    def add_documents(self, docs: list[tuple[str, str]]) -> dict:
        """Fold in extra (name, text) documents — e.g. iMessage/Mail — that
        aren't files on disk. Called after reindex()."""
        for name, text in docs:
            for p in _passages(text):
                self._passages.append((name, p))
        return self.stats()

    def stats(self) -> dict:
        return {"folders": len(self.config.folders),
                "passages": len(self._passages),
                "files": len({p for p, _ in self._passages})}

    # -- answering -------------------------------------------------------

    def search(self, query: str, k: int = 4) -> list[tuple[str, str, int]]:
        if self._semantic_on() and any(v is not None for v in self._vecs):
            sem = self._search_semantic(query, k)
            if sem:
                return sem
        q = _keywords(query)
        scored = []
        for path, passage in self._passages:
            hits = len(q & _keywords(passage))
            if hits:
                scored.append((hits, path, passage))
        scored.sort(key=lambda s: -s[0])
        return [(path, passage, hits) for hits, path, passage in scored[:k]]

    def _search_semantic(self, query: str, k: int) -> list[tuple[str, str, int]]:
        import math
        assert self.embedder is not None   # only reached when semantic search is on
        try:
            qv = self.embedder(query)
        except Exception:
            return []
        if not qv:
            return []
        qn = math.sqrt(sum(x * x for x in qv)) or 1.0
        scored = []
        for (path, passage), v in zip(self._passages, self._vecs):
            if not v:
                continue
            dot = sum(a * b for a, b in zip(qv, v))
            vn = math.sqrt(sum(x * x for x in v)) or 1.0
            cos = dot / (qn * vn)
            if cos > 0.15:
                scored.append((cos, path, passage))
        scored.sort(key=lambda s: -s[0])
        # map cosine → the small int "hits" the caller uses for confidence
        return [(path, passage, max(1, int(cos * 6))) for cos, path, passage in scored[:k]]

    def ask(self, query: str) -> Optional[Answer]:
        hits = self.search(query)
        if not hits:
            return None
        sources = list(dict.fromkeys(h[0] for h in hits))     # unique, ordered
        if self.synthesizer is not None:
            try:
                text = self.synthesizer(query, [(h[0], h[1]) for h in hits])
            except Exception:
                text = hits[0][1]
        else:
            text = hits[0][1]                    # best passage, verbatim
        conf = min(1.0, 0.4 + 0.15 * hits[0][2])
        return Answer(text=text.strip(), sources=sources, tier="laptop",
                      confidence=conf)
