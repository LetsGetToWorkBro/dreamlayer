"""orchestrator — Central coordinator and mode manager for DreamLayer.

The Orchestrator owns the top-level state machine:
  IDLE → DREAM_MODE → LUCID_RECALL → REALITY_COMPILER

It receives sensor events from pipelines, routes them to the active
module, and dispatches HUD cards via the bridge.
"""
from .orchestrator import Orchestrator
from .recall_context import RecallContext
from .state import AppState
from .intents import Intent

__all__ = ["Orchestrator", "RecallContext", "AppState", "Intent"]
