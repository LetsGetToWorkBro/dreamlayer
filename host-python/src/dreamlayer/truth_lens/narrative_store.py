"""truth_lens/narrative_store.py — Per-contact baseline storage + anomaly log."""
from __future__ import annotations
from typing import Optional
from .schema import ContactBaseline, AUFrame, ProsodyFrame, LinguisticFrame


class NarrativeStore:
    def __init__(self, memory_backend=None):
        self._backend = memory_backend or _DictStore()

    def get_baseline(self, contact_id: str) -> Optional[ContactBaseline]:
        return self._backend.get(f"truth_lens_baseline_{contact_id}")

    def save_baseline(self, baseline: ContactBaseline) -> None:
        self._backend.set(f"truth_lens_baseline_{baseline.contact_id}", baseline)

    def update_baseline(self, contact_id: str, au, prosody, linguistic) -> ContactBaseline:
        baseline = self.get_baseline(contact_id)
        if baseline is None:
            baseline = ContactBaseline(contact_id=contact_id)
        if au is not None and prosody is not None and linguistic is not None:
            baseline.update(au, prosody, linguistic)
            self.save_baseline(baseline)
        return baseline

    def log_anomaly(self, contact_id: str, deception_prob: float,
                    dominant_channel: str, user_label=None) -> None:
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

    def contact_count(self) -> int:
        return self._backend.count()


class _DictStore:
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

    def count(self) -> int:
        return len([k for k in self._data if k.startswith("truth_lens_baseline_")])
