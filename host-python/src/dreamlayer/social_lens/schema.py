"""social_lens/schema.py — Data structures for SocialLens."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class ContactRecord:
    """A single entry in the personal contacts registry.

    Attributes
    ----------
    contact_id   : unique identifier (e.g. address book UUID)
    name         : display name
    embedding    : 512-d float face embedding vector
    company      : employer / organisation (optional)
    role         : job title (optional)
    last_met     : ISO-8601 date string of last interaction (optional)
    notes        : freeform personal notes (optional)
    relation     : how you know them — "colleague", "brother" (optional)
    email        : email address (optional)
    """
    contact_id: str
    name: str
    embedding: list[float]
    company: Optional[str] = None
    role: Optional[str] = None
    last_met: Optional[str] = None
    notes: Optional[str] = None
    relation: Optional[str] = None
    debts: tuple = ()                 # [{dir, what}] — owes/owed, kept on-device
    email: Optional[str] = None

    def __post_init__(self):
        if len(self.embedding) != 512:
            raise ValueError(
                f"ContactRecord embedding must be 512-d, got {len(self.embedding)}"
            )

    def latest_note(self) -> str:
        """The most recent freeform note (what the recall card highlights)."""
        return _latest_note(self.notes)

    def debt_lines(self) -> list:
        """Open debts as plain phrases: "owes you $20", "you owe lunch"."""
        out = []
        for d in self.debts or ():
            what = str(d.get("what", "")).strip()
            if not what:
                continue
            out.append(f"owes you {what}" if d.get("dir") == "they_owe"
                       else f"you owe {what}")
        return out

    def context_line(self) -> str:
        """One-line context string for the HUD card."""
        parts = []
        if self.company:
            parts.append(self.company)
        if self.role:
            parts.append(self.role)
        if self.last_met:
            parts.append(f"Met: {self.last_met}")
        return "  •  ".join(parts) if parts else ""


@dataclass
class MatchResult:
    """Result of a single face-embedding search."""
    contact: ContactRecord
    confidence: float           # cosine similarity 0-1
    is_match: bool              # True if confidence >= threshold


@dataclass
class SocialLensResult:
    """Complete output from one SocialLens.identify() call."""
    match: Optional[MatchResult]
    frame_confidence: float     # face detection confidence
    no_face: bool = False       # True if no face was detected
    no_match: bool = False      # True if face found but no contact matched

    def to_hud_card(self) -> dict:
        """Render as a Halo HUD card dict."""
        if self.no_face:
            return {
                "type": "SocialLensCard",
                "dismiss_ms": 2500,
                "eyebrow": "FACE RECALL",
                "primary": "No face detected",
                "detail": "",
                "footer": "",
                "color": 0xFF0000,
                "opacity": 0.7,
                "lines": ["FACE RECALL", "No face detected"],
                "layout": {
                    "eyebrow": {"x": 128, "y": 200, "size": "sm",
                                "color": 0x7BEF, "tracking": 3},
                    "primary": {"x": 128, "y": 218, "size": "sm",
                                "color": 0xFF0000},
                },
            }

        if self.no_match:
            return {
                "type": "SocialLensCard",
                "dismiss_ms": 2500,
                "eyebrow": "FACE RECALL",
                "primary": "No match",
                "detail": "Not in your contacts",
                "footer": "",
                "color": 0x7BEF,
                "opacity": 0.7,
                "lines": ["FACE RECALL", "No match", "Not in your contacts"],
                "layout": {
                    "eyebrow": {"x": 128, "y": 200, "size": "sm",
                                "color": 0x7BEF, "tracking": 3},
                    "primary": {"x": 128, "y": 218, "size": "sm",
                                "color": 0x7BEF},
                    "detail":  {"x": 128, "y": 234, "size": "sm",
                                "color": 0x39E7},
                },
            }

        # Matched contact (reached only past the no_match guard above)
        m = self.match
        assert m is not None
        c = m.contact
        conf_pct = round(m.confidence * 100)
        conf_color = 0x07E0 if m.confidence >= 0.85 else (
            0xFFE0 if m.confidence >= 0.70 else 0xFD20
        )
        # The rescue: lead with how you know them, so you never blank —
        # relationship, then context, then the freshest thing you noted.
        relation = (c.relation or "").strip()
        note = _latest_note(c.notes)          # what you last asked to remember
        note_line = f"“{note}”" if note else ""
        ctx = c.context_line()
        debt_line = "  ·  ".join(c.debt_lines())   # "owes you $20"
        lines = ["FACE RECALL", c.name]
        if relation:
            lines.append(relation)
        if debt_line:
            lines.append(debt_line)
        if ctx:
            lines.append(ctx)
        if note_line:
            lines.append(note_line)
        lines.append(f"{conf_pct}% match")
        # stack whatever's present, top to bottom
        y = 182
        layout = {"eyebrow": {"x": 128, "y": y, "size": "sm",
                              "color": conf_color, "tracking": 3}}
        y += 18
        layout["primary"] = {"x": 128, "y": y, "size": "sm", "color": 0xFFFF}
        if relation:
            y += 16
            layout["relation"] = {"x": 128, "y": y, "size": "sm", "color": 0x2E9F}
        if debt_line:
            y += 16
            layout["debt"] = {"x": 128, "y": y, "size": "sm", "color": 0xFD20}
        if ctx:
            y += 16
            layout["detail"] = {"x": 128, "y": y, "size": "sm", "color": 0x5EF7}
        if note_line:
            y += 16
            layout["note"] = {"x": 128, "y": y, "size": "sm", "color": 0x2E9F}
        y += 16
        layout["footer"] = {"x": 128, "y": y, "size": "sm", "color": conf_color}
        return {
            "type": "SocialLensCard",
            "dismiss_ms": 5000,
            "eyebrow": "FACE RECALL",
            "primary": c.name,
            "relation": relation,
            "debt": debt_line,
            "detail": ctx,
            "note": note_line,
            "footer": f"{conf_pct}% match",
            "color": conf_color,
            "opacity": 0.9,
            "contact_id": c.contact_id,
            "confidence": m.confidence,
            "lines": lines,
            "layout": layout,
        }


def _latest_note(notes: Optional[str]) -> str:
    """The most recent freeform note on a contact (mirrors
    ContactEnricher.latest_note without importing it)."""
    if not notes:
        return ""
    parts = [p.strip() for p in notes.split(" • ") if p.strip()]
    return parts[-1] if parts else ""
