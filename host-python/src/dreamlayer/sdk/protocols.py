"""Typed contracts for the SDK (PEP 544 Protocols + a TypedDict manifest).

These describe the *shape* a plugin author codes against, so editors and
type-checkers (mypy/pyright) give autocomplete and catch mistakes — while the
host stays free to change the concrete classes behind them. They're structural:
the real ``PluginContext`` satisfies ``PluginContextProtocol`` without importing
it. Import for annotations only::

    from dreamlayer.sdk import PluginContextProtocol

    def register(ctx: PluginContextProtocol) -> None:
        ctx.add_card_renderer("MyCard", draw)
"""
from __future__ import annotations

from typing import Any, Callable, Protocol, TypedDict, runtime_checkable


@runtime_checkable
class SettingsProtocol(Protocol):
    """A plugin's persisted settings (``ctx.settings``), scoped to the plugin."""

    def get(self, key: str, default: Any = None) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...
    def all(self) -> dict: ...


@runtime_checkable
class PluginContextProtocol(Protocol):
    """The narrow surface a plugin is handed in ``register(ctx)`` and the
    lifecycle hooks. Every ``add_*`` wires into a real host registry; each
    requires the matching capability be declared in the manifest.
    """

    config: dict

    # capability queries
    def has(self, capability: str) -> bool: ...
    @property
    def capabilities(self) -> frozenset: ...

    # read-only host state
    @property
    def ring(self) -> Any: ...
    @property
    def mesh(self) -> Any: ...
    def veiled(self) -> bool: ...

    # extension points (declare the matching capability)
    def add_object_provider(self, provider: Any) -> None: ...
    def add_glance_candidate(self, candidate: Any) -> None: ...
    def add_vision_brain(self, brain: Any) -> None: ...
    def add_knowledge_brain(self, brain: Any) -> None: ...
    def add_perceptor(self, perceptor: Any, prefer: bool = True) -> None: ...
    def add_card_renderer(self, card_type: str, fn: Callable) -> None: ...
    def add_shop_provider(self, fn: Callable) -> None: ...

    # v2: events + settings
    def subscribe(self, kind: str, fn: Callable) -> bool: ...
    @property
    def settings(self) -> SettingsProtocol: ...


class ManifestDict(TypedDict, total=False):
    """The shape of a plugin's ``plugin.json`` (and a registry manifest). Only
    ``name``/``version``/``entry`` are required in practice; the rest have
    sensible defaults. Use it to type-check the dicts you hand to
    ``PluginManifest.from_dict``."""

    # identity + loading
    name: str
    version: str
    entry: str                    # "module:factory"
    api: str                      # "1" | "2"
    min_sdk: str                  # lowest dreamlayer.sdk version required
    requires: list[str]           # capability names

    # trust + integrity (stamped by tooling / the store)
    checksum: str
    signature: str
    pubkey: str

    # publisher / marketplace
    author: str
    official: bool
    pricing: dict                 # {"model": "free" | "one_time" | ...}

    # store detail (travels with the plugin)
    description: str
    homepage: str
    forwho: str
    long: list[str]
    screenshot: str
