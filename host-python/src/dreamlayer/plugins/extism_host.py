"""plugins/extism_host.py — plugins made INCAPABLE, not inspected (Extism).

Our plugin trust story scans for capabilities; Extism inverts it: an untrusted
plugin (written in any language, compiled to WASM) runs in a sandbox that simply
HAS no filesystem, no network, no clock beyond what the host grants — the same
philosophy as figment budgets, applied to the plugin side. This host runs a
guest with hard limits:

    * no WASI (no ambient authority at all)
    * no allowed_hosts (Extism denies HTTP by default — we grant none)
    * a memory ceiling and a wall-clock timeout

Lazy adapter (extras group `extism`); absent the wheel, run() returns None and
the existing subprocess/wasmtime plugin paths carry on unchanged. This also
widens the contributor funnel: DreamLayer plugins in Rust/Go/JS, one .wasm each.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("dreamlayer.extism")

_MAX_WASM = 32 * 1024 * 1024     # refuse a >32 MB "plugin" outright
_MAX_OUT = 1 * 1024 * 1024       # and never accept more than 1 MB back


def _has(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


class ExtismHost:
    """Run untrusted WASM plugin functions under hard limits."""

    dep = "extism"
    available = _has("extism")

    def __init__(self, timeout_ms: int = 2000, max_pages: int = 64):
        # 64 pages = 4 MB of guest memory — generous for a lens plugin
        self.timeout_ms = max(100, min(int(timeout_ms), 30_000))
        self.max_pages = max(16, min(int(max_pages), 1024))

    @property
    def ready(self) -> bool:
        return self.available

    def run(self, wasm: bytes, func: str = "run",
            input_bytes: bytes = b"") -> Optional[bytes]:
        """Call `func` in the guest with `input_bytes`; the guest's output bytes
        back, or None on ANY failure (missing wheel, oversized module, trap,
        timeout, oversized output). The guest gets no WASI and no hosts."""
        if not self.available:
            return None
        if not isinstance(wasm, (bytes, bytearray)) or not wasm \
                or len(wasm) > _MAX_WASM:
            return None
        func = (func or "").strip()
        if not func:
            return None
        try:
            import extism  # type: ignore
            manifest = {
                "wasm": [{"data": bytes(wasm)}],
                "memory": {"max_pages": self.max_pages},
                "timeout_ms": self.timeout_ms,
                "allowed_hosts": [],               # explicit: the guest gets NO network
            }
            # functions=[]: never link the global @host_fn registry — "zero
            # ambient authority" stays structural even if some future import
            # registers host functions process-wide.
            with extism.Plugin(manifest, wasi=False, functions=[]) as plugin:
                out = plugin.call(func, bytes(input_bytes or b""))
            out = bytes(out or b"")
            return out[:_MAX_OUT] if len(out) <= _MAX_OUT else None
        except Exception as exc:                   # noqa: BLE001 — a trap is a refusal, not a crash
            log.info("[extism] plugin call refused/failed: %s", exc)
            return None


def default_extism_host() -> Optional[ExtismHost]:
    h = ExtismHost()
    return h if h.ready else None
