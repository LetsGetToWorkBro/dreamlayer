"""Typed pipeline runner (pydantic-ai) — models the RC stages
intent_parser → compiler → validator → deployer as a typed node graph.

ADD-alongside: new module (compiler.py untouched). Lazy-imports pydantic-ai
(extras group `structured`); the always-available fallback is a simple typed
sequential runner that threads each stage's output into the next and stops on
the first failure — same control flow the compiler already has, just made
inspectable.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple

log = logging.getLogger("dreamlayer.pipeline_pydanticai")

try:
    import pydantic_ai  # type: ignore  # noqa: F401
    _HAS_PYDANTIC_AI = True
except ImportError:
    _HAS_PYDANTIC_AI = False

available = _HAS_PYDANTIC_AI


@dataclass
class StageResult:
    ok: bool
    value: Any = None
    failed_at: Optional[str] = None
    error: Optional[str] = None
    trace: List[str] = field(default_factory=list)


class StagePipeline:
    """`stages` = ordered [(name, fn)] where fn(prev_value) -> next_value.

    A stage that raises stops the pipeline and is reported in `failed_at`.
    """
    def __init__(self, stages: List[Tuple[str, Callable[[Any], Any]]]):
        self.stages = stages

    def run(self, initial: Any = None) -> StageResult:
        value = initial
        trace: List[str] = []
        for name, fn in self.stages:
            try:
                value = fn(value)
                trace.append(name)
            except Exception as exc:
                log.warning("[pipeline] stage %s failed: %s", name, exc)
                return StageResult(ok=False, failed_at=name, error=str(exc), trace=trace)
        return StageResult(ok=True, value=value, trace=trace)
