"""social_lens/schema.py — Data structures for SocialLens."""
from __future__ import annotations
from dataclasses import dataclass, field
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
    email        : email address (optional)
    """
    contact_id: str
    name: str
    embedding: list[float]
    company: Optional[str] = None
    role: Optional[str] = None
    last_met: Optional[str] = None
    notes: Optional[str] = None
    email: Optional[str] = None

    def __post_init__(self):
        if len(self.embedding) != 512:
            raise ValueError(
                f"ContactRecord embedding must be 512-d, got {len(self.embedding)}"
            )

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

        # Matched contact
        m = self.match
        c = m.contact
        conf_pct = round(m.confidence * 100)
        conf_color = 0x07E0 if m.confidence >= 0.85 else (
            0xFFE0 if m.confidence >= 0.70 else 0xFD20
        )
        note = _latest_note(c.notes)          # what you last asked to remember
        note_line = f"“{note}”" if note else ""
        lines = ["FACE RECALL", c.name, c.context_line()]
        if note_line:
            lines.append(note_line)
        lines.append(f"{conf_pct}% match")
        layout = {
            "eyebrow": {"x": 128, "y": 186, "size": "sm",
                        "color": conf_color, "tracking": 3},
            "primary": {"x": 128, "y": 204, "size": "sm", "color": 0xFFFF},
            "detail":  {"x": 128, "y": 220, "size": "sm", "color": 0x5EF7},
        }
        if note_line:
            layout["note"] = {"x": 128, "y": 236, "size": "sm", "color": 0x2E9F}
        layout["footer"] = {"x": 128, "y": 236 + (16 if note_line else 0),
                            "size": "sm", "color": conf_color}
        return {
            "type": "SocialLensCard",
            "dismiss_ms": 5000,
            "eyebrow": "FACE RECALL",
            "primary": c.name,
            "detail": c.context_line(),
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
