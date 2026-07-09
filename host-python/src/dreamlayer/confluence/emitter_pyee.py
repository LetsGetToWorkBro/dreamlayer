"""confluence/emitter_pyee.py — a pub/sub bus around mesh traffic so many
listeners (HUD, saga, weather, beacon) can react to one emitted/received packet
without the mesh knowing who they are.

ADD-alongside: `confluence/mesh.py` (MeshManager.emit/receive) is untouched.
This wraps a MeshManager: `publish_emit(kind, body)` calls the real
`emit`, and — only if a packet was actually produced (not veiled, group live) —
fans it out to subscribers. The privacy contract is preserved because we never
fabricate a packet; a veiled `emit()` returns None and nothing is published.

pyee is optional (extras group `platform`). When absent, a tiny synchronous
in-house emitter with the same on/emit surface is used, so the bus always works.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

log = logging.getLogger("dreamlayer.emitter_pyee")

try:
    from pyee.base import EventEmitter  # type: ignore
    _HAS_PYEE = True
except ImportError:
    try:
        from pyee import EventEmitter  # type: ignore  # older layout
        _HAS_PYEE = True
    except ImportError:
        _HAS_PYEE = False


class _MiniEmitter:
    """Synchronous fallback: the subset of pyee's EventEmitter we use."""

    def __init__(self):
        self._handlers: dict[str, list[Callable]] = {}

    def on(self, event: str, fn: Callable) -> Callable:
        self._handlers.setdefault(event, []).append(fn)
        return fn

    def remove_listener(self, event: str, fn: Callable) -> None:
        if event in self._handlers and fn in self._handlers[event]:
            self._handlers[event].remove(fn)

    def emit(self, event: str, *args, **kwargs) -> bool:
        handlers = list(self._handlers.get(event, ()))
        for fn in handlers:
            try:
                fn(*args, **kwargs)
            except Exception as exc:  # a bad listener must not break the bus
                log.warning("[emitter] listener for %s raised: %s", event, exc)
        return bool(handlers)


class MeshEventBus:
    """Fan out mesh packets to decoupled subscribers.

    Events: "emit" (this wearer sent) and "receive" (a member's state folded in).
    Subscribe with `on(event, fn)`. Drive with `publish_emit` / `publish_receive`,
    which call the real MeshManager and only publish when it produced something.
    """

    available = _HAS_PYEE

    def __init__(self, mesh, emitter=None):
        self._mesh = mesh
        self._ee = emitter or (EventEmitter() if _HAS_PYEE else _MiniEmitter())

    def on(self, event: str, fn: Callable) -> Callable:
        return self._ee.on(event, fn)

    def publish_emit(self, kind: str, body: dict):
        """Emit through the mesh (honors the Veil) and, if a packet resulted,
        publish it. Returns the packet or None."""
        pkt = self._mesh.emit(kind, body)
        if pkt is not None:
            self._ee.emit("emit", pkt)
        return pkt

    def publish_receive(self, wire: dict):
        """Feed inbound wire to the mesh and publish the updated member if
        accepted. Returns the member or None (forged/replayed/veiled dropped)."""
        member = self._mesh.receive(wire)
        if member is not None:
            self._ee.emit("receive", member)
        return member
