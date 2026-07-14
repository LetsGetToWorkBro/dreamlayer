"""logging_setup.py — opt-in structured logging for the Brain and the hub.

Default behaviour is unchanged (plain human logs). Set ``DL_LOG_JSON=1`` and
every log record becomes one JSON line — timestamp, level, logger, message,
plus any extra fields — so an operator running the Brain as a service (or a CI
run) gets machine-parseable logs without touching call sites.

    from dreamlayer.logging_setup import configure_logging
    configure_logging()          # reads DL_LOG_JSON / DL_LOG_LEVEL from env

Idempotent: safe to call more than once (it replaces its own handler).
"""
from __future__ import annotations

import json
import logging
import os

_HANDLER_TAG = "_dreamlayer_handler"

# Standard LogRecord attributes we never treat as "extra" payload.
_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName",
}


class JsonLineFormatter(logging.Formatter):
    """One compact JSON object per record; extras (logger.info(msg, extra={…}))
    ride alongside the standard fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, val in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                try:
                    json.dumps(val)          # only serialisable extras
                    payload[key] = val
                except (TypeError, ValueError):
                    payload[key] = repr(val)
        return json.dumps(payload, separators=(",", ":"))


def configure_logging(json_mode: bool | None = None,
                      level: str | None = None) -> None:
    """Install DreamLayer's root handler. ``json_mode``/``level`` default to the
    env (``DL_LOG_JSON``, ``DL_LOG_LEVEL``). Replaces a previously-installed
    DreamLayer handler so repeated calls don't stack."""
    if json_mode is None:
        # case-insensitive + common falsy spellings, so DL_LOG_JSON=False/off/no
        # correctly DISABLE json mode rather than enabling it (audit 2026-07-14).
        json_mode = os.environ.get("DL_LOG_JSON", "").strip().lower() not in (
            "", "0", "false", "off", "no")
    lvl = (level or os.environ.get("DL_LOG_LEVEL", "INFO")).upper()

    root = logging.getLogger()
    root.setLevel(getattr(logging, lvl, logging.INFO))
    # drop any handler we installed earlier (idempotent)
    root.handlers = [h for h in root.handlers
                     if not getattr(h, _HANDLER_TAG, False)]

    handler = logging.StreamHandler()
    setattr(handler, _HANDLER_TAG, True)
    if json_mode:
        handler.setFormatter(JsonLineFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%H:%M:%S"))
    root.addHandler(handler)
