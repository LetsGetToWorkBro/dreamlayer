"""
pytest tests for halo_bridge.py and dreamlayer/fsm.py.
All pure — no BLE hardware, no emulator required.
"""
import json
import sys
from pathlib import Path

import pytest

# Path setup
SCRIPTS = Path(__file__).resolve().parent.parent
REPO    = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO))

from halo_bridge import (
    _step_to_msg,
    step_delay,
    dry_run_scenario,
)
from halo_lab import ble_frame, validate_scenario
from dreamlayer.fsm import (
    DreamLayerFSM, State, Event, MemoryCard, FSMContext,
    _TRANSITIONS,
)


# ===========================================================================
# halo_bridge  — _step_to_msg
# ===========================================================================

class TestStepToMsg:
    def test_connect(self):
        assert _step_to_msg({"action": "connect"}) == {"t": "connect"}

    def test_disconnect(self):
        assert _step_to_msg({"action": "disconnect"}) == {"t": "disconnect"}

    def test_button_single(self):
        msg = _step_to_msg({"action": "button", "kind": "single"})
        assert msg == {"t": "button", "kind": "single"}

    def test_button_long(self):
        msg = _step_to_msg({"action": "button", "kind": "long"})
        assert msg == {"t": "button", "kind": "long"}

    def test_card(self):
        step = {
            "action": "card",
            "card_type": "ObjectRecallCard",
            "payload": {"object": "KEYS", "place": "KITCHEN",
                        "last_seen": "2h ago", "confidence": 0.91}
        }
        msg = _step_to_msg(step)
        assert msg["t"] == "card"
        assert msg["payload"]["type"] == "ObjectRecallCard"
        assert msg["payload"]["object"] == "KEYS"

    def test_command(self):
        msg = _step_to_msg({"action": "command", "kind": "ask"})
        assert msg == {"t": "command", "kind": "ask"}

    def test_imu_tap(self):
        assert _step_to_msg({"action": "imu_tap"}) == {"t": "imu_tap"}

    def test_card_payload_includes_type(self):
        step = {"action": "card", "card_type": "LoadingCard", "payload": {}}
        msg  = _step_to_msg(step)
        assert msg["payload"]["type"] == "LoadingCard"


# ===========================================================================
# halo_bridge — step_delay
# ===========================================================================

class TestStepDelay:
    def _steps(self, ats):
        return [{"action": "connect", "at": a} for a in ats]

    def test_first_step_zero(self):
        assert step_delay(self._steps([0, 1, 2]), 0, 800) == 0.0

    def test_uses_at_field(self):
        assert step_delay(self._steps([0.0, 2.5]), 1, 800) == pytest.approx(2.5)

    def test_fallback_to_settle(self):
        steps = [{"action": "connect"}, {"action": "connect"}]
        assert step_delay(steps, 1, 800) == pytest.approx(0.8)

    def test_at_gap_respected(self):
        steps = self._steps([0.0, 1.0, 4.5])
        assert step_delay(steps, 2, 800) == pytest.approx(3.5)

    def test_negative_at_gap_clamped(self):
        steps = self._steps([5.0, 3.0])   # reversed timestamps
        assert step_delay(steps, 1, 800) == 0.0


# ===========================================================================
# halo_bridge — dry_run_scenario
# ===========================================================================

class TestDryRun:
    def _scenario(self, n=3):
        steps = [{"action": "connect", "at": float(i)} for i in range(n)]
        return {"name": "test", "description": "", "steps": steps}

    def test_returns_all_steps(self):
        results = dry_run_scenario(self._scenario(4))
        assert len(results) == 4

    def test_step_keys(self):
        r = dry_run_scenario(self._scenario(1))[0]
        assert {"step", "label", "delay_s", "frame_bytes"} <= r.keys()

    def test_first_delay_zero(self):
        assert dry_run_scenario(self._scenario(2))[0]["delay_s"] == 0.0

    def test_frame_bytes_positive_for_connect(self):
        assert dry_run_scenario(self._scenario(1))[0]["frame_bytes"] > 0


# ===========================================================================
# FSM — basic state machine
# ===========================================================================

