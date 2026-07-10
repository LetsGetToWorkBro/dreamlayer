"""object_lens/bench.py — the 350ms Club (INNOVATION_SESSION 1.4).

A public benchmark for "what am I looking at?" held to the Tier-0 glance budget.
A perceptor runs against a fixed labeled image set; every classification is put
through the *real* deadline runner (`orchestrator/budgets.run_with_deadline`)
at the 350ms glance-name budget — anything that answers late is silently
dropped, exactly as it would be on-glass, so a slow-but-accurate model can't
game the score. The result is accuracy × latency, reported together.

The bundled set is deterministic synthetic pixels (a leafy plant, a page of
text, a dark screen, a warm mug — the coarse kinds the offline
HeuristicVisionClassifier separates), generated with a seeded RNG so the number
is reproducible run to run. Bring your own `classifier` (an
`add_perceptor`-style callable `frame -> (label, conf) | None`) to bench a
competitor to the platform's own vision tier — the whole point of 1.4.

Needs numpy (the `perception` extra); `available()` says whether it can run.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from ..orchestrator.budgets import GLANCE_NAME_MS, run_with_deadline

# label → a small painter that draws that visual *kind* into HxWx3 uint8 pixels.
# Mirrors the feature prototypes HeuristicVisionClassifier calibrates against.
_SIZE = 64


def available() -> bool:
    try:
        import numpy  # noqa: F401
        return True
    except Exception:
        return False


def _painters():
    import numpy as np

    def plant(rng):
        img = np.zeros((_SIZE, _SIZE, 3), np.float32)
        img[..., 0], img[..., 1], img[..., 2] = 40, 150, 50      # green-dominant
        img += rng.normal(0, 26, img.shape)                       # leafy edges
        return np.clip(img, 0, 255).astype(np.uint8)

    def book(rng):
        img = np.full((_SIZE, _SIZE, 3), 225, np.float32)         # bright paper
        img[..., 2] -= 18                                         # warm/cream
        for r in range(4, _SIZE, 4):
            img[r:r + 1, 6:_SIZE - 6, :] = 20                     # rows of text
        img += rng.normal(0, 5, img.shape)
        return np.clip(img, 0, 255).astype(np.uint8)

    def screen(rng):
        img = np.full((_SIZE, _SIZE, 3), 45, np.float32)          # dark, flat
        img[10:12, :, :] = 90
        img[30:32, :, :] = 80                                     # a couple of bars
        img += rng.normal(0, 6, img.shape)
        return np.clip(img, 0, 255).astype(np.uint8)

    def mug(rng):
        img = np.zeros((_SIZE, _SIZE, 3), np.float32)
        img[..., 0], img[..., 1], img[..., 2] = 205, 110, 55      # warm, saturated
        img += rng.normal(0, 8, img.shape)
        return np.clip(img, 0, 255).astype(np.uint8)

    return {"houseplant": plant, "book": book, "screen": screen, "mug": mug}


def sample_set(per_label: int = 6, seed: int = 7) -> list[tuple]:
    """A deterministic labeled image set: `per_label` variants of each kind."""
    import numpy as np
    rng = np.random.default_rng(seed)
    out: list[tuple] = []
    for label, paint in _painters().items():
        for _ in range(per_label):
            out.append((paint(rng), label))
    return out


@dataclass
class BenchResult:
    n: int
    correct: int
    dropped: int          # answered later than the glance budget → dropped
    accuracy: float       # correct / n  (a dropped answer counts as wrong)
    mean_ms: float
    p95_ms: float
    score: float          # accuracy × a latency factor in [0,1]

    def as_dict(self) -> dict:
        return {"n": self.n, "correct": self.correct, "dropped": self.dropped,
                "accuracy": round(self.accuracy, 4), "mean_ms": round(self.mean_ms, 3),
                "p95_ms": round(self.p95_ms, 3), "score": round(self.score, 4)}


def run_perception_bench(classifier: Optional[Callable] = None,
                         deadline_ms: float = GLANCE_NAME_MS,
                         samples: Optional[list] = None) -> BenchResult:
    """Run `classifier` (default: the vision ladder) over the labeled set under
    the glance deadline. A late answer is dropped (counts as wrong), so the
    score rewards being *right, inside the budget*."""
    import time
    if classifier is None:
        from .classify_backends import default_classifier
        classifier = default_classifier()
    samples = samples if samples is not None else sample_set()

    correct = dropped = 0
    latencies: list[float] = []
    for frame, label in samples:
        t0 = time.perf_counter()
        # the real on-glass gate: over budget → None, silently dropped
        pred = run_with_deadline(lambda: classifier(frame), deadline_ms)
        dt = (time.perf_counter() - t0) * 1000.0
        latencies.append(dt)
        if pred is None and dt > deadline_ms:
            dropped += 1
            continue
        if pred is not None and pred[0] == label:
            correct += 1

    n = len(samples)
    latencies.sort()
    mean_ms = sum(latencies) / n if n else 0.0
    p95_ms = latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))] if n else 0.0
    accuracy = correct / n if n else 0.0
    latency_factor = max(0.0, 1.0 - mean_ms / deadline_ms)
    return BenchResult(n=n, correct=correct, dropped=dropped, accuracy=accuracy,
                       mean_ms=mean_ms, p95_ms=p95_ms,
                       score=round(accuracy * latency_factor, 4))
