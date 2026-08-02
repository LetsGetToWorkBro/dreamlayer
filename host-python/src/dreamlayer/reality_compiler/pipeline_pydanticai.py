"""Typed pipeline runner — runs the RC v2 stages
rehearse → choreograph → verify → sign → deploy in order, threading each
stage's output into the next and stopping at the first failure.
(The v1 codegen pipeline this originally mirrored was removed; the runner
is stage-agnostic — callers supply the stages.)

Nothing optional is imported here, and that is the point. This module used to
open with a probe for the agent framework in the `structured` extras group and
declare the `typed_pipeline` capability off it, describing itself as a typed
node graph with the sequential runner as a fallback. There was no node graph:
the import sat under `# noqa: F401` and was never referenced again, so
installing the wheel (and the ~60 packages behind it) moved the capability
meter from "missing" to "dormant" while `run()` executed byte-identical code.
The claim was dropped rather than implemented (#577) — the sequential runner is
the only implementation, it records what ran (`trace`) and where it failed
(`failed_at`) on every call, and it needs nothing installed to do it. The
module name is left alone so existing imports keep working.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple

log = logging.getLogger("dreamlayer.pipeline_pydanticai")


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
