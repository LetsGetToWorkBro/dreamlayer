"""extraction.py — legacy commitment extractor (delegates to IngestPipeline).

Kept for backward compatibility. New code should use IngestPipeline directly.
"""
from __future__ import annotations

# Legacy regex fallback (kept for callers that import extract_commitments directly)
PROMISE_CUES = ("i'll", "i will", "promise", "i can", "i'll send", "send")


def extract_commitments(conv: dict) -> list[dict]:
    """Extract commitment dicts from a structured conversation object.

    Accepts the old {turns: [{text, commitment, speaker}], participants: [...]}
    format. For raw transcript strings, use IngestPipeline.ingest() instead.
    """
    out = []
    for turn in conv.get("turns", []):
        text = turn.get("text", "").lower()
        if any(cue in text for cue in PROMISE_CUES) and turn.get("commitment"):
            c = turn["commitment"]
            out.append({
                "person": c.get("to") or _other(conv, turn.get("speaker")),
                "task":   c["task"],
                "due":    c.get("due", ""),
                "confidence": c.get("confidence", 0.8),
            })
    return out


def _other(conv: dict, speaker: str) -> str:
    for p in conv.get("participants", []):
        if p != speaker:
            return p
    return ""
