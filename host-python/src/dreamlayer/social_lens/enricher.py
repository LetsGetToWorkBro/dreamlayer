"""social_lens/enricher.py — Contact record enrichment."""
from __future__ import annotations
from typing import Optional
from .schema import ContactRecord


class ContactEnricher:
    def __init__(self, memory_backend=None):
        self._backend = memory_backend or _DictBackend()

    def get_last_met(self, contact_id: str) -> Optional[str]:
        return self._backend.get(f"social_lens_last_met_{contact_id}")

    def set_last_met(self, contact_id: str, date_str: str) -> None:
        self._backend.set(f"social_lens_last_met_{contact_id}", date_str)

    def get_notes(self, contact_id: str) -> Optional[str]:
        return self._backend.get(f"social_lens_notes_{contact_id}")

    def set_notes(self, contact_id: str, notes: str) -> None:
        self._backend.set(f"social_lens_notes_{contact_id}", notes)

    def enrich(self, contact: ContactRecord) -> ContactRecord:
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
        import datetime
        self.set_last_met(contact_id, datetime.date.today().isoformat())


class _DictBackend:
    def __init__(self):
        self._data: dict = {}

    def get(self, key: str):
        return self._data.get(key)

    def set(self, key: str, value) -> None:
        self._data[key] = value
