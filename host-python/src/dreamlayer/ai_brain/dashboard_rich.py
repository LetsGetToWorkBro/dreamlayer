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
        #: How many times the RICH path has genuinely drawn a table. The wheel
        #: importing is not proof the dashboard works — a console that cannot
        #: reach a terminal, or a Table that raises, both fall through to the
        #: plain line while `available` still reads True. This counter is what
        #: promotes the capability, and only a completed draw increments it.
        self.rich_renders = 0

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
                self.rich_renders += 1
            except Exception as exc:
                log.warning("[dashboard_rich] render failed: %s; plain", exc)
                print(text)
        return text


#: How often the live panel redraws, in seconds. Slow on purpose: this is a
#: status panel someone glances at, not a monitor — and every tick reads the
#: index stats and the ear, so a tight loop would tax the machine the Brain is
#: supposed to be quietly living on.
REFRESH_S = 5.0


def brain_status(brain, **extra) -> dict:
    """The Brain's live state as a flat dict of display strings.

    Every read is wrapped: a dashboard must never be the thing that takes the
    server down, and a field the Brain cannot answer right now is better shown
    as "?" than as a traceback. Ordered for reading, not alphabetically.
    """
    def _try(fn, default="?"):
        try:
            return fn()
        except Exception:                          # noqa: BLE001 — display only
            return default

    # Read through `brain` rather than binding `cfg = getattr(brain, "config",
    # None)` first: that binds `Any | None`, and mypy then rejects every
    # `cfg.model` even though `_try` catches the AttributeError at runtime.
    # A Brain with no `config` is already handled — it reads "?" like any other
    # unanswerable field.
    status = {
        "model": _try(lambda: brain.config.model or "(none)"),
        "folders": _try(lambda: str(len(brain.config.folders))),
        "files": _try(lambda: str(brain.index.stats()["files"])),
        "token": _try(lambda: "set" if brain.config.token else "(none)"),
        # The veil belongs on a status panel more than anything else here: it is
        # the one piece of state that changes what the Brain is ALLOWED to do,
        # and a wearer glancing at the terminal should be able to see it.
        "veil": _try(lambda: "UP" if brain.incognito_now() else "down"),
        "cloud calls": _try(lambda: str(brain.config.cloud_calls)),
    }
    ear = _try(lambda: brain.ear_status(), None)
    if isinstance(ear, dict):
        status["ear"] = ("listening" if ear.get("listening") or ear.get("remote_listening")
                         else "off")
        # A COUNT, never the transcript. The panel says how much was heard and
        # nothing about what — same rule the ear's own status endpoint follows.
        status["heard"] = str(ear.get("heard_count", 0))
    status.update({k: str(v) for k, v in extra.items()})
    return status


def start_dashboard(brain, interval: float = REFRESH_S, **extra):
    """Redraw the live panel every `interval` seconds on a daemon thread.

    Returns the `Dashboard` so a caller can read `rich_renders` — which is what
    tells the capability meter the rich path is genuinely drawing rather than
    merely importable. Returns None only if the thread cannot start at all.

    Daemon, like every other background loop in this product (docs/CONCURRENCY.md):
    the panel must never hold the process open at Ctrl-C.

    The returned `Dashboard` carries `stop()`. The launcher never calls it — it
    runs until the process ends — but a panel that CANNOT be stopped is a panel
    that keeps writing to stdout after whoever started it has moved on, and one
    left running under pytest interleaves rich tables into other tests' captured
    output. `stop()` also makes the sleep interruptible, so teardown is immediate
    rather than up to `interval` seconds late.
    """
    import threading

    dash = Dashboard()
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                dash.render(brain_status(brain, **extra))
            except Exception as exc:               # noqa: BLE001 — never fatal
                log.warning("[dashboard_rich] tick failed: %s", type(exc).__name__)
            stop.wait(interval)                    # interruptible sleep

    try:
        threading.Thread(target=loop, daemon=True,
                         name="dreamlayer-dashboard").start()
    except Exception as exc:                       # noqa: BLE001
        log.error("[dashboard_rich] could not start: %s", exc)
        return None
    dash.stop = stop.set                           # type: ignore[attr-defined]
    return dash
