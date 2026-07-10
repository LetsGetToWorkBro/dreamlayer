"""dreamlayer.simulator — the Halo, without the Halo.

Two halves:

- `scenarios.py` — headless, fixture-driven demo scenarios (the original
  module: seed an Orchestrator and ask it things).
- `core.py` + `server.py` — the live simulator: a browser page that runs the
  REAL stack — the Orchestrator, the voice grammar, Social Lens, Waypath,
  native timers, the Reality Compiler's Figment stage — and draws what the
  glasses would draw, with the same card renderer that produces the golden
  images and the same Figment semantics the device Lua runs (pinned by the
  parity suite in test_rc2_lua_stage.py).

    python -m dreamlayer.simulator          # http://127.0.0.1:8765

Talk to Juno in the input box ("set a timer for 2 minutes", "this is my
colleague Sarah, she runs marketing", "where's my bike?"), pick a face to
look at, tap the temple, drop the Privacy Veil — and watch the round glass
respond with real pixels. Nothing here is a mock of DreamLayer; only the
hardware is simulated.
"""
from .core import HaloSimulator

__all__ = ["HaloSimulator"]
