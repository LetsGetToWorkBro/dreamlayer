"""orchestrator/health.py — the per-seam failure ledger.

Silent degradation is the right call for the WEARER (a glasses HUD must
never show a stack trace); it is the wrong call for the BUILDER. Before
this ledger, every brain error became an empty answer, every dead tier a
silent skip — graceful for the user, undiagnosable for whoever runs the
system ("the cloud tier failed 40 times this hour" was invisible).

Every degrading `except` records here before it degrades. The ledger is
cheap (counters + a small ring of recent errors per seam), thread-safe,
and surfaced wherever the host exposes status (the Brain panel's
/dreamlayer/health, the hub's summary()).
"""
from __future__ import annotations

import threading
import time
from collections import deque

# canonical seam names — keep in sync with the wiring sites
SEAMS = ("cloud", "mac", "ollama", "ble", "asr", "vision", "brain",
         "ann", "plugin", "deadline", "api-brain")

_RING = 8


class HealthLedger:
    def __init__(self, now_fn=None) -> None:
        self._now = now_fn or time.time
        self._lock = threading.Lock()
        self._fail: dict[str, int] = {}
        self._ok: dict[str, int] = {}
        self._recent: dict[str, deque] = {}
        self._lat: dict[str, float] = {}       # seam -> EWMA latency (ms)

    def record_failure(self, seam: str, error: object = "") -> None:
        with self._lock:
            self._fail[seam] = self._fail.get(seam, 0) + 1
            ring = self._recent.setdefault(seam, deque(maxlen=_RING))
            ring.append({"ts": self._now(),
                         "error": str(error)[:200]})

    def record_ok(self, seam: str, ms: float | None = None) -> None:
        with self._lock:
            self._ok[seam] = self._ok.get(seam, 0) + 1
            if ms is not None:
                # a smoothed round-trip so a live "how fast is this tier"
                # readout doesn't jitter on one slow call
                prev = self._lat.get(seam)
                self._lat[seam] = float(ms) if prev is None else \
                    prev + 0.3 * (float(ms) - prev)

    def failures(self, seam: str) -> int:
        with self._lock:
            return self._fail.get(seam, 0)

    def snapshot(self) -> dict:
        """{seam: {failures, successes, last_error, last_ts}} for every seam
        that has ever reported."""
        with self._lock:
            out = {}
            for seam in set(self._fail) | set(self._ok):
                ring = self._recent.get(seam)
                last = ring[-1] if ring else None
                out[seam] = {
                    "failures": self._fail.get(seam, 0),
                    "successes": self._ok.get(seam, 0),
                    "last_error": last["error"] if last else "",
                    "last_ts": last["ts"] if last else 0.0,
                }
                if seam in self._lat:
                    out[seam]["latency_ms"] = round(self._lat[seam], 1)
            return out

    def recent(self, seam: str) -> list:
        with self._lock:
            return list(self._recent.get(seam, ()))