class TestFSMConnect:
    def test_starts_disconnected(self):
        fsm = DreamLayerFSM()
        assert fsm.state == State.DISCONNECT

    def test_connect_moves_to_idle(self):
        fsm = DreamLayerFSM()
        fsm.send(Event.BLE_CONNECT)
        assert fsm.state == State.IDLE

    def test_disconnect_from_idle(self):
        fsm = DreamLayerFSM()
        fsm.send(Event.BLE_CONNECT)
        fsm.send(Event.BLE_DISCONNECT)
        assert fsm.state == State.DISCONNECT

    def test_connect_clears_privacy(self):
        fsm = DreamLayerFSM()
        fsm.send(Event.BLE_CONNECT)
        fsm.send(Event.BUTTON_LONG)
        assert fsm.state == State.PRIVACY_VEIL
        fsm.send(Event.BLE_DISCONNECT)
        fsm.send(Event.BLE_CONNECT)
        assert not fsm.ctx.privacy_active


class TestFSMListening:
    def _connected(self):
        fsm = DreamLayerFSM()
        fsm.send(Event.BLE_CONNECT)
        return fsm

    def test_single_click_starts_listening(self):
        fsm = self._connected()
        fsm.send(Event.BUTTON_SINGLE)
        assert fsm.state == State.LISTENING

    def test_listen_increments_count(self):
        fsm = self._connected()
        fsm.send(Event.BUTTON_SINGLE)
        assert fsm.ctx.listen_count == 1
        fsm.send(Event.BUTTON_SINGLE)  # cancel
        fsm.send(Event.BUTTON_SINGLE)  # start again
        assert fsm.ctx.listen_count == 2

    def test_cancel_listening_returns_idle(self):
        fsm = self._connected()
        fsm.send(Event.BUTTON_SINGLE)
        fsm.send(Event.BUTTON_SINGLE)
        assert fsm.state == State.IDLE

    def test_loading_start_transitions(self):
        fsm = self._connected()
        fsm.send(Event.BUTTON_SINGLE)
        fsm.send(Event.LOADING_START)
        assert fsm.state == State.LOADING


class TestFSMCard:
    def _idle(self):
        fsm = DreamLayerFSM()
        fsm.send(Event.BLE_CONNECT)
        return fsm

    def test_card_received_shows_card(self):
        fsm   = self._idle()
        card  = MemoryCard(card_type="ObjectRecallCard", payload={"object": "KEYS"})
        fsm.send(Event.CARD_RECEIVED, payload=card)
        assert fsm.state == State.CARD
        assert fsm.ctx.current_card is card

    def test_card_count_increments(self):
        fsm  = self._idle()
        card = MemoryCard(card_type="SavedMemoryCard", payload={"primary": "test"})
        fsm.send(Event.CARD_RECEIVED, payload=card)
        fsm.send(Event.CARD_RECEIVED, payload=card)
        assert fsm.ctx.card_count == 2

    def test_double_click_dismisses(self):
        fsm = self._idle()
        fsm.send(Event.CARD_RECEIVED)
        fsm.send(Event.BUTTON_DOUBLE)
        assert fsm.state == State.IDLE
        assert fsm.ctx.current_card is None

    def test_imu_tap_dismisses(self):
        fsm = self._idle()
        fsm.send(Event.CARD_RECEIVED)
        fsm.send(Event.IMU_TAP)
        assert fsm.state == State.IDLE

    def test_result_ready_from_loading(self):
        fsm  = self._idle()
        card = MemoryCard(card_type="LoadingCard", payload={})
        fsm.send(Event.BUTTON_SINGLE)
        fsm.send(Event.LOADING_START)
        fsm.send(Event.RESULT_READY, payload=card)
        assert fsm.state == State.CARD

    def test_timeout_from_loading_returns_idle(self):
        fsm = self._idle()
        fsm.send(Event.BUTTON_SINGLE)
        fsm.send(Event.LOADING_START)
        fsm.send(Event.TIMEOUT)
        assert fsm.state == State.IDLE


