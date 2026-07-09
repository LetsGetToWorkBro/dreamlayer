"""pipelines/lsl_transport.py — an optional Lab Streaming Layer (LSL) transport
for streaming sensor/marker samples to research tooling.

LSL (labstreaminglayer / pylsl) is the lingua franca for time-synced biosignal
and marker streams — handy for anyone wiring Halo's IMU / gaze / event markers
into an experiment recorder alongside EEG, eye-trackers, etc.

ADD-alongside: a new pipeline transport; nothing existing is edited. Exposes a
tiny `push(sample)` / `drain()` surface. pylsl is optional (extras group
`platform`); when absent it falls back to an in-memory ring buffer with the same
surface, so `push`/`drain` always work (tests, and offline recording).
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Deque, List, Optional, Sequence

log = logging.getLogger("dreamlayer.lsl_transport")

try:
    import pylsl  # type: ignore
    _HAS_LSL = True
except ImportError:
    _HAS_LSL = False


class LslTransport:
    """Stream numeric samples out over LSL, or buffer them in memory.

    `name`/`stream_type`/`channels` describe the outlet. `push(sample)` sends one
    vector; `drain()` returns and clears the in-memory buffer (fallback path or
    local mirror)."""

    available = _HAS_LSL

    def __init__(self, name: str = "dreamlayer", stream_type: str = "Markers",
                 channels: int = 1, max_buffer: int = 4096):
        self.name = name
        self.stream_type = stream_type
        self.channels = channels
        self._buf: Deque[Sequence[float]] = deque(maxlen=max_buffer)
        self._outlet = None
        if _HAS_LSL:
            try:
                info = pylsl.StreamInfo(name, stream_type, channels,
                                        pylsl.IRREGULAR_RATE, "float32", name)
                self._outlet = pylsl.StreamOutlet(info)
            except Exception as exc:
                log.warning("[lsl] outlet init failed: %s; buffer fallback", exc)
                self._outlet = None

    def push(self, sample: Sequence[float]) -> None:
        vec = list(sample)
        self._buf.append(vec)
        if self._outlet is not None:
            try:
                self._outlet.push_sample(vec)
            except Exception as exc:
                log.warning("[lsl] push failed: %s", exc)

    def drain(self) -> List[Sequence[float]]:
        out = list(self._buf)
        self._buf.clear()
        return out
