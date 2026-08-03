"""One gesture, everything stops — `structured_concurrency`, Brain-side.

WHAT WAS MISSING, AND WHY IT WAS SUBTLER THAN THE REST
-----------------------------------------------------
`orchestrator/concurrency_anyio.run_until_veil` runs a set of coroutines under
one scope and cancels them all the moment the Veil drops. It is complete and it
honours the floor: with anyio absent it falls back to plain asyncio with the
same cancel-all semantics.

It had no caller, but unlike the other re-hostings the fix was NOT "call it from
the Brain". The shipped Brain is a threaded `ThreadingHTTPServer` — schedulers,
watchers and the ear are all daemon threads — so for most of it there is no
event loop to put a scope in, and standing one up just to have somewhere to call
this would be the resurrection mistake in a different costume.

There is exactly one place in the Brain that already runs an event loop, and it
is also the one place where the Veil-stop guarantee is genuinely incomplete:

    live_dream.scene()  →  asyncio.run(self._describer.tick(ctx))

That beat checks `veiled()` ONCE, at the top, and then runs up to two VLM calls
with the wearer's camera frame in them. Drop the Veil mid-beat — which is the
exact gesture the guarantee is named for — and the in-flight call keeps going.
Nothing is persisted, but a request carrying that frame is already on its way to
a model, and "everything stops" is not true of it. `live_dream`'s own comment
names the neighbouring half of this: a hung backend leaves an orphaned worker
that `asyncio.run` joins at shutdown.

So this is not glue for the sake of a green row. It is the one scope in the
Brain that needed a cancel-all, and the seam that was written for it.

WHAT CANCELLING DOES AND DOES NOT BUY
-------------------------------------
It stops the Brain WAITING on the call and lets the beat return veiled. It
cannot un-send bytes already on a socket — no cancellation can — and claiming
otherwise would be the overclaim this whole line of work exists to remove. What
the wearer gets is: the moment they veil, the dream stops feeding on frames, no
result from an in-flight beat is ever drawn, and the beat that was running
releases its worker instead of holding it for the backend's socket timeout.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("dreamlayer.veil_scope")

#: How often the scope re-asks the posture. The Veil is a switch a human flips,
#: so a quarter second is imperceptible to them and ~20 checks across a beat
#: that would otherwise run to a multi-second backend timeout.
POLL_S = 0.25

#: Scopes that genuinely ran under a cancel-all. Module-level rather than
#: per-Brain because the scope is a property of the process's event loop, and
#: `live_dream` builds its describer per session — a counter on either would
#: reset under the thing it is meant to measure.
_SCOPES = 0
_CANCELLED = 0


def scopes_run() -> int:
    return _SCOPES


def veil_cancels() -> int:
    return _CANCELLED


def run_guarded(factory, is_veiled, poll_s: float = POLL_S):
    """Run one coroutine under a Veil-cancelled scope. Returns its value, or
    None if the Veil dropped first.

    `factory` is a zero-argument callable returning a coroutine — the same
    contract `run_until_veil` takes — and `is_veiled` is a plain synchronous
    predicate, because the posture lives on a threaded Brain and not in the
    loop.

    Fails CLOSED in the one direction that matters: a posture check that raises
    is treated as veiled and cancels the scope. An unreadable trust signal must
    never resolve to "keep sending frames to the model".
    """
    global _SCOPES, _CANCELLED

    async def _scope():
        global _SCOPES, _CANCELLED
        from ...orchestrator.concurrency_anyio import run_until_veil
        out: dict = {}
        stop = asyncio.Event()

        async def _work():
            try:
                out["value"] = await factory()
            finally:
                # Setting the stop event on COMPLETION as well as on the Veil is
                # what makes this a scope rather than a leak: `run_until_veil`
                # returns when the event fires, so without this the watcher
                # would sit there until the wearer happened to veil, and a beat
                # that finished in 200 ms would hold its worker forever.
                stop.set()

        async def _watch():
            while not stop.is_set():
                try:
                    veiled = bool(is_veiled())
                except Exception:                # noqa: BLE001 — unreadable → veiled
                    veiled = True
                if veiled:
                    out["veiled"] = True
                    stop.set()
                    return
                await asyncio.sleep(poll_s)

        try:
            await run_until_veil([_work, _watch], stop)
        except Exception as exc:                 # noqa: BLE001
            # A beat that failed has no value to draw, and the two paths inside
            # `run_until_veil` report failure differently — anyio propagates an
            # ExceptionGroup, plain asyncio swallows it into
            # `gather(return_exceptions=True)`. Normalising here is what makes
            # the guarantee identical whether or not the optional wheel is
            # installed, which is the floor this repo holds every optional
            # dependency to.
            log.info("[veil] beat failed inside the scope: %s",
                     type(exc).__name__)
            _SCOPES += 1
            return None
        _SCOPES += 1
        if out.get("veiled"):
            _CANCELLED += 1
            return None
        return out.get("value")

    return asyncio.run(_scope())


def driving() -> bool:
    """Whether the structural cancel-all is genuinely in use.

    Both halves are needed and neither alone is honest. `available` is the
    anyio wheel — the capability IS anyio, and the asyncio path is the baseline
    it must never do worse than — and `scopes_run()` is a scope having actually
    executed, because a wheel on disk with no beat run through it is the
    "importable, never called" state this whole audit is about.

    It cannot distinguish the anyio path from `run_until_veil`'s own internal
    fallback, which logs a warning and drops to asyncio if the anyio branch
    raises. That is a narrow, loud failure and it is named here rather than
    papered over.
    """
    try:
        from ...orchestrator.concurrency_anyio import available
    except Exception:                                # noqa: BLE001
        return False
    return bool(available) and _SCOPES > 0