class TestFSMPrivacy:
    def _idle(self):
        fsm = DreamLayerFSM()
        fsm.send(Event.BLE_CONNECT)
        return fsm

    def test_long_press_enters_privacy(self):
        fsm = self._idle()
        fsm.send(Event.BUTTON_LONG)
        assert fsm.state == State.PRIVACY_VEIL
        assert fsm.ctx.privacy_active is True

    def test_long_press_exits_privacy(self):
        fsm = self._idle()
        fsm.send(Event.BUTTON_LONG)
        fsm.send(Event.BUTTON_LONG)
        assert fsm.state == State.IDLE
        assert fsm.ctx.privacy_active is False

    def test_card_suppressed_in_privacy(self):
        fsm  = self._idle()
        card = MemoryCard(card_type="ObjectRecallCard", payload={"object": "KEYS"})
        fsm.send(Event.BUTTON_LONG)
        fsm.send(Event.CARD_RECEIVED, payload=card)
        assert fsm.state == State.PRIVACY_VEIL   # stays in PRIVACY
        assert fsm.ctx.card_count == 0      # card NOT displayed

    def test_privacy_toggle_exits(self):
        fsm = self._idle()
        fsm.send(Event.BUTTON_LONG)
        fsm.send(Event.PRIVACY_TOGGLE)
        assert fsm.state == State.IDLE

    def test_single_click_noop_in_privacy(self):
        fsm = self._idle()
        fsm.send(Event.BUTTON_LONG)
        fsm.send(Event.BUTTON_SINGLE)
        assert fsm.state == State.PRIVACY_VEIL

    def test_privacy_clears_card(self):
        fsm  = self._idle()
        card = MemoryCard(card_type="SavedMemoryCard", payload={"primary": "x"})
        fsm.send(Event.CARD_RECEIVED, payload=card)
        assert fsm.ctx.current_card is not None
        fsm.send(Event.BUTTON_LONG)
        assert fsm.ctx.current_card is None

    def test_long_press_from_listening_enters_privacy(self):
        fsm = self._idle()
        fsm.send(Event.BUTTON_SINGLE)
        fsm.send(Event.BUTTON_LONG)
        assert fsm.state == State.PRIVACY_VEIL


class TestFSMHistory:
    def test_history_tracks_states(self):
        fsm = DreamLayerFSM()
        fsm.send(Event.BLE_CONNECT)
        fsm.send(Event.BUTTON_SINGLE)
        assert State.IDLE in fsm.ctx.history

    def test_previous_state(self):
        fsm = DreamLayerFSM()
        fsm.send(Event.BLE_CONNECT)
        assert fsm.ctx.previous_state() == State.DISCONNECT

    def test_reset_clears_history(self):
        fsm = DreamLayerFSM()
        fsm.send(Event.BLE_CONNECT)
        fsm.reset()
        assert fsm.ctx.history == []
        assert fsm.state == State.DISCONNECT


class TestFSMTransitionCallback:
    def test_callback_fires_on_transition(self):
        log = []
        fsm = DreamLayerFSM(on_transition=lambda p, e, n: log.append((p, e, n)))
        fsm.send(Event.BLE_CONNECT)
        assert log == [(State.DISCONNECT, Event.BLE_CONNECT, State.IDLE)]

    def test_callback_not_fired_on_unknown_event(self):
        log = []
        fsm = DreamLayerFSM(on_transition=lambda p, e, n: log.append((p, e, n)))
        fsm.send(Event.BUTTON_SINGLE)   # no transition from DISCONNECT
        assert log == []


class TestFSMUnknownEvents:
    def test_unknown_event_ignored(self):
        fsm = DreamLayerFSM()
        prev = fsm.state
        fsm.send(Event.BUTTON_SINGLE)   # no transition from DISCONNECT
        assert fsm.state == prev

    def test_double_click_idle_noop(self):
        fsm = DreamLayerFSM()
        fsm.send(Event.BLE_CONNECT)
        fsm.send(Event.BUTTON_DOUBLE)
        assert fsm.state == State.IDLE


class TestMemoryCard:
    def test_high_confidence(self):
        card = MemoryCard(card_type="ObjectRecallCard", payload={}, confidence=0.91)
        assert card.is_high_confidence() is True

    def test_low_confidence(self):
        card = MemoryCard(card_type="ObjectRecallCard", payload={}, confidence=0.50)
        assert card.is_high_confidence() is False

    def test_boundary_confidence(self):
        card = MemoryCard(card_type="ObjectRecallCard", payload={}, confidence=0.75)
        assert card.is_high_confidence() is True

    def test_default_source(self):
        card = MemoryCard(card_type="LoadingCard", payload={})
        assert card.source == "ble"


class TestTransitionTable:
    def test_all_transitions_have_valid_states(self):
        for (s, e), (ns, _) in _TRANSITIONS.items():
            assert isinstance(s, State)
            assert isinstance(e, Event)
            assert isinstance(ns, State)

    def test_disconnect_reachable_from_all_active_states(self):
        active = {State.IDLE, State.LISTENING, State.LOADING, State.CARD, State.PRIVACY_VEIL}
        reachable = {
            s for (s, e), (ns, _) in _TRANSITIONS.items()
            if e == Event.BLE_DISCONNECT and ns == State.DISCONNECT
        }
        assert active == reachable
