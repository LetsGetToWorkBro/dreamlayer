"""social_lens/commitment_ner.py — sharper commitment/action extraction (GLiNER).

The deterministic extractor in meeting.py catches the obvious shapes ("I'll …",
"Marcus will …"). GLiNER — a tiny generalist zero-shot NER — catches the ones a
regex can't ("owner: Dana, ship the build by EOW", "we're on the hook for the
audit"). Lazy-imports gliner (extras group `nlp-extra`); absent the wheel,
extract() returns [] and the deterministic pass stands alone. On-device, no
cloud.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("dreamlayer.commitment_ner")

# the labels we ask GLiNER for — a commitment and, when present, who owns it and
# when it's due.
_LABELS = ["task or commitment", "person", "deadline"]


def _has(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


class GlinerCommitments:
    """A `extract(text) -> [{text, when, who}]` over GLiNER. `available` is True
    only when the wheel imports AND the model loads."""

    dep = "gliner"
    available = _has("gliner")

    def __init__(self, model: str = "urchade/gliner_small-v2.1",
                 threshold: float = 0.45):
        self._model = None
        self._threshold = threshold
        if not self.available:
            return
        try:
            from gliner import GLiNER  # type: ignore
            self._model = GLiNER.from_pretrained(model)
        except Exception as exc:                       # noqa: BLE001
            log.info("[gliner] load failed (%s); deterministic-only", exc)
            self._model = None

    @property
    def ready(self) -> bool:
        return self._model is not None

    def extract(self, text: str) -> list[dict]:
        text = (text or "").strip()
        if not text or self._model is None:
            return []
        try:
            ents = self._model.predict_entities(text, _LABELS,
                                                threshold=self._threshold)
        except Exception as exc:                       # noqa: BLE001
            log.error("[gliner] predict failed: %s", exc)
            return []
        tasks, who, when = [], "", ""
        for e in ents or []:
            lab = str(e.get("label", "")).lower()
            val = str(e.get("text", "")).strip()
            if not val:
                continue
            if lab.startswith("task"):
                tasks.append(val)
            elif lab == "person" and not who:
                who = val
            elif lab == "deadline" and not when:
                when = val
        return [{"text": t[:200], "when": when, "who": who} for t in tasks]


def default_commitment_ner() -> Optional[GlinerCommitments]:
    """The GLiNER extractor if the wheel is installed, else None (deterministic
    extraction stands alone)."""
    g = GlinerCommitments()
    return g if g.ready else None
