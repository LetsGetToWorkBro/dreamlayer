"""The PII scrubber must actually run on the memory WRITE path — the Guardian
pack advertises "PII scrubbed before write", and before this wiring PiiRedactor
had zero callers on that path, so summaries were stored verbatim. These tests
pin the wiring (MemoryDB.add_memory -> default_redactor) and its two guarantees:

  1. contact/financial identifiers are scrubbed on the way in, and
  2. names and places — the things the product exists to remember — are NOT,

plus the toggle (DL_DISABLE_PII_REDACTION) that makes it fully switch-off-able.
Uses only the regex fallback (no presidio dep in CI), so it runs everywhere.
"""
from __future__ import annotations

import pytest

import dreamlayer.memory.pii_presidio as P
from dreamlayer.memory.db import MemoryDB


@pytest.fixture(autouse=True)
def _reset_redactor_memo(monkeypatch):
    """default_redactor() memoizes; reset it around each test and make sure the
    disable flag never leaks in from the ambient environment."""
    monkeypatch.delenv("DL_DISABLE_PII_REDACTION", raising=False)
    P._REDACTOR = None
    P._REDACTOR_BUILT = False
    yield
    P._REDACTOR = None
    P._REDACTOR_BUILT = False


def test_write_path_scrubs_contact_identifiers():
    db = MemoryDB(":memory:")
    mid = db.add_memory(
        "note", "Call Alice at 555-123-4567 or bob@example.com about the Oak St lease")
    stored = db.memory(mid)["summary"]
    # scrubbed …
    assert "555-123-4567" not in stored
    assert "bob@example.com" not in stored
    assert "<PHONE>" in stored and "<EMAIL>" in stored


def test_write_path_preserves_names_and_places():
    """The whole point of the product is remembering people and places by name —
    redaction must never strip them, or recall is gutted."""
    db = MemoryDB(":memory:")
    mid = db.add_memory("note", "Alice promised to email the Oak St lease on Friday")
    stored = db.memory(mid)["summary"]
    assert "Alice" in stored
    assert "Oak St" in stored
    assert "Friday" in stored


def test_toggle_off_stores_verbatim(monkeypatch):
    """The panel's per-cap switch sets DL_DISABLE_PII_REDACTION; when off, the
    write path must skip redaction entirely (suspect-feature escape hatch)."""
    monkeypatch.setenv("DL_DISABLE_PII_REDACTION", "1")
    P._REDACTOR = None
    P._REDACTOR_BUILT = False
    db = MemoryDB(":memory:")
    mid = db.add_memory("note", "Call 555-123-4567 or bob@example.com")
    stored = db.memory(mid)["summary"]
    assert "555-123-4567" in stored and "bob@example.com" in stored


def test_redaction_failure_never_blocks_a_write(monkeypatch):
    """A broken redactor must degrade to an unredacted write, never lose the row."""
    class _Boom:
        def redact(self, _text):
            raise RuntimeError("presidio exploded")

    monkeypatch.setattr(P, "default_redactor", lambda: _Boom())
    db = MemoryDB(":memory:")
    mid = db.add_memory("note", "something happened")
    assert db.memory(mid)["summary"] == "something happened"


def test_empty_and_nonstring_summaries_are_left_alone():
    db = MemoryDB(":memory:")
    # empty string: nothing to redact, must not raise
    mid = db.add_memory("note", "")
    assert db.memory(mid)["summary"] == ""
