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

import re
from pathlib import Path
from typing import Callable, Optional

from ..schema import Answer

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
    def __init__(self, config, synthesizer: Optional[Callable] = None):
        self.config = config
        self.synthesizer = synthesizer          # (query, [(path,passage)]) -> str
        self._passages: list[tuple[str, str]] = []   # (path, passage)

    # -- building --------------------------------------------------------

    def reindex(self) -> dict:
        self._passages = []
        files = 0
        for folder in self.config.folders:
            base = Path(folder).expanduser()
            if not base.is_dir():
                continue
            for path in base.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in TEXT_EXTS:
                    continue
                try:
                    if path.stat().st_size > MAX_FILE_BYTES:
                        continue
                    text = path.read_text(errors="ignore")
                except OSError:
                    continue
                files += 1
                for p in _passages(text):
                    self._passages.append((path.name, p))
        return self.stats()

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
        q = _keywords(query)
        scored = []
        for path, passage in self._passages:
            hits = len(q & _keywords(passage))
            if hits:
                scored.append((hits, path, passage))
        scored.sort(key=lambda s: -s[0])
        return [(path, passage, hits) for hits, path, passage in scored[:k]]

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
