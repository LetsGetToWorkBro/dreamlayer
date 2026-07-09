"""Validated HUD-answer objects (pydantic/instructor) over the plain dicts that
orchestrator/answer_builder.py returns.

ADD-alongside: new module. answer_builder.py is untouched. `validate_answer`
coerces a builder dict through a pydantic model when pydantic is installed
(extras group `structured`), catching malformed card payloads early; without
pydantic it returns the dict unchanged. Either way the shape is preserved, so
it's a safe optional hardening wrapper.
"""
from __future__ import annotations
import logging

log = logging.getLogger("dreamlayer.answer_validate")

try:  # optional dep — extras group `structured`
    from pydantic import BaseModel, ConfigDict  # type: ignore
    _HAS_PYDANTIC = True
except ImportError:
    _HAS_PYDANTIC = False


if _HAS_PYDANTIC:
    class AnswerCard(BaseModel):  # type: ignore[misc]
        model_config = ConfigDict(extra="allow")
        type: str = "AnswerCard"
        primary: str = ""
        confidence: float | None = None


def validate_answer(card: dict) -> dict:
    """Return a validated (or passthrough) card dict.

    Never raises on shape: on validation error it logs and returns the original
    dict, so this can wrap builder output without changing behaviour.
    """
    if not _HAS_PYDANTIC or not isinstance(card, dict):
        return card
    try:
        return AnswerCard(**card).model_dump()
    except Exception as exc:
        log.warning("[answer_validate] card failed validation: %s; passthrough", exc)
        return card
