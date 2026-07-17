"""test_logging_discipline.py — CI enforcement of the "no PII in the log MESSAGE
string" contract.

logging_setup.JsonLineFormatter redacts sensitive values passed via
``extra={...}`` (``_is_sensitive``/``_sanitize`` scrub them), but it emits the
rendered message — ``record.getMessage()`` — VERBATIM, deliberately un-redacted
(redacting arbitrary prose would mangle legit logs). So a caller that interpolates
a sensitive value INTO the message string itself bypasses the scrub entirely::

    log.info(f"reply={juno_text}")        # f-string          -> leaks juno_text
    log.info("name=%s", user_name)        # %-lazy args        -> getMessage() renders it
    log.warning("email=%s" % email)       # %-format BinOp     -> leaks email

Nothing at runtime prevents this; the tree stays clean by caller discipline alone.
This test turns that discipline into a CI gate. It AST-scans the shipped source
(``dreamlayer/``, tests excluded) for logging call sites whose *message* argument
interpolates a value whose IDENTIFIER matches a sensitive root the redactor
already knows — the roots are imported from ``logging_setup`` so the guard and the
redactor can never drift — and fails with a ``file:line`` pointer telling the
author to pass the value via ``extra={}`` instead.

Tuned to zero false positives on the current tree: the only sensitive-looking
identifiers interpolated today are bare ``name`` / ``__name__`` (a plugin/store/
stage/config-key name, or ``type(exc).__name__``) — generic code identifiers, not
person names — which are carved out in ``_GUARD_GENERIC``. Person-name FIELDS
(``user_name``, ``contact_name``, ``display_name``, ``nickname``, ``username``,
``full_name``) are NOT carved out and still trip, as do ``reply``/``transcript``/
``email``/``token``/``secret``/``password``/``embedding``/``api_key`` etc.
"""
from __future__ import annotations

import ast
from pathlib import Path

import dreamlayer
from dreamlayer.logging_setup import _SENSITIVE_ROOTS, _is_sensitive

# The logging emit methods (Logger + the ``logging`` module helpers). ``log``
# alone takes a leading level arg, so its message is the SECOND positional.
_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception",
                "critical", "fatal", "log"}
# Receiver names we treat as a logger: the module convention is
# ``log = logging.getLogger(...)``; also ``logger``/``logging`` and self-attrs.
_LOG_RECEIVERS = {"log", "logger", "logging", "_log", "_logger"}

# Generic CODE identifiers that match a sensitive root only by loose substring
# (chiefly the "name" root: __name__/filename/hostname/classname…) and never
# carry PII in this codebase. Kept explicit and minimal so the guard stays
# honest — a person-name field (user_name, contact_name, display_name, nickname,
# username, full_name) is deliberately absent and still trips. Bare ``name`` is
# here because in this tree it denotes a plugin/store/stage/config-key/model
# identifier, not a person; label a real person's name field descriptively and
# the guard catches it.
_GUARD_GENERIC = frozenset({
    "name", "names",           # generic record/plugin/store/stage/model id
    "__name__",                # class/module dunder, e.g. type(exc).__name__
    "filename", "filenames", "basename", "dirname", "pathname",
    "hostname", "classname", "typename", "funcname", "fieldname",
    "nodename", "modname", "varname", "fname", "qname",
})


def _guard_sensitive(identifier: str) -> bool:
    """A leaked identifier: sensitive per the redactor's own rule, minus the
    generic code identifiers that only match the loose 'name' substring root."""
    if identifier in _GUARD_GENERIC:
        return False
    return _is_sensitive(identifier)


def _sensitive_identifiers(node: ast.AST) -> set[str]:
    """Sensitive names referenced anywhere inside an interpolated expression —
    both bare names (``reply``) and attribute tails (``obj.transcript``)."""
    hits: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and _guard_sensitive(n.id):
            hits.add(n.id)
        elif isinstance(n, ast.Attribute) and _guard_sensitive(n.attr):
            hits.add(n.attr)
    return hits


def _is_log_call(call: ast.Call) -> str | None:
    """The method name if ``call`` is a ``log``/``logger``/``logging`` emit, else
    None. Matches ``log.info(...)``, ``self.logger.error(...)``, ``logging.warning``."""
    f = call.func
    if not isinstance(f, ast.Attribute) or f.attr not in _LOG_METHODS:
        return None
    recv = f.value
    names: set[str] = set()
    if isinstance(recv, ast.Name):
        names.add(recv.id)
    elif isinstance(recv, ast.Attribute):
        names.add(recv.attr)           # self.logger -> "logger"
    return f.attr if names & _LOG_RECEIVERS else None


