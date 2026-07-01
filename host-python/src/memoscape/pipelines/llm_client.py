"""llm_client.py — GPT-4o-mini structured extraction (Tier 3).

Lazy-imports openai so the rest of the codebase has no hard dependency.
All errors are caught and logged; callers always get a list (possibly empty).

Usage
-----
from memoscape.pipelines.llm_client import LLMClient
from memoscape.config import CONFIG

client = LLMClient(CONFIG)
events = client.extract(transcript, context)
"""
from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ingest import MemoryEvent

log = logging.getLogger("memoscape.llm")

_SYSTEM_PROMPT = """\
You are a memory extraction engine for a wearable assistant.
Given a transcript, extract structured memory events as JSON.

Return ONLY valid JSON in this exact shape:
{"events": [
  {"kind": "<object|person|place|promise|task>",
   "summary": "<one concise sentence>",
   "confidence": <0.0-1.0>,
   "meta": {<relevant fields>}}
]}

Kind rules:
  object  — a physical item and where it is  (meta: object, place)
  person  — a person mentioned               (meta: person)
  place   — a location                       (meta: place)
  promise — a commitment made                (meta: person, task, due)
  task    — a to-do or reminder              (meta: task)

Confidence guide:
  0.95  explicitly stated fact
  0.80  clear implication
  0.65  reasonable inference

Return an empty events array if nothing memorable is said.
Do not add commentary outside the JSON object.
"""


class LLMClient:
    """Wraps openai.OpenAI for structured transcript extraction."""

    def __init__(self, config):
        self._config = config
        self._client = None  # lazy-loaded

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import openai  # type: ignore
        except ImportError:
            log.warning("[llm] openai package not installed; tier-3 disabled")
            return None

        api_key = (
            getattr(self._config, "openai_api_key", "") or
            os.environ.get("OPENAI_API_KEY", "")
        )
        if not api_key:
            log.warning("[llm] OPENAI_API_KEY not set; tier-3 disabled")
            return None

        self._client = openai.OpenAI(
            api_key=api_key,
            timeout=getattr(self._config, "llm_timeout_s", 4.0),
        )
        return self._client

    def extract(self, transcript: str, context: dict | None = None) -> list["MemoryEvent"]:
        """Call GPT-4o-mini and return list[MemoryEvent]. Never raises."""
        from .ingest import MemoryEvent  # local import avoids circular

        client = self._get_client()
        if client is None:
            return []

        # Build user message: inject context hints if available
        context = context or {}
        user_parts = [f'Transcript: "{transcript}"']
        if context.get("location"):
            user_parts.append(f'Current location: {context["location"]}')
        if context.get("people"):
            user_parts.append(f'Known people present: {", ".join(context["people"])}')
        user_msg = "\n".join(user_parts)

        model = getattr(self._config, "llm_model", "gpt-4o-mini")

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=512,
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
        except Exception as exc:
            log.error("[llm] extraction failed: %s", exc)
            return []

        events: list[MemoryEvent] = []
        for item in data.get("events", []):
            kind = item.get("kind", "")
            if kind not in ("object", "person", "place", "promise", "task"):
                continue
            summary = str(item.get("summary", "")).strip()
            if not summary:
                continue
            conf = float(item.get("confidence", 0.75))
            meta = item.get("meta") or {}
            events.append(MemoryEvent(
                kind=kind,
                summary=summary,
                confidence=conf,
                source="llm",
                meta=meta,
            ))

        log.info("[llm] extracted %d events from transcript", len(events))
        return events
