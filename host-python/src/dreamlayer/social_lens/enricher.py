"""social_lens/enricher.py — Contact record enrichment.

Loads the full contact record for a matched contact_id:
  - Name, company, role, email from the address book
  - Last-met date from the DreamLayer memory layer
  - Personal notes
  - Optional: calendar context (next/last meeting)

In production this integrates with the existing DreamLayer
memory and contacts systems. Here we provide a clean interface
and an in-memory dict backend for test/standalone use.
"""
from __future__ import annotations

from typing import Optional

from .schema import ContactRecord


class ContactEnricher:
    """Enriches a ContactRecord with memory-layer context.

    Parameters
    ----------
    memory_backend : object, optional
        Object with get(key) -> value and set(key, value).
        Defaults to in-memory dict.
    """

    def __init__(self, memory_backend=None):
        self._backend = memory_backend or _DictBackend()

    def get_last_met(self, contact_id: str) -> Optional[str]:
        """Return ISO-8601 date of last interaction, or None."""
        return self._backend.get(f"social_lens_last_met_{contact_id}")

    def set_last_met(self, contact_id: str, date_str: str) -> None:
        """Record a new last-met date."""
        self._backend.set(f"social_lens_last_met_{contact_id}", date_str)

    def get_notes(self, contact_id: str) -> Optional[str]:
        """Return personal notes for a contact."""
        return self._backend.get(f"social_lens_notes_{contact_id}")

    def set_notes(self, contact_id: str, notes: str) -> None:
        self._backend.set(f"social_lens_notes_{contact_id}", notes)

    NOTE_SEP = " • "
    NOTES_MAX = 240                       # keep the record light; trim the oldest

    def append_note(self, contact_id: str, note: str) -> str:
        """Add one freeform note to a contact, keeping the ones already there.
        Idempotent for an identical note; the newest is kept last (it's what
        the recall card shows). Returns the full notes string after the add."""
        note = " ".join((note or "").split()).strip(" .")
        if not note:
            return self.get_notes(contact_id) or ""
        existing = self.get_notes(contact_id) or ""
        parts = [p.strip() for p in existing.split(self.NOTE_SEP) if p.strip()]
        low = note.lower()
        parts = [p for p in parts if p.lower() != low]      # dedupe / move to end
        parts.append(note)
        merged = self.NOTE_SEP.join(parts)
        while len(merged) > self.NOTES_MAX and len(parts) > 1:
            parts.pop(0)                                    # drop the oldest
            merged = self.NOTE_SEP.join(parts)
        self.set_notes(contact_id, merged)
        return merged

    @staticmethod
    def latest_note(notes: Optional[str]) -> str:
        """The most recent note (what the recall card highlights)."""
        if not notes:
            return ""
        parts = [p.strip() for p in notes.split(ContactEnricher.NOTE_SEP) if p.strip()]
        return parts[-1] if parts else ""

    def enrich(self, contact: ContactRecord) -> ContactRecord:
        """Return a copy of the ContactRecord enriched with stored context."""
        last_met = self.get_last_met(contact.contact_id)
        notes = self.get_notes(contact.contact_id)
        return ContactRecord(
            contact_id=contact.contact_id,
            name=contact.name,
            embedding=contact.embedding,
            company=contact.company,
            role=contact.role,
            last_met=last_met or contact.last_met,
            notes=notes or contact.notes,
            email=contact.email,
        )

    def record_encounter(self, contact_id: str) -> None:
        """Update last-met to today's date."""
        import datetime
        today = datetime.date.today().isoformat()
        self.set_last_met(contact_id, today)


class _DictBackend:
    def __init__(self):
        self._data: dict = {}

    def get(self, key: str):
        return self._data.get(key)

    def set(self, key: str, value) -> None:
        self._data[key] = value
