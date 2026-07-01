"""face_recall/enricher.py — Contact record enrichment.

Loads the full contact record for a matched contact_id:
  - Name, company, role, email from the address book
  - Last-met date from the Memoscape memory layer
  - Personal notes
  - Optional: calendar context (next/last meeting)

In production this integrates with the existing Memoscape
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
        return self._backend.get(f"face_recall_last_met_{contact_id}")

    def set_last_met(self, contact_id: str, date_str: str) -> None:
        """Record a new last-met date."""
        self._backend.set(f"face_recall_last_met_{contact_id}", date_str)

    def get_notes(self, contact_id: str) -> Optional[str]:
        """Return personal notes for a contact."""
        return self._backend.get(f"face_recall_notes_{contact_id}")

    def set_notes(self, contact_id: str, notes: str) -> None:
        self._backend.set(f"face_recall_notes_{contact_id}", notes)

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
