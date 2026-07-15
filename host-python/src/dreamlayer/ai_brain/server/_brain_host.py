"""ai_brain/server/_brain_host.py — the typed host surface the brain_* mixins share.

The Brain server was decomposed into cohesive ``brain_*`` mixins (RCOps,
CalendarOps, SocialOps, ReminderOps, WaypathOps) — the same ``ops_*`` pattern
the orchestrator uses. Every mixin reads shared state and calls sibling/host
methods that live on the composed ``Brain``; from a standalone mixin those
look undeclared, so mypy flags each ``self.config`` / ``self._store_lock`` /
``self.saga_record()`` as ``attr-defined``.

``BrainHost`` names that contract once. Each mixin inherits it
(``class RCOps(BrainHost): ...``) so mypy sees the shared shape. At runtime
``BrainHost`` is *empty*: the whole body is under ``if TYPE_CHECKING:`` and
``from __future__ import annotations`` keeps every annotation a string, so
nothing is imported, assigned, or defined when the module runs. Inheriting it
changes no behaviour — the real values are built by ``Brain.__init__``; this
file only declares their types.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    import threading
    from pathlib import Path

    from ...orchestrator.health import HealthLedger
    from ...orchestrator.waypath import WaypathLens
    from ...reality_compiler.v2.compiler import RealityCompilerV2
    from ..schema import Answer
    from .store import ActivityLog, BrainConfig


class BrainHost:
    """Shared-state + shared-behaviour surface for the ``brain_*`` mixins.

    Inheriting this is a *typing-only* act — the body below runs only under a
    type checker (see the module docstring for why that is zero-cost).
    """

    if TYPE_CHECKING:
        # -- Shared state (built by Brain.__init__) --
        cfg_dir: Path
        config: BrainConfig
        activity: ActivityLog
        health: HealthLedger
        waypath: WaypathLens
        rc: RealityCompilerV2
        _store_lock: threading.RLock
        _rc_pending: dict
        _rc_active: str | None
        _cal_stop: threading.Event | None
        _capability_handlers: dict
        # macOS reader seams (injectable for tests) — untyped third-party
        # payloads, so their return is Any.
        _calendar_reader: Callable[..., Any]
        _calendar_lister: Callable[..., Any]
        _contacts_reader: Callable[..., Any]
        _reminders_reader: Callable[..., Any]
        _reminder_lister: Callable[..., Any]

        # -- Shared behaviour: methods on the composed Brain or a sibling mixin,
        #    invoked cross-mixin. Signatures mirror the real definitions. --
        def _load_json(self, name: str, default: Any) -> Any: ...
        def _save_json(self, name: str, obj: Any) -> None: ...
        def saga_record(self, event: str, count: int | None = None) -> list: ...
        def ask(self, query: str, no_cloud: bool = False) -> Optional[Answer]: ...
        def sync_contacts(self) -> dict: ...
        def sync_reminders(self) -> dict: ...
