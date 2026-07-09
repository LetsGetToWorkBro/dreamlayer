"""Structured concurrency (anyio) for the Privacy-Veil "one gesture, everything
stops" guarantee — run a set of tasks under one scope, cancel all at once.

ADD-alongside: new module. Lazy-imports anyio (extras group `privacy`); when
absent it falls back to plain asyncio with the same cancel-all semantics, so the
Veil stop guarantee holds either way.
"""
from __future__ import annotations
import asyncio
import logging

log = logging.getLogger("dreamlayer.concurrency_anyio")

try:
    import anyio  # type: ignore
    _HAS_ANYIO = True
except ImportError:
    _HAS_ANYIO = False

available = _HAS_ANYIO


async def run_until_veil(task_factories, stop_event) -> None:
    """Run each `factory()` coroutine concurrently until `stop_event` is set,
    then cancel them all. `stop_event` is an asyncio.Event (the Veil switch).

    anyio path uses a task group + cancel scope; the fallback uses asyncio.gather
    with explicit cancellation. Both guarantee no task outlives the Veil drop.
    """
    if _HAS_ANYIO:
        try:
            async with anyio.create_task_group() as tg:
                for f in task_factories:
                    tg.start_soon(f)

                async def _watch():
                    await _wait_event(stop_event)
                    tg.cancel_scope.cancel()

                tg.start_soon(_watch)
            return
        except Exception as exc:
            log.warning("[concurrency_anyio] anyio path failed: %s; asyncio", exc)

    tasks = [asyncio.ensure_future(f()) for f in task_factories]
    watcher = asyncio.ensure_future(_wait_event(stop_event))
    try:
        await watcher
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _wait_event(ev) -> None:
    if hasattr(ev, "wait"):
        await ev.wait()
