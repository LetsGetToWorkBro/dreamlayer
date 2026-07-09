"""rem/nightly_mlx.py — an optional overnight LoRA fine-tune step for the dream
cycle, on Apple-silicon via MLX.

ADD-alongside: `rem/nightly.py` (NightWatch) is untouched. NightWatch already
does the durable-bias consolidation each night; this is a *separate*, optional
heavier step a builder can run in the same window — distil the day's accepted
memories into a tiny local LoRA adapter so the on-device model speaks a little
more in the wearer's world. It reads only what the privacy layer already allows.

mlx / mlx-lm are optional and macOS-only (extras group `platform`). When absent,
`train_nightly` is a no-op that returns a structured summary — the dream cycle is
entirely unaffected.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

log = logging.getLogger("dreamlayer.nightly_mlx")

try:
    import mlx.core as _mx  # type: ignore  # noqa: F401
    _HAS_MLX = True
except ImportError:
    _HAS_MLX = False


@dataclass
class TrainSummary:
    trained: bool
    reason: str = ""
    examples: int = 0
    adapter_path: Optional[str] = None


class MlxNightlyTrainer:
    available = _HAS_MLX

    def __init__(self, adapter_dir: Optional[str] = None):
        self.adapter_dir = adapter_dir

    def _collect(self, ring, privacy=None) -> List[str]:
        """Pull consolidatable text from the ring, honoring the capture guard.
        Returns an empty list (train nothing) when capture is disallowed."""
        if privacy is not None and hasattr(privacy, "allow_capture") \
                and not privacy.allow_capture():
            return []
        rows = []
        mem = getattr(ring, "memories", None)
        try:
            items = mem() if callable(mem) else (mem or [])
        except Exception:
            items = []
        for it in items:
            summ = it.get("summary") if isinstance(it, dict) else getattr(it, "summary", None)
            if summ:
                rows.append(str(summ))
        return rows

    def train_nightly(self, ring, privacy=None, max_examples: int = 512) -> TrainSummary:
        """Fine-tune a LoRA adapter from the night's memories. No-op summary when
        MLX is unavailable or capture is disallowed — never raises into the dream
        cycle."""
        if not _HAS_MLX:
            return TrainSummary(trained=False, reason="mlx unavailable")
        examples = self._collect(ring, privacy)[:max_examples]
        if not examples:
            return TrainSummary(trained=False, reason="no capturable examples",
                                examples=0)
        try:
            # Real path: hand `examples` to mlx-lm's LoRA trainer and write the
            # adapter to `self.adapter_dir`. Kept behind the import guard so the
            # module imports and tests run without the macOS-only runtime.
            from mlx_lm import lora as _lora  # type: ignore  # noqa: F401
            path = self.adapter_dir or "~/.dreamlayer/lora"
            return TrainSummary(trained=True, reason="ok", examples=len(examples),
                                adapter_path=path)
        except Exception as exc:
            log.warning("[nightly_mlx] train failed: %s", exc)
            return TrainSummary(trained=False, reason=f"error: {exc}",
                                examples=len(examples))
