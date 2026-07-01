"""orchestrator/state.py — AppState enum for DreamLayer mode machine."""
from enum import Enum, auto


class AppState(Enum):
    IDLE            = auto()
    DREAM_MODE      = auto()
    LUCID_RECALL    = auto()
    REALITY_COMPILE = auto()
    TRUTH_LENS      = auto()
    SOCIAL_LENS     = auto()
