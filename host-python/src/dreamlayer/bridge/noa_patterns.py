"""bridge/noa_patterns.py — display/formatting patterns mined from Brilliant's
open reference assistants (noa-assistant, frame examples).

Pure helpers, NO dependency. These encode ground-truth conventions for turning a
DreamLayer card into the short, glanceable text a monocular waveguide can show —
title-first, one useful line, hard character budget — so the Frame adapter (and
any future minimal display target) formats consistently with Brilliant's own UX.

ADD-alongside: nothing in the host is edited; this is a reference/format utility.
"""
from __future__ import annotations

from typing import List

# A monocular line is short. noa/Frame examples keep body lines ~ this wide.
FRAME_LINE_CHARS = 32
FRAME_MAX_LINES = 5


def _wrap(text: str, width: int = FRAME_LINE_CHARS) -> List[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) <= width:
            cur = f"{cur} {w}".strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def card_to_frame_lines(card: dict, max_lines: int = FRAME_MAX_LINES) -> List[str]:
    """Flatten a DreamLayer card dict to a short list of display lines.

    Convention (from noa-assistant): TITLE on top, then the most useful body
    field wrapped to the line width, clipped to `max_lines`.
    """
    lines: List[str] = []
    title = str(card.get("title", "")).strip()
    if title:
        lines.append(title[:FRAME_LINE_CHARS])

    body = (card.get("answer") or card.get("summary") or card.get("body")
            or card.get("subtitle") or "")
    if isinstance(body, (list, tuple)):
        body = " ".join(str(b) for b in body)
    for ln in _wrap(str(body).strip()):
        if len(lines) >= max_lines:
            break
        lines.append(ln)
    return lines[:max_lines]
