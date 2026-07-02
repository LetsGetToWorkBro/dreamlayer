--- main.lua  —  DreamLayer Halo entry-point
---
--- Boots the card queue FSM, wires BLE host-comm, and runs the tick loop.
--- Dream Mode is activated by a double-tap event from the host.

local CardQueue  = require("card_queue")
-- card_queue is a class (CardQueue.new() + method calls); one queue
-- instance drives the whole HUD. Priority constants stay on the class.
local Cards      = CardQueue.new()
local HostComm   = require("ble.host_comm")   -- already wires DC via require
local DreamRend  = require("display.dream_renderer")
local PAL        = require("display.palette")
local Figment    = require("app.figment_stage") -- Reality Compiler v2 stage

-- figment_put/swap/revoke/text arrive as BLE envelopes → stage handlers
Figment.register(HostComm)

-- ---------------------------------------------------------------------------
-- Card priority table (existing + dream card types)
-- ---------------------------------------------------------------------------
local CARD_PRIORITY = {
  -- Memory Mode cards
  ReadyCard            = CardQueue.AMBIENT,
  SavedMemoryCard      = CardQueue.CONTEXT,
  QueryListeningCard   = CardQueue.URGENT,
  LoadingCard          = CardQueue.URGENT,
  ObjectRecallCard     = CardQueue.URGENT,
  CommitmentRecallCard = CardQueue.URGENT,
  ProactiveMemoryCard  = CardQueue.CONTEXT,
  PersonContextCard    = CardQueue.CONTEXT,
  PrivacyPausedCard    = CardQueue.URGENT,
  ErrorCard            = CardQueue.URGENT,
  LowConfidenceCard    = CardQueue.CONTEXT,
  CommitmentDriftCard  = CardQueue.CONTEXT,
  TimeScrubNodeCard    = CardQueue.URGENT,
  DeviationAlertCard   = CardQueue.URGENT,
  ForgetLastCard       = CardQueue.URGENT,
  PrivateZoneCard      = CardQueue.URGENT,
  ConsentRequiredCard  = CardQueue.URGENT,
  LiveCaptionCard      = CardQueue.CONTEXT,
  -- Dream Mode cards
  SynesthesiaCard      = CardQueue.URGENT,    -- VLM scene description overlay
  PaletteShiftCard     = CardQueue.AMBIENT,   -- mic-reactive color shift
  WorldAnchorCard      = CardQueue.CONTEXT,   -- ghost memory echo at place
}

-- ---------------------------------------------------------------------------
-- BLE event handlers
-- ---------------------------------------------------------------------------
local function process_inbound(msg)
  if not msg then return end
  local t = msg.t

  -- Dream Mode messages are handled directly by host_comm dispatch
  -- (registered by host_comm_dream via DC.register at require time).
  -- We still call on_message so any remaining handlers fire.
  HostComm.on_message(msg)

  if t == "card" then
    local ptype    = msg.card_type or msg.type or "ObjectRecallCard"
    local priority = CARD_PRIORITY[ptype] or CardQueue.CONTEXT
    msg.type = ptype   -- queue and renderers key on .type; hosts send card_type
    Cards:push(msg, priority)

  elseif t == "command" then
    local cmd = msg.cmd or msg.command or ""
    if cmd == "show_ready" then
      Cards:push({ type = "ReadyCard" }, CardQueue.AMBIENT)
    elseif cmd == "ask" then
      Cards:push({ type = "QueryListeningCard" }, CardQueue.URGENT)
    elseif cmd == "resume" then
      Cards:push({ type = "ReadyCard" }, CardQueue.AMBIENT)
    end

  elseif t == "button" and Figment.is_running() then
    -- while a figment holds the stage, physical buttons drive it
    local ev = msg.ev or ""
    if ev == "single" or ev == "double" or ev == "long" then
      Figment.on_event(ev)
    end

  elseif t == "double_tap" then
    -- Host sends t="double_tap" to mirror the gesture back for Lua FSM;
    -- actual dream enter/exit is handled in host_comm_dream via dream_enter/exit.
    -- Here we just update card queue behaviour.
    if HostComm.dream_active() then
      Cards:clear()
    end
  end
end

-- ---------------------------------------------------------------------------
-- Dream render integration
-- ---------------------------------------------------------------------------
local function render_dream_card(card)
  local ct = card.type or ""
  if ct == "WorldAnchorCard" then
    DreamRend.render_world_anchor(card)
  elseif ct == "SynesthesiaCard" then
    -- v2 payloads (Halo Cinema v1) compose phrase + gestural sprite
    if card.version == 2 then
      DreamRend.draw_synesthesia_v2(card)
    else
      DreamRend.render_synesthesia(card)
    end
  end
end

-- ---------------------------------------------------------------------------
-- Main tick  (called by halo.runloop or a while-true loop at ~20fps)
-- ---------------------------------------------------------------------------
local function tick()
  -- Receive BLE
  local raw = (_G.halo and _G.halo.bluetooth and _G.halo.bluetooth.receive
               and _G.halo.bluetooth.receive()) or nil
  if raw then
    local msg = HostComm.on_receive(raw)
    if msg then process_inbound(msg) end
  end

  -- Render
  if Figment.is_running() then
    -- a deployed figment owns the display; it renders via its bound
    -- display API and yields the stage the moment it ends or is revoked
    Figment.tick(0.05)
  elseif HostComm.dream_active() then
    -- Dream Mode: draw ambient layer then any pending dream cards
    DreamRend.draw_frame()
    local card = Cards:peek()
    if card then
      render_dream_card(card)
      -- Auto-dismiss dream cards after their dismiss_ms
      -- (CardQueue handles dismiss timer internally)
    end
  else
    -- Memory Mode: normal card queue rendering
    local card = Cards:peek()
    if card then
      -- card rendering handled by existing display/cards.lua pipeline
      -- (unchanged from pre-dream main.lua)
    end
  end
end

-- ---------------------------------------------------------------------------
-- Boot
-- ---------------------------------------------------------------------------
-- Bind the BLE channel so device→host sends (figment acks, telemetry)
-- actually leave the device — HostComm.send drops silently when unbound.
if _G.halo and _G.halo.bluetooth then
  HostComm.bind(_G.halo.bluetooth)
end

-- Give the figment stage its whitelisted effects: display, host send,
-- battery. This is the entire capability surface a figment can reach.
Figment.bind({
  display = _G.halo and _G.halo.display or nil,
  send    = HostComm.send,
  battery = _G.halo and _G.halo.battery_level or nil,
})

if _G.halo and _G.halo.runloop then
  _G.halo.runloop(tick)
else
  -- Emulator / test: expose tick for external test harness
  _G._dreamlayer_tick = tick
end

return { tick = tick, CARD_PRIORITY = CARD_PRIORITY }
