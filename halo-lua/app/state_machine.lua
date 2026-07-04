-- app/state_machine.lua
-- Real finite-state machine for DreamLayer Halo.
--
-- States:
--   boot         -> startup event -> ready
--   ready        -> host_connected -> connected
--                -> single_click  -> query_listening
--                -> long_press    -> privacy_veil
--   connected    -> card_received  -> showing_card
--                -> command_received (ask) -> query_listening
--                -> command_received (pause) -> privacy_veil
--                -> command_received (show_ready) -> ready
--                -> single_click  -> query_listening
--                -> long_press    -> privacy_veil
--                -> host_disconnected -> ready
--   showing_card -> single_click  -> connected  (dismiss)
--                -> double_click  -> connected  (dismiss)
--                -> card_received -> showing_card (replace)
--                -> dismiss_timer -> connected
--                -> host_disconnected -> ready
--   query_listening -> card_received -> showing_card
--                   -> single_click  -> connected  (cancel)
--                   -> host_disconnected -> ready
--   privacy_veil  -> long_press    -> connected  (resume)
--                   -> command_received (resume) -> connected
--                   -> host_disconnected -> ready
--
-- Public API:
--   M.init(renderer, scheduler, on_transition, on_show_card)
--   M.dispatch(event, payload)
--   M.state()
--   M.set_card(card)    -- called by main.lua when a card BLE message arrives
--   M.set_command(kind) -- called by main.lua when a command BLE message arrives

local E = require("app.events")

local M = {}

local _state         = "boot"
local _renderer      = nil
local _on_transition = nil
local _on_show_card  = nil   -- injected by main.lua; routes cards through CardQueue
local _current_card  = nil
local _cards         = nil

local function cards()
  if not _cards then _cards = require("display.cards") end
  return _cards
end

local function transition(new_state)
  local old = _state
  _state = new_state
  if _on_transition then
    pcall(_on_transition, old, new_state, nil)
  end
end

-- show() routes through the injected queue hook when available,
-- falling back to direct renderer.show_card() for backward compat.
local function show(card)
  _current_card = card
  if _on_show_card then
    pcall(_on_show_card, card)
  elseif _renderer then
    pcall(_renderer.show_card, card)
  end
end

-- ---------------------------------------------------------------------------
-- State transition table
-- ---------------------------------------------------------------------------
local TRANSITIONS = {}

TRANSITIONS["boot"] = {
  [E.EVENTS.startup] = function(_)
    transition("ready")
    show(cards().ready())
  end,
}

TRANSITIONS["ready"] = {
  [E.EVENTS.host_connected] = function(_)
    transition("connected")
    show(cards().ready())
  end,
  [E.EVENTS.single_click] = function(_)
    transition("query_listening")
    show(cards().query_listening())
  end,
  [E.EVENTS.long_press] = function(_)
    transition("privacy_veil")
    show(cards().privacy_veil())
  end,
  [E.EVENTS.card_received] = function(payload)
    transition("showing_card")
    show(payload)
  end,
}

TRANSITIONS["connected"] = {
  [E.EVENTS.card_received] = function(payload)
    transition("showing_card")
    show(payload)
  end,
  [E.EVENTS.command_received] = function(payload)
    local kind = payload and payload.kind
    if kind == "ask" then
      transition("query_listening")
      show(cards().query_listening())
    elseif kind == "pause" then
      transition("privacy_veil")
      show(cards().privacy_veil())
    elseif kind == "show_ready" or kind == "reset" then
      transition("ready")
      show(cards().ready())
    elseif kind == "loading" then
      show(cards().loading())
    end
  end,
  [E.EVENTS.single_click] = function(_)
    transition("query_listening")
    show(cards().query_listening())
  end,
  [E.EVENTS.long_press] = function(_)
    transition("privacy_veil")
    show(cards().privacy_veil())
  end,
  [E.EVENTS.host_disconnected] = function(_)
    transition("ready")
    show(cards().ready())
  end,
}

