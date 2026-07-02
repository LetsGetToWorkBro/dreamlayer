"""object_lens/schema.py — data structures for the Object Lens.

An Object Lens turns "look at a thing" into a small contextual panel: what
it is, what you already know about it, and what you can do with it. The
panel is assembled from providers (object_lens/providers.py), so the shapes
here are deliberately generic — a title, a subtitle, and a list of rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ObjectSighting:
    """One recognised object in view."""
    label: str
    confidence: float               # 0-1
    attributes: dict = field(default_factory=dict)   # colour, brand, text…
    # the frame it was seen in, for a vision brain to explain. Not part of
    # identity and never serialised.
    frame: object = field(default=None, repr=False, compare=False)

    def key(self) -> str:
        return self.label.strip().lower()


# a panel row: information you read, an action you can take, or a live stat
ROW_KINDS = frozenset({"info", "action", "toggle", "stat"})


@dataclass
class PanelRow:
    label: str
    detail: str = ""
    kind: str = "info"              # info | action | toggle | stat
    value: Optional[str] = None     # for stat/toggle
    source: str = ""                # which provider produced it

    def to_dict(self) -> dict:
        d = {"label": self.label, "kind": self.kind}
        if self.detail:
            d["detail"] = self.detail
        if self.value is not None:
            d["value"] = self.value
        if self.source:
            d["source"] = self.source
        return d


@dataclass
class ObjectPanel:
    """The contextual control panel for one sighting."""
    sighting: ObjectSighting
    title: str
    subtitle: str = ""
    rows: list[PanelRow] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.rows

    def to_hud_card(self) -> dict:
        conf_pct = round(self.sighting.confidence * 100)
        lines = [self.title]
        if self.subtitle:
            lines.append(self.subtitle)
        for r in self.rows[:4]:
            lines.append(f"{r.label}{('  ' + r.value) if r.value else ''}")
        return {
            "type": "ObjectPanelCard",
            "dismiss_ms": 6000,
            "eyebrow": "OBJECT",
            "primary": self.title,
            "detail": self.subtitle,
            "footer": f"{conf_pct}% · {', '.join(self.sources)}",
            "color": "accent_memory",
            "label": self.sighting.label,
            "confidence": self.sighting.confidence,
            "rows": [r.to_dict() for r in self.rows],
            "lines": lines,
        }
