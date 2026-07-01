"""lucid_recall/schema.py — Data structures for Lucid Recall."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class QueryType(Enum):
    FACE = "face"         # Who is this person?
    FACT = "fact"         # What did we discuss last time?
    CONTEXT = "context"   # What do I know about this person?
    UNKNOWN = "unknown"


@dataclass
class LucidRecallResult:
    query_type: QueryType
    answer: str
    confidence: float          # 0.0 – 1.0
    contact_id: Optional[str] = None
    contact_name: Optional[str] = None
    detail: Optional[str] = None
    source: Optional[str] = None   # "social_lens", "memory", "combined"

    def to_hud_card(self) -> dict:
        conf_color = (
            0x07E0 if self.confidence >= 0.80 else
            0xFFE0 if self.confidence >= 0.60 else
            0x7BEF
        )
        return {
            "type": "LucidRecallCard",
            "dismiss_ms": 5000,
            "eyebrow": "LUCID RECALL",
            "primary": self.answer,
            "detail": self.detail or "",
            "footer": self.contact_name or "",
            "color": conf_color,
            "opacity": 0.9,
            "confidence": round(self.confidence, 2),
            "query_type": self.query_type.value,
            "lines": ["LUCID RECALL", self.answer,
                      self.detail or "", self.contact_name or ""],
            "layout": {
                "eyebrow": {"x": 128, "y": 192, "size": "sm",
                            "color": conf_color, "tracking": 3},
                "primary": {"x": 128, "y": 210, "size": "sm", "color": 0xFFFF},
                "detail":  {"x": 128, "y": 226, "size": "sm", "color": 0x5EF7},
                "footer":  {"x": 128, "y": 242, "size": "sm", "color": conf_color},
            },
        }