TRANSITIONS["showing_card"] = {
  [E.EVENTS.card_received] = function(payload)
    show(payload)
  end,
  [E.EVENTS.single_click] = function(_)
    transition("connected")
    show(cards().ready())
  end,
  [E.EVENTS.double_click] = function(_)
    transition("connected")
    show(cards().ready())
  end,
  [E.EVENTS.long_press] = function(_)
    transition("privacy_veil")
    show(cards().privacy_veil())
  end,
  [E.EVENTS.imu_tap] = function(_)
    transition("connected")
    -- queue:dismiss() already called in main.lua before this dispatch
  end,
  [E.EVENTS.host_disconnected] = function(_)
    transition("ready")
    show(cards().ready())
  end,
}

TRANSITIONS["query_listening"] = {
  [E.EVENTS.card_received] = function(payload)
    transition("showing_card")
    show(payload)
  end,
  [E.EVENTS.single_click] = function(_)
    transition("connected")
    show(cards().ready())
  end,
  [E.EVENTS.long_press] = function(_)
    transition("privacy_veil")
    show(cards().privacy_veil())
  end,
  [E.EVENTS.host_disconnected] = function(_)
    transition("ready")
    show(cards().ready())
  end,
}

TRANSITIONS["privacy_veil"] = {
  [E.EVENTS.long_press] = function(_)
    transition("connected")
    show(cards().ready())
  end,
  [E.EVENTS.command_received] = function(payload)
    local kind = payload and payload.kind
    if kind == "resume" then
      transition("connected")
      show(cards().ready())
    end
  end,
  [E.EVENTS.host_disconnected] = function(_)
    transition("ready")
    show(cards().ready())
  end,
}

-- ---------------------------------------------------------------------------
-- Public API
-- ---------------------------------------------------------------------------

--- @param renderer      table    display.renderer
--- @param scheduler     any      unused, reserved
--- @param on_transition function called on every state change
--- @param on_show_card  function optional; injected by main.lua to route cards
---                                through CardQueue instead of direct render
function M.init(renderer, scheduler, on_transition, on_show_card)
  _renderer      = renderer
  _on_transition = on_transition
  _on_show_card  = on_show_card
  _state         = "boot"
  _current_card  = nil
  _cards         = nil
end

function M.dispatch(event, payload)
  local handlers = TRANSITIONS[_state]
  if not handlers then return end
  local fn = handlers[event]
  if fn then
    local ok, err = pcall(fn, payload)
    if not ok then
      print("[fsm] error in " .. tostring(_state) .. "/" .. tostring(event) .. ": " .. tostring(err))
    end
  end
end

function M.state()
  return _state
end

function M.set_card(msg_payload)
  local C   = cards()
  local t   = msg_payload and msg_payload.type
  local card
  if t == "ObjectRecallCard" then
    card = C.object_recall(msg_payload)
  elseif t == "CommitmentRecallCard" then
    card = C.commitment_recall(msg_payload)
  elseif t == "ProactiveMemoryCard" then
    card = C.proactive_memory(msg_payload)
  elseif t == "PersonContextCard" then
    card = C.person_context(msg_payload)
  elseif t == "SavedMemoryCard" then
    card = C.saved_memory(msg_payload.primary)
  elseif t == "QueryListeningCard" then
    card = C.query_listening()
  elseif t == "LoadingCard" then
    card = C.loading()
  elseif t == "PrivacyVeilCard" then
    card = C.privacy_veil()
  elseif t == "ErrorCard" then
    card = C.error_card(msg_payload.primary)
  elseif t == "LowConfidenceCard" then
    card = C.low_confidence()
  elseif t == "FactCheckCard" then
    card = C.fact_check(msg_payload)
  elseif t == "AnswerAheadCard" then
    card = C.answer_ahead(msg_payload)
  elseif t == "OracleReplyCard" then
    card = C.oracle_reply(msg_payload)
  elseif t == "HarkCard" then
    card = C.hark(msg_payload)
  else
    card = C.error_card("Unknown card: " .. tostring(t))
  end
  M.dispatch(E.EVENTS.card_received, card)
end

function M.set_command(msg)
  M.dispatch(E.EVENTS.command_received, msg)
end

return M