def _interpolated_leaks(msg: ast.expr, fmt_args: list[ast.expr]) -> set[str]:
    """Sensitive identifiers interpolated into a message, across every form:
    f-string, %-format / concat BinOp, ``.format(...)``, and %-lazy args."""
    hits: set[str] = set()
    # f-string:  log.info(f"reply={juno_text}")
    if isinstance(msg, ast.JoinedStr):
        for part in msg.values:
            if isinstance(part, ast.FormattedValue):
                hits |= _sensitive_identifiers(part.value)
    # %-format or concat:  log.info("email=%s" % email) / "a" + reply
    if isinstance(msg, ast.BinOp) and isinstance(msg.op, (ast.Mod, ast.Add)):
        hits |= _sensitive_identifiers(msg.left)
        hits |= _sensitive_identifiers(msg.right)
    # str.format:  log.info("reply={}".format(juno_text))
    if (isinstance(msg, ast.Call) and isinstance(msg.func, ast.Attribute)
            and msg.func.attr == "format"):
        for a in msg.args:
            hits |= _sensitive_identifiers(a)
        for kw in msg.keywords:
            hits |= _sensitive_identifiers(kw.value)
    # %-lazy args:  log.info("name=%s", user_name)  -> getMessage() renders it
    for a in fmt_args:
        hits |= _sensitive_identifiers(a)
    return hits


def _scan_source(src: str, filename: str) -> list[str]:
    """Return a ``file:line`` violation per logging call that interpolates a
    sensitive value into its message string."""
    tree = ast.parse(src, filename=filename)
    out: list[str] = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        method = _is_log_call(call)
        if not method or not call.args:
            continue
        # ``log(level, msg, *args)`` puts the message second; everything else first.
        msg_idx = 1 if method == "log" else 0
        if msg_idx >= len(call.args):
            continue
        msg = call.args[msg_idx]
        fmt_args = call.args[msg_idx + 1:]
        leaks = _interpolated_leaks(msg, fmt_args)
        if leaks:
            line = getattr(msg, "lineno", call.lineno)
            names = ", ".join(sorted(leaks))
            out.append(f"{filename}:{line}: log.{method}(...) interpolates "
                       f"sensitive value(s) {{{names}}} into the message string")
    return out


def _source_files() -> list[Path]:
    root = Path(dreamlayer.__file__).resolve().parent
    return [p for p in sorted(root.rglob("*.py"))
            if "/tests/" not in p.as_posix() and "__pycache__" not in p.as_posix()]


def test_no_pii_interpolated_into_log_messages():
    """The whole shipped source obeys the extra={}-only contract: no logging call
    interpolates a sensitive-named value into its message string. FAILS with a
    file:line pointer if any does — move the value to extra={} so
    JsonLineFormatter can redact it."""
    # the roots are the redactor's own, so the guard can never silently drift
    assert _SENSITIVE_ROOTS, "sensitive roots vanished from logging_setup"
    violations: list[str] = []
    for path in _source_files():
        violations.extend(_scan_source(path.read_text(encoding="utf-8"), str(path)))
    assert not violations, (
        "sensitive value interpolated into a log MESSAGE string (bypasses the "
        "extra={}-only redaction seam in logging_setup.JsonLineFormatter). Pass "
        "it via extra={...} instead so it is redacted:\n  " + "\n  ".join(violations))


def test_scanner_catches_fstring_leak():
    src = ('import logging\nlog = logging.getLogger("x")\n'
           'def f(juno_text):\n    log.info(f"reply={juno_text}")\n')
    assert _scan_source(src, "planted.py"), "f-string PII leak not caught"


def test_scanner_catches_percent_lazy_args_leak():
    # the exact idiom the module docstring warns about; getMessage() renders it
    src = ('import logging\nlog = logging.getLogger("x")\n'
           'def f(user_name):\n    log.info("hello %s", user_name)\n')
    assert _scan_source(src, "planted.py"), "%-lazy-args PII leak not caught"


def test_scanner_catches_percent_format_and_format_call():
    binop = ('import logging\nlog = logging.getLogger("x")\n'
             'def f(email):\n    log.warning("to=%s" % email)\n')
    fmt = ('import logging\nlog = logging.getLogger("x")\n'
           'def f(transcript):\n    log.error("t={}".format(transcript))\n')
    assert _scan_source(binop, "a.py"), "%-format PII leak not caught"
    assert _scan_source(fmt, "b.py"), ".format() PII leak not caught"


def test_scanner_ignores_benign_interpolation():
    # the benign forms that MUST NOT trip: non-sensitive counters, and the
    # generic 'name'/__name__ identifiers the current tree already interpolates.
    benign = [
        'log.info("indexed %d rows", n)',
        'log.info(f"loaded {count} plugins in {ms}ms")',
        'log.warning("plugin %r failed", name, exc_info=True)',
        'log.warning("skipped (%s)", type(exc).__name__)',
        'log.info("connecting to %s:%d", hostname, port)',
        'log.debug("wrote %s", filename)',
    ]
    for expr in benign:
        src = f'import logging\nlog = logging.getLogger("x")\n{expr}\n'
        assert not _scan_source(src, "benign.py"), f"false positive on: {expr}"
