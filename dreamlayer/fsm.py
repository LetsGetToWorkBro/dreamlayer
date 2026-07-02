"""
dreamlayer/fsm.py
DreamLayer Core FSM — finite state machine for memory capture and recall.

States
------
IDLE        Device connected, no active operation.
LISTENING  Button single-click; audio capture active.
LOADING    Processing / waiting for AI response.
CARD        A memory card is displayed.
PRIVACY_VEIL  Privacy Veil; no capture or display.
DISCONNECT Device not connected.

Transitions are driven by Events (button presses, BLE messages, timeouts).
The FSM is pure Python with no I/O so it is fully testable without hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

class State(Enum):
    DISCONNECT  = auto()
    IDLE        = auto()
    LISTENING   = auto()
    LOADING     = auto()
    CARD        = auto()
    PRIVACY_VEIL = auto()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class Event(Enum):
    # Hardware inputs
    BUTTON_SINGLE  = auto()
    BUTTON_DOUBLE  = auto()
    BUTTON_LONG    = auto()
    IMU_TAP        = auto()
    # BLE lifecycle
    BLE_CONNECT    = auto()
    BLE_DISCONNECT = auto()
    # AI / data events
    CARD_RECEIVED  = auto()    # BLE pushed a memory card
    LOADING_START  = auto()    # host started processing
    RESULT_READY   = auto()    # AI result ready → show card
    TIMEOUT        = auto()    # loading timeout
    # Privacy
    PRIVACY_TOGGLE = auto()


# ---------------------------------------------------------------------------
# Memory card payload
# ---------------------------------------------------------------------------

@dataclass
class MemoryCard:
    card_type: str
    payload:   dict[str, Any]
    source:    str = "ble"      # "ble" | "ai" | "proactive"
    confidence: float = 1.0

    def is_high_confidence(self) -> bool:
        return self.confidence >= 0.75


# ---------------------------------------------------------------------------
# FSM context — mutable state carried between transitions
# ---------------------------------------------------------------------------

@dataclass
class FSMContext:
    state:           State               = State.DISCONNECT
    current_card:    Optional[MemoryCard] = None
    privacy_active:  bool                = False
    listen_count:    int                 = 0    # total LISTENING entries
    card_count:      int                 = 0    # total cards displayed
    last_event:      Optional[Event]     = None
    history:         list[State]         = field(default_factory=list)

    def push_state(self, new_state: State) -> None:
        self.history.append(self.state)
        self.state = new_state

    def previous_state(self) -> Optional[State]:
        return self.history[-1] if self.history else None


# ---------------------------------------------------------------------------
# Transition table
# (current_state, event) → (next_state, side_effect_name)
# side_effect_name is looked up in DreamLayerFSM._effects dict
# ---------------------------------------------------------------------------

_TRANSITIONS: dict[tuple[State, Event], tuple[State, str]] = {
    # --- Connection ---
    (State.DISCONNECT,  Event.BLE_CONNECT):     (State.IDLE,       "on_connect"),
    (State.IDLE,        Event.BLE_DISCONNECT):  (State.DISCONNECT, "on_disconnect"),
    (State.LISTENING,   Event.BLE_DISCONNECT):  (State.DISCONNECT, "on_disconnect"),
    (State.LOADING,     Event.BLE_DISCONNECT):  (State.DISCONNECT, "on_disconnect"),
    (State.CARD,        Event.BLE_DISCONNECT):  (State.DISCONNECT, "on_disconnect"),
    (State.PRIVACY_VEIL,     Event.BLE_DISCONNECT):  (State.DISCONNECT, "on_disconnect"),

    # --- Listening ---
    (State.IDLE,        Event.BUTTON_SINGLE):   (State.LISTENING,  "on_listen_start"),
    (State.CARD,        Event.BUTTON_SINGLE):   (State.LISTENING,  "on_listen_start"),
    (State.LISTENING,   Event.BUTTON_SINGLE):   (State.IDLE,       "on_listen_cancel"),
    (State.LISTENING,   Event.LOADING_START):   (State.LOADING,    "on_loading"),

    # --- Loading ---
    (State.LOADING,     Event.RESULT_READY):    (State.CARD,       "on_card_show"),
    (State.LOADING,     Event.TIMEOUT):         (State.IDLE,       "on_timeout"),
    (State.LOADING,     Event.BUTTON_DOUBLE):   (State.IDLE,       "on_dismiss"),

    # --- Card display ---
    (State.IDLE,        Event.CARD_RECEIVED):   (State.CARD,       "on_card_show"),
    (State.CARD,        Event.CARD_RECEIVED):   (State.CARD,       "on_card_replace"),
    (State.CARD,        Event.BUTTON_DOUBLE):   (State.IDLE,       "on_dismiss"),
    (State.CARD,        Event.IMU_TAP):         (State.IDLE,       "on_dismiss"),
    (State.IDLE,        Event.BUTTON_DOUBLE):   (State.IDLE,       "noop"),

    # --- Privacy ---
    (State.IDLE,        Event.BUTTON_LONG):     (State.PRIVACY_VEIL,    "on_privacy_enter"),
    (State.CARD,        Event.BUTTON_LONG):     (State.PRIVACY_VEIL,    "on_privacy_enter"),
    (State.LISTENING,   Event.BUTTON_LONG):     (State.PRIVACY_VEIL,    "on_privacy_enter"),
    (State.PRIVACY_VEIL,     Event.BUTTON_LONG):     (State.IDLE,       "on_privacy_exit"),
    (State.PRIVACY_VEIL,     Event.BUTTON_SINGLE):   (State.PRIVACY_VEIL,    "noop"),
    (State.PRIVACY_VEIL,     Event.BUTTON_DOUBLE):   (State.PRIVACY_VEIL,    "noop"),
    (State.PRIVACY_VEIL,     Event.CARD_RECEIVED):   (State.PRIVACY_VEIL,    "noop"),  # suppress during privacy
    (State.PRIVACY_VEIL,     Event.PRIVACY_TOGGLE):  (State.IDLE,       "on_privacy_exit"),

    # --- IMU tap (dismiss from loading too) ---
    (State.LOADING,     Event.IMU_TAP):         (State.IDLE,       "on_dismiss"),
}


# ---------------------------------------------------------------------------
# FSM
# ---------------------------------------------------------------------------

class DreamLayerFSM:
    """
    Pure FSM — no I/O, no threads.
    Inject events with .send(event, payload=None).
    Subscribe to state changes via .on_transition callback.
    """

    def __init__(
        self,
        on_transition: Optional[Callable[[State, Event, State], None]] = None,
    ) -> None:
        self.ctx            = FSMContext()
        self._on_transition = on_transition
        self._effects: dict[str, Callable] = {
            "on_connect":      self._effect_connect,
            "on_disconnect":   self._effect_disconnect,
            "on_listen_start": self._effect_listen_start,
            "on_listen_cancel":self._effect_listen_cancel,
            "on_loading":      self._effect_loading,
            "on_card_show":    self._effect_card_show,
            "on_card_replace": self._effect_card_replace,
            "on_dismiss":      self._effect_dismiss,
            "on_timeout":      self._effect_timeout,
            "on_privacy_enter":self._effect_privacy_enter,
            "on_privacy_exit": self._effect_privacy_exit,
            "noop":            lambda payload=None: None,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> State:
        return self.ctx.state

    def send(self, event: Event, payload: Any = None) -> State:
        """
        Send an event. Returns the new state.
        Ignores events with no registered transition (graceful degradation).
        """
        key = (self.ctx.state, event)
        if key not in _TRANSITIONS:
            return self.ctx.state

        next_state, effect_name = _TRANSITIONS[key]
        prev_state = self.ctx.state
        self.ctx.last_event = event
        self.ctx.push_state(next_state)

        # Run side effect
        effect = self._effects.get(effect_name)
        if effect:
            effect(payload=payload)

        # Notify subscriber
        if self._on_transition:
            self._on_transition(prev_state, event, next_state)

        return next_state

    def reset(self) -> None:
        """Reset to DISCONNECT state, clearing all context."""
        self.ctx = FSMContext()

    # ------------------------------------------------------------------
    # Side effects
    # ------------------------------------------------------------------

    def _effect_connect(self, payload=None) -> None:
        self.ctx.privacy_active = False

    def _effect_disconnect(self, payload=None) -> None:
        self.ctx.current_card   = None
        self.ctx.privacy_active = False

    def _effect_listen_start(self, payload=None) -> None:
        self.ctx.listen_count += 1
        self.ctx.current_card  = None

    def _effect_listen_cancel(self, payload=None) -> None:
        pass

    def _effect_loading(self, payload=None) -> None:
        pass

    def _effect_card_show(self, payload: Any = None) -> None:
        if isinstance(payload, MemoryCard):
            self.ctx.current_card = payload
            self.ctx.card_count  += 1

    def _effect_card_replace(self, payload: Any = None) -> None:
        if isinstance(payload, MemoryCard):
            self.ctx.current_card = payload
            self.ctx.card_count  += 1

    def _effect_dismiss(self, payload=None) -> None:
        self.ctx.current_card = None

    def _effect_timeout(self, payload=None) -> None:
        self.ctx.current_card = None

    def _effect_privacy_enter(self, payload=None) -> None:
        self.ctx.privacy_active = True
        self.ctx.current_card   = None

    def _effect_privacy_exit(self, payload=None) -> None:
        self.ctx.privacy_active = False
