"""orchestrator/intents.py — Intent enum for user gesture/voice actions."""
from enum import Enum, auto


class Intent(Enum):
    DOUBLE_TAP       = auto()   # enter Dream Mode / trigger active lens
    SINGLE_TAP       = auto()   # dismiss card
    LONG_PRESS       = auto()   # enter Lucid Recall query
    SWIPE_FORWARD    = auto()   # next card
    SWIPE_BACK       = auto()   # previous card
    VOICE_QUERY      = auto()   # ASR utterance received
    WAKE_WORD        = auto()   # wake word detected
    PLACE_CHANGE     = auto()   # GPS/WiFi place signature changed
