"""truth_lens/narrative_store.py — Per-contact baseline storage + anomaly log.

Maps to the Narrative (agentic memory system) integration in the Lua spec.
In production this reads/writes to the existing DreamLayer memory layer.
In test/standalone mode it uses an in-memory dict store.
"""
from __future__ import annotations

from typing import Optional

from .schema import (
    ContactBaseline, AUFrame, ProsodyFrame, LinguisticFrame,
)


class NarrativeStore:
    """Stores per-contact baselines and anomaly logs.

    Designed to wrap the existing DreamLayer memory layer:
      narrative.get / narrative.set / narrative.push
    Defaults to an in-memory dict for test/standalone use.
    """

    def __init__(self, memory_backend=None):
        """
        Parameters
        ----------
        memory_backend : object, optional
            An object with get(key), set(key, value), push(key, value).
            Defaults to a simple in-memory dict store.
        """
        self._backend = memory_backend or _DictStore()

    # ------------------------------------------------------------------
    # Baseline API
    # ------------------------------------------------------------------

    def get_baseline(self, contact_id: str) -> Optional[ContactBaseline]:
        """Load the baseline for a contact, or None if not yet calibrated."""
        return self._backend.get(f"truth_lens_baseline_{contact_id}")

    def save_baseline(self, baseline: ContactBaseline) -> None:
        self._backend.set(
            f"truth_lens_baseline_{baseline.contact_id}", baseline
        )

    def update_baseline(
        self,
        contact_id: str,
        au: Optional[AUFrame],
        prosody: Optional[ProsodyFrame],
        linguistic: Optional[LinguisticFrame],
    ) -> ContactBaseline:
        """Incrementally update baseline with new data. Creates if absent."""
        baseline = self.get_baseline(contact_id)
        if baseline is None:
            baseline = ContactBaseline(contact_id=contact_id)

        if au is not None and prosody is not None and linguistic is not None:
            baseline.update(au, prosody, linguistic)
            self.save_baseline(baseline)

        return baseline

    # ------------------------------------------------------------------
    # Anomaly log API
    # ------------------------------------------------------------------

    def log_anomaly(
        self,
        contact_id: str,
        deception_prob: float,
        dominant_channel: str,
        user_label: Optional[str] = None,
    ) -> None:
        """Append an anomaly event to the contact's log."""
        import time
        entry = {
            "timestamp": time.time(),
            "deception_prob": deception_prob,
            "dominant_channel": dominant_channel,
            "user_label": user_label,
        }
        self._backend.push(f"truth_lens_anomaly_{contact_id}", entry)

    def get_anomaly_log(self, contact_id: str) -> list:
        return self._backend.get(f"truth_lens_anomaly_{contact_id}") or []

    def forget(self, contact_id: str) -> None:
        """Erase everything stored ABOUT a person — their deception baseline and
        their anomaly log. Structured judgments about known people must die with
        "forget that" like any other memory; without this hook they persisted
        indefinitely with no erase path (audit 2026-07-14)."""
        for key in (f"truth_lens_baseline_{contact_id}",
                    f"truth_lens_anomaly_{contact_id}"):
            deleter = getattr(self._backend, "delete", None)
            if callable(deleter):
                deleter(key)
            else:
                self._backend.set(key, None)

    def forget_all(self) -> None:
        """Erase EVERY stored deception baseline and anomaly log — the
        erase-everything path (audit refute 2026-07: session reset() does not
        reach the per-contact store; only this and forget(cid) do)."""
        clearer = getattr(self._backend, "clear", None)
        if callable(clearer):
            clearer()

    def contact_count(self) -> int:
        return self._backend.count()


class _DictStore:
    """Simple in-memory backend (for tests and standalone use)."""

    def __init__(self):
        self._data: dict = {}

    def get(self, key: str):
        return self._data.get(key)

    def set(self, key: str, value) -> None:
        self._data[key] = value

    def push(self, key: str, value) -> None:
        if key not in self._data:
            self._data[key] = []
        self._data[key].append(value)

    def clear(self) -> None:
        self._data.clear()

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def count(self) -> int:
        return len([k for k in self._data if k.startswith("truth_lens_baseline_")])
