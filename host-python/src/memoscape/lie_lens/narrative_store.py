"""lie_lens/narrative_store.py — Per-contact baseline storage + anomaly log.

In production this wraps the Halo Narrative agentic memory system.
In tests / offline mode it uses a simple in-process dict.
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np

from .schema import ContactBaseline, AnomalyRecord, AUFrame, ProsodyFrame, LinguisticFrame


class NarrativeStore:
    """Stores and retrieves per-contact baselines and anomaly logs.

    Parameters
    ----------
    backend : dict-like, optional
        Storage backend. Defaults to in-process dict (suitable for tests).
        In production, pass a Narrative-backed store.
    """

    def __init__(self, backend: Optional[dict] = None):
        self._db: dict = backend if backend is not None else {}

    # ------------------------------------------------------------------
    # Baseline management
    # ------------------------------------------------------------------

    def get_baseline(self, contact_id: str) -> Optional[ContactBaseline]:
        return self._db.get(f"baseline:{contact_id}")

    def save_baseline(self, baseline: ContactBaseline) -> None:
        self._db[f"baseline:{baseline.contact_id}"] = baseline

    def update_baseline_incremental(
        self,
        contact_id: str,
        au_frame: Optional[AUFrame],
        prosody_frame: Optional[ProsodyFrame],
        linguistic_frame: Optional[LinguisticFrame],
    ) -> ContactBaseline:
        """Online update of contact baseline using exponential moving average."""
        existing = self.get_baseline(contact_id)
        alpha = 0.05  # EMA weight for new sample

        if existing is None:
            # Initialise from first sample
            au_mean = au_frame.aus if au_frame else [0.15] * 17
            au_std = [0.1] * 17
            p_pitch_mean = prosody_frame.pitch_mean_hz if prosody_frame else 180.0
            p_pitch_std = 30.0
            p_jitter = prosody_frame.jitter_pct if prosody_frame else 0.5
            p_shimmer = prosody_frame.shimmer_pct if prosody_frame else 1.0
            l_hedge = linguistic_frame.hedging_score if linguistic_frame else 0.1
            l_fp = linguistic_frame.first_person_rate if linguistic_frame else 0.12
            existing = ContactBaseline(
                contact_id=contact_id,
                au_mean=au_mean,
                au_std=au_std,
                prosody_pitch_mean=p_pitch_mean,
                prosody_pitch_std=p_pitch_std,
                prosody_jitter_mean=p_jitter,
                prosody_shimmer_mean=p_shimmer,
                linguistic_hedge_mean=l_hedge,
                linguistic_fp_mean=l_fp,
                sample_count=1,
            )
        else:
            # EMA update
            if au_frame:
                existing.au_mean = [
                    (1 - alpha) * m + alpha * v
                    for m, v in zip(existing.au_mean, au_frame.aus)
                ]
            if prosody_frame:
                existing.prosody_pitch_mean = (
                    (1 - alpha) * existing.prosody_pitch_mean
                    + alpha * prosody_frame.pitch_mean_hz
                )
                existing.prosody_jitter_mean = (
                    (1 - alpha) * existing.prosody_jitter_mean
                    + alpha * prosody_frame.jitter_pct
                )
                existing.prosody_shimmer_mean = (
                    (1 - alpha) * existing.prosody_shimmer_mean
                    + alpha * prosody_frame.shimmer_pct
                )
            if linguistic_frame:
                existing.linguistic_hedge_mean = (
                    (1 - alpha) * existing.linguistic_hedge_mean
                    + alpha * linguistic_frame.hedging_score
                )
                existing.linguistic_fp_mean = (
                    (1 - alpha) * existing.linguistic_fp_mean
                    + alpha * linguistic_frame.first_person_rate
                )
            existing.sample_count += 1

        self.save_baseline(existing)
        return existing

    # ------------------------------------------------------------------
    # Anomaly log
    # ------------------------------------------------------------------

    def log_anomaly(self, contact_id: str, deception_prob: float,
                    dominant_signal: str,
                    user_label: Optional[str] = None) -> AnomalyRecord:
        record = AnomalyRecord(
            contact_id=contact_id,
            timestamp=time.time(),
            deception_prob=deception_prob,
            dominant_signal=dominant_signal,
            user_label=user_label,
        )
        key = f"anomalies:{contact_id}"
        log: list = self._db.get(key, [])
        log.append(record)
        # Keep last 100 anomalies per contact
        self._db[key] = log[-100:]
        return record

    def get_anomalies(self, contact_id: str) -> list[AnomalyRecord]:
        return self._db.get(f"anomalies:{contact_id}", [])

    # ------------------------------------------------------------------
    # Contact registry
    # ------------------------------------------------------------------

    def register_contact(self, contact_id: str, name: str,
                          embedding: np.ndarray) -> None:
        self._db[f"contact:{contact_id}"] = {
            "name": name, "embedding": embedding
        }
        # Keep master index
        idx: dict = self._db.get("contact_index", {})
        idx[contact_id] = embedding
        self._db["contact_index"] = idx

    def get_contact_name(self, contact_id: str) -> Optional[str]:
        entry = self._db.get(f"contact:{contact_id}")
        return entry["name"] if entry else None

    def get_contact_embeddings(self) -> dict[str, np.ndarray]:
        return dict(self._db.get("contact_index", {}))
