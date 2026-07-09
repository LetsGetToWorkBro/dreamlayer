"""Rich terminal dashboard — a cinematic live status panel for the Brain server
(pairing, indexing, model load, lens states).

ADD-alongside: new module. Lazy-imports rich (extras group `infra`); when
absent, `render()` prints a plain-text status line so it degrades to ordinary
logging with no dep.
"""
from __future__ import annotations
import logging

log = logging.getLogger("dreamlayer.dashboard_rich")

try:
    from rich.console import Console  # type: ignore
    from rich.table import Table  # type: ignore
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False


class Dashboard:
    available = _HAS_RICH

    def __init__(self):
        self._console = Console() if _HAS_RICH else None

    def render(self, status: dict) -> str:
        """Render a status dict. Returns the plain-text form (also printed via
        rich when available) so callers/tests get a stable string either way."""
        lines = [f"{k}: {v}" for k, v in status.items()]
        text = "  ·  ".join(lines)
        if self._console is not None:
            try:
                table = Table(title="DreamLayer Brain", show_header=False)
                for k, v in status.items():
                    table.add_row(str(k), str(v))
                self._console.print(table)
            except Exception as exc:
                log.warning("[dashboard_rich] render failed: %s; plain", exc)
                print(text)
        return text
