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

import hashlib
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

# Extra keys whose *values* are treated as sensitive PII/secrets and never
# written verbatim to a log line. Compared case-insensitively (see
# ``_is_sensitive``). The JSON formatter serialises every non-reserved extra
# verbatim, so absent this list a caller passing names/embeddings/transcripts
# in ``extra={…}`` would leak them into logs if logs ever ship. Keep this
# conservative-but-broad; extend as new sensitive fields appear.
_SENSITIVE_KEYS = {
    "name", "names", "summary", "transcript", "transcripts",
    "embedding", "embeddings", "contact", "contacts", "query", "answer",
    "token", "api_key", "apikey", "key", "secret", "secrets", "password",
    "passphrase", "text", "caption", "captions", "email", "phone",
    "address", "prompt", "content", "message_body", "credential",
    "credentials", "auth", "authorization", "session", "cookie",
}


# Substring roots: a key whose separator-stripped form CONTAINS one of these is
# sensitive, so single-word compounds and camelCase (username, userName→username,
# fullname, authToken→authtoken, homeAddress) are caught, not just ``_``-suffixed
# forms. Over-redaction is the safe direction for a privacy-first logger.
_SENSITIVE_ROOTS = (
    "name", "email", "phone", "address", "token", "secret", "password",
    "passphrase", "credential", "apikey", "transcript", "embedding",
    "contact", "summary", "caption", "passcode", "ssn",
)


def _is_sensitive(key: str) -> bool:
    """A key is sensitive if its normalised form matches a known-sensitive key
    exactly, ends with ``_<sensitive>``, OR contains a sensitive root as a
    substring (so ``username``/``userEmail``/``authToken`` are caught, not only
    ``user_name``). Case- and separator-insensitive."""
    norm = key.strip().lower().replace("-", "_")
    if norm in _SENSITIVE_KEYS:
        return True
    if any(norm.endswith("_" + s) for s in _SENSITIVE_KEYS):
        return True
    flat = norm.replace("_", "")
    return any(root in flat for root in _SENSITIVE_ROOTS)


def _sanitize(val: object, depth: int = 0) -> object:
    """Recursively redact sensitive keys *inside* a structured extra value, so a
    transcript/name nested under a benign key (``extra={"result": {"name": …}}``)
    can't slip through the top-level key check. Bounded depth guards cycles."""
    if depth > 6:
        return "<max-depth>"
    if isinstance(val, dict):
        return {str(k): (_redact(v) if _is_sensitive(str(k))
                         else _sanitize(v, depth + 1)) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_sanitize(v, depth + 1) for v in val]
    return val


def _redact(val: object) -> str:
    """Replace a sensitive value with a stable, non-reversible marker. The
    short hash lets an operator correlate repeated values across log lines
    without ever exposing the plaintext."""
    try:
        raw = json.dumps(val, separators=(",", ":"), sort_keys=True,
                         default=repr)
    except (TypeError, ValueError):
        raw = repr(val)
    digest = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:8]
    return f"<redacted:{digest}>"


class JsonLineFormatter(logging.Formatter):
    """One compact JSON object per record; extras (logger.info(msg, extra={…}))
    ride alongside the standard fields. Values under known-sensitive keys are
    redacted (replaced with a ``<redacted:hash>`` marker) before serialisation
    so PII/secrets never reach the log line."""

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
                if _is_sensitive(key):
                    payload[key] = _redact(val)
                    continue
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
