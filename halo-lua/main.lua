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
local Prism      = require("display.prism")
local PAL        = require("display.palette")
local Figment    = require("app.figment_stage") -- Reality Compiler v2 stage
local MT         = require("ble.message_types")
local Horizon    = require("display.horizon")   -- Meridian day-ring
local Renderer   = require("display.renderer")
local Particles  = require("display.particles") -- Lumen hero pool
local PalAnim    = require("display.palette_animator")
local Parallax   = require("display.parallax")
local Anim       = require("display.animations")

-- figment_put/swap/revoke/text arrive as BLE envelopes → stage handlers
Figment.register(HostComm)

-- Meridian: composed day-ring frames land in the horizon plotter
HostComm.register(MT.HORIZON, function(msg) Horizon.on_frame(msg) end)
-- Yesterlight scrub state rides the same plotter
HostComm.register(MT.YESTERLIGHT,
                  function(msg) Horizon.on_yesterlight(msg) end)
-- Timbre: known-voice waveforms land in the dream renderer
HostComm.register(MT.TIMBRE,
                  function(msg) DreamRend.on_timbre(msg) end)
-- Confluence: the entangled sky; TinCan: the partner's silent ping
HostComm.register(MT.CONFLUENCE,
                  function(msg) DreamRend.on_confluence(msg) end)
HostComm.register(MT.TINCAN,
                  function(msg) DreamRend.on_tincan(msg) end)
-- Prism Lens: the psychedelic kaleidoscope overlay
HostComm.register(MT.PRISM, function(msg) Prism.on_prism(msg) end)
-- Lumen: live voice level drives the listening waveform
HostComm.register(MT.AMP, function(msg) Renderer.on_amp(msg) end)

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
  PrivacyVeilCard      = CardQueue.URGENT,
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
  -- O3 conversation cards
  FactCheckCard        = CardQueue.URGENT,    -- Veritas: a claim needs your eye now
  AnswerAheadCard      = CardQueue.URGENT,    -- the answer, in time to say it
  HarkCard             = CardQueue.URGENT,    -- Oracle's "Listen!"
  OracleReplyCard      = CardQueue.CONTEXT,   -- Oracle's answer / confirmation
  -- World lenses (each answers an active look / tap)
  ScholarCard          = CardQueue.URGENT,    -- an answer/form read off the world
  GlanceChoiceCard     = CardQueue.URGENT,    -- the chooser: awaiting your tap
  TasteCard            = CardQueue.URGENT,    -- the pick, while you're deciding
  -- Missing frames
  ListeningCard        = CardQueue.URGENT,    -- Oracle's wake cue, the moment it wakes
  MessageCard          = CardQueue.URGENT,    -- a text/mail arriving
  UpcomingCard         = CardQueue.CONTEXT,   -- an event about to start
  HereCard             = CardQueue.CONTEXT,   -- something you left is right here
  PersonDossierCard    = CardQueue.CONTEXT,   -- who this is + your ledger
  SpokenCaptionCard    = CardQueue.CONTEXT,   -- live caption of a familiar voice
  MorningBriefCard     = CardQueue.CONTEXT,   -- the wake brief
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
    elseif cmd == "wake" then
      -- Lumen wake ring: the day assembles outward from the notch
      Horizon.wake()
    end

  elseif t == "connect" then
    Horizon.wake()

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
local _tick_ms   = 0     -- monotonic tick clock (50ms per tick)
local _shown     = nil   -- card instance currently owned by the renderer
local _dreaming  = false -- last seen dream state (Lumen warp trigger)

local function tick()
  _tick_ms = _tick_ms + 50

  -- Lumen dream door: entering/leaving Dream Mode is a starfield breath
  -- over the SAME terrain — streaks rush outward into the dream and
  -- inward on the way back — instead of the old hard clear
  -- (docs/CINEMA_V2_DELTAS.md §8's stated risk, answered).
  local dreaming = HostComm.dream_active()
  if dreaming ~= _dreaming then
    _dreaming = dreaming
    Particles.clear()
    Particles.streaks(Anim.WARP_STREAKS, {
      t0 = dreaming and _tick_ms or Renderer.now_ms(),
      seed = 7, reverse = not dreaming,
      ttl_ms = dreaming and Anim.MER_DREAM_ENTER_MS
                        or  Anim.MER_DREAM_EXIT_MS,
    })
  end

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
  elseif Prism.is_active() then
    -- Prism Lens: the psychedelic kaleidoscope owns the display while on.
    -- Parallax ticks here so the field floats with the wearer's head.
    local has_frame = (type(_G.frame) == "table")
    if has_frame then frame.display.clear(0x000000) end
    Parallax.tick(_tick_ms)
    Prism.draw(_tick_ms)
    if has_frame then frame.display.show() end
  elseif HostComm.dream_active() then
    -- Dream Mode: same terrain, different light (cinema_v2/weather.md) —
    -- the dimmed horizon under the weather, then any pending dream cards
    local has_frame = (type(_G.frame) == "table")
    if has_frame then frame.display.clear(0x000000) end
    DreamRend.draw_frame(_tick_ms)
    local card = Cards:peek()
    if card then
      render_dream_card(card)
      -- Auto-dismiss dream cards after their dismiss_ms
      -- (CardQueue handles dismiss timer internally)
    end
    -- Lumen: door streaks + any light programs ride over the weather
    Particles.tick(_tick_ms)
    PalAnim.tick(_tick_ms)
    if has_frame then frame.display.show() end
  else
    -- Memory Mode: the queue decides WHAT holds focus; the renderer
    -- decides HOW it condenses, holds, and recedes. With no card the
    -- renderer draws the Horizon — the display is never a black screen.
    local card = Cards:tick(_tick_ms)
    if card ~= _shown then
      if card then
        Renderer.show_card(card)
      else
        Renderer.dismiss()
      end
      _shown = card
    end
    Renderer.tick()
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
