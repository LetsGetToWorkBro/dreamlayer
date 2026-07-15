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
local ImuGesture = require("app.imu_gesture")    -- Nod to Remember (boot-flag)
local StateMachine = require("app.state_machine") -- on-device input FSM (Veil toggle)
local E          = require("app.events")          -- FSM event constants
local MT         = require("ble.message_types")
local Horizon    = require("display.horizon")   -- Meridian day-ring
local Renderer   = require("display.renderer")
local Particles  = require("display.particles") -- Lumen hero pool
local PalAnim    = require("display.palette_animator")
local Parallax   = require("display.parallax")
local Anim       = require("display.animations")
local Telemetry  = require("ble.telemetry")
local StasisFx   = require("display.stasis")     -- shutter + ribbon in Dream
                                                 -- Mode (Renderer owns Memory
                                                 -- Mode's pass; docs/STASIS.md)
local Theme      = require("display.theme")      -- Forkable Skin (3.6)

-- Forkable Skin: if the host set a theme table before boot, restyle the
-- static identity (palette + type scale + motion) over the shipped defaults.
-- Applied before any card renders; refused whole if it fails the skin budget,
-- so a bad theme falls back to the defaults instead of a half-applied look.
if type(_G.DREAMLAYER_THEME) == "table" then
  local ok, issues = Theme.apply(_G.DREAMLAYER_THEME)
  if not ok then
    Telemetry.emit(Telemetry.TICK_ERROR,
                   { where = "theme", why = issues[1] or "invalid theme" })
  end
end

-- Monotonic tick clock (50ms/tick). Declared here, ahead of the BLE
-- registrations below, so their closures can pass it to time-based handlers
-- (Lua upvalues must be in lexical scope at the point the closure is defined).
-- Without this, on_timbre/on_tincan received nil and computed until_ms = 0 + TTL,
-- so every Timbre/TinCan frame expired on the first draw after ~2.5s uptime.
local _tick_ms = 0

-- figment_put/swap/revoke/text arrive as BLE envelopes → stage handlers
Figment.register(HostComm)

-- Meridian: composed day-ring frames land in the horizon plotter
HostComm.register(MT.HORIZON, function(msg) Horizon.on_frame(msg) end)
-- Yesterlight scrub state rides the same plotter
HostComm.register(MT.YESTERLIGHT,
                  function(msg) Horizon.on_yesterlight(msg) end)
-- Timbre: known-voice waveforms land in the dream renderer (needs the tick
-- clock so the frame's lifetime is measured from *now*, not from boot).
HostComm.register(MT.TIMBRE,
                  function(msg) DreamRend.on_timbre(msg, _tick_ms) end)
-- Confluence: the entangled sky; TinCan: the partner's silent ping
HostComm.register(MT.CONFLUENCE,
                  function(msg) DreamRend.on_confluence(msg) end)
HostComm.register(MT.TINCAN,
                  function(msg) DreamRend.on_tincan(msg, _tick_ms) end)
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
  HarkCard             = CardQueue.URGENT,    -- Juno's "Listen!"
  JunoReplyCard      = CardQueue.CONTEXT,   -- Juno's answer / confirmation
  -- World lenses (each answers an active look / tap)
  ScholarCard          = CardQueue.URGENT,    -- an answer/form read off the world
  GlanceChoiceCard     = CardQueue.URGENT,    -- the chooser: awaiting your tap
  TasteCard            = CardQueue.URGENT,    -- the pick, while you're deciding
  -- Missing frames
  ListeningCard        = CardQueue.URGENT,    -- Juno's wake cue, the moment it wakes
  MessageCard          = CardQueue.URGENT,    -- a text/mail arriving
  UpcomingCard         = CardQueue.CONTEXT,   -- an event about to start
  HereCard             = CardQueue.CONTEXT,   -- something you left is right here
  PersonDossierCard    = CardQueue.CONTEXT,   -- who this is + your ledger
  SpokenCaptionCard    = CardQueue.CONTEXT,   -- live caption of a familiar voice
  MorningBriefCard     = CardQueue.CONTEXT,   -- the wake brief
  -- Ember (docs/EMBER.md) — the practice is calm by contract: the glow and
  -- the flare are ambient (they never pre-empt anything), the reveal and
  -- the graduation are context (the wearer just spoke; they're waiting)
  EmberPromptCard      = CardQueue.AMBIENT,   -- the glow at the doorway
  EmberFlareCard       = CardQueue.AMBIENT,   -- you reached it; one breath
  EmberRevealCard      = CardQueue.CONTEXT,   -- the gentle answer
  EmberGraduatedCard   = CardQueue.CONTEXT,   -- it lives in you now
}

-- ---------------------------------------------------------------------------
-- On-device input FSM (app/state_machine.lua).
--
-- Audit 2026-07-14: the FSM was DEAD — required by no boot path, driven by no
-- test — so the documented local `long_press → privacy_veil` affordance never
-- existed and there was NO on-glass Veil toggle. We wire it here: when no
-- figment holds the stage, physical buttons drive the FSM, and a long-press
-- toggles the Veil with no host/phone in the loop. Entering/leaving the veil
-- emits PRIVACY_VEIL / PRIVACY_RESUMED telemetry, which the phone honors to
-- silence its lens relay (phone-app src/services/lensRelay.ts). The FSM's cards
-- ride the SAME one card queue; its idle "ready" card is just the empty-queue
-- Horizon the renderer already draws, so we clear to that rather than stack a
-- duplicate card (the audit's "card registry in 3-4 places" is not re-created).
-- ---------------------------------------------------------------------------
local function _on_fsm_transition(old_state, new_state)
  if new_state == "privacy_veil" then
    Telemetry.emit(Telemetry.PRIVACY_VEIL, {})
  elseif old_state == "privacy_veil" then
    Telemetry.emit(Telemetry.PRIVACY_RESUMED, {})
  end
end

local function _on_fsm_card(card)
  if not card then return end
  if card.type == "ReadyCard" then
    -- idle / resume: main.lua's empty-queue renderer IS the "ready" Horizon,
    -- so drop the (veil) card back to it instead of stacking a ReadyCard.
    Cards:dismiss(_tick_ms)
    return
  end
  Cards:push(card, CARD_PRIORITY[card.type] or CardQueue.CONTEXT)
end

StateMachine.init(Renderer, nil, _on_fsm_transition, _on_fsm_card)
StateMachine.dispatch(E.EVENTS.startup)   -- boot → ready so long-press is live

-- ---------------------------------------------------------------------------
-- Tick clock (_tick_ms) is declared near the top so the BLE registrations can
-- close over it; the banish gesture below closes over it too.
-- ---------------------------------------------------------------------------
local BANISH_WINDOW_MS = 2000
local _last_long_ms = -BANISH_WINDOW_MS  -- last long-press (banish gesture)

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
    StateMachine.dispatch(E.EVENTS.host_connected)  -- ready → connected

  elseif t == "button" then
    local ev = msg.ev or ""
    if Figment.is_running() then
      -- while a figment holds the stage, physical buttons drive it —
      -- EXCEPT the escape hatch: two long-presses within BANISH_WINDOW_MS
      -- banish the figment locally, no host required. A figment may consume
      -- single long-presses, but it can never swallow its own kill switch.
      if ev == "long" then
        if _tick_ms - _last_long_ms <= BANISH_WINDOW_MS then
          local id = Figment.banish()
          if id then
            Telemetry.emit(Telemetry.FIGMENT_BANISHED, { id = id })
          end
          _last_long_ms = -BANISH_WINDOW_MS
        else
          _last_long_ms = _tick_ms
          Figment.on_event(ev)
        end
      elseif ev == "single" or ev == "double" then
        Figment.on_event(ev)
      end
    else
      -- no figment on stage: physical buttons drive the on-device FSM, giving
      -- the wearer a LOCAL Veil toggle (long-press → privacy_veil → resume)
      -- with no host or phone in the loop. See the FSM-wiring note above.
      if ev == "long" then
        StateMachine.dispatch(E.EVENTS.long_press)
      elseif ev == "single" then
        StateMachine.dispatch(E.EVENTS.single_click)
      elseif ev == "double" then
        StateMachine.dispatch(E.EVENTS.double_click)
      end
    end

  elseif t == "event" then
    -- a named physical-world signal from the host ($6 ESP32 kit, 1.6):
    -- deliver it to the running figment's scene grammar. Harmless if no
    -- figment is up or its scenes don't listen for msg.name — on_event is a
    -- no-op then, and the figment's own emit/scene budgets still bound it.
    if Figment.is_running() and msg.name then
      Figment.on_event(msg.name)
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
local _shown     = nil   -- card instance currently owned by the renderer
local _dreaming  = false -- last seen dream state (Lumen warp trigger)

-- Nod to Remember (INNOVATION 2.1): the tuned IMU classifier, declared here as
-- an upvalue so tick_body can feed it. Instantiated at boot only behind the
-- boot flag (default OFF); nil means the whole path is dormant and free.
local _imu = nil
local function _read_accel()
  local imu = _G.halo and _G.halo.imu
  if not imu or not imu.read then return nil end
  local ok, ax, ay, az = pcall(imu.read)
  if ok and type(ax) == "number" then return ax, ay, az end
  return nil
end

local function tick_body()
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

  -- Receive BLE — drain every complete frame (two frames can arrive
  -- concatenated in a single chunk; leaving one queued adds a tick of lag)
  local raw = (_G.halo and _G.halo.bluetooth and _G.halo.bluetooth.receive
               and _G.halo.bluetooth.receive()) or nil
  if raw then
    local msg = HostComm.on_receive(raw)
    while msg do
      process_inbound(msg)
      msg = HostComm.on_receive("")
    end
  end

  -- Nod to Remember: feed one accel sample per tick when enabled + present.
  -- A NOD_SAVE / SHAKE / etc. fires the on_gesture callback → imu_gesture
  -- envelope to the host. Dormant (and free) unless the boot flag wired _imu.
  if _imu then
    local ax, ay, az = _read_accel()
    if ax then _imu:feed(ax, ay, az, _tick_ms) end
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
    -- Stasis shutter/ribbon rides over the weather too (sub-card, no queue)
    StasisFx.draw(_tick_ms)
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

  -- Heap watermark: one telemetry event a minute so the host learns the
  -- real on-device memory ceiling (Rig-1 data). collectgarbage may be
  -- absent on device firmware — pcall-guarded, and cheap when it is.
  if _tick_ms % 60000 == 0 then
    local ok, kb = pcall(collectgarbage, "count")
    if ok and type(kb) == "number" then
      Telemetry.emit(Telemetry.HEAP, { kb = math.floor(kb) })
    end
  end
end

-- ---------------------------------------------------------------------------
-- Crash guard: the tick is pcall-wrapped so one bad frame can never kill the
-- display until reboot. On failure we render the never-black fallback (a bare
-- dim ring at the safe radius) and emit ONE rate-limited TICK_ERROR so the
-- host sees the crash instead of silence. "The display is a place, not a
-- stage" is a guarantee here, not a policy.
-- ---------------------------------------------------------------------------
local _tick_errors      = 0
local _last_err_tel_ms  = -60000

local function _render_fallback()
  local d = _G.halo and _G.halo.display
  if not d then return end
  pcall(function()
    d.clear(0x000000)
    if d.circle then d.circle(128, 128, 112, { color = 0x223344 }) end
    d.show()
  end)
end

local function tick()
  local ok, err = pcall(tick_body)
  if ok then return end
  _tick_errors = _tick_errors + 1
  -- _tick_ms already advanced inside tick_body before any failure point
  if _tick_ms - _last_err_tel_ms >= 60000 then
    _last_err_tel_ms = _tick_ms
    Telemetry.emit(Telemetry.TICK_ERROR,
                   { error = string.sub(tostring(err), 1, 120),
                     count = _tick_errors })
  end
  _render_fallback()
end

-- ---------------------------------------------------------------------------
-- Boot
-- ---------------------------------------------------------------------------
-- Bind the BLE channel so device→host sends (figment acks, telemetry)
-- actually leave the device — HostComm.send drops silently when unbound.
if _G.halo and _G.halo.bluetooth then
  HostComm.bind(_G.halo.bluetooth)
end

-- Wire telemetry to the same channel. Without this bind every emit is a
-- silent no-op and the host's feedback loops (adaptive confidence, crash
-- and heap reports) never see the device.
Telemetry.bind(HostComm.send)

-- Physical buttons: route through the SAME path as host-mirrored button
-- events so on-device and host-driven input behave identically (and the
-- figment banish gesture works with no host connected).
if _G.halo and _G.halo.button then
  local function _button(ev)
    return function() process_inbound({ t = "button", ev = ev }) end
  end
  if _G.halo.button.single then _G.halo.button.single(_button("single")) end
  if _G.halo.button.double then _G.halo.button.double(_button("double")) end
  if _G.halo.button.long   then _G.halo.button.long(_button("long"))     end
end

-- Nod to Remember: enable the IMU gesture classifier only behind the boot flag
-- (_G.halo.config.imu_gestures, default OFF), so default boot is unchanged.
-- Each gesture crosses to the host as an imu_gesture envelope: NOD_SAVE → a
-- pinned memory, SHAKE_DISMISS → dismiss the current card (see ops_ingest).
if _G.halo and _G.halo.config and _G.halo.config.imu_gestures then
  _imu = ImuGesture.new({
    on_gesture = function(name, conf)
      HostComm.send({ t = "imu_gesture", gesture = name, confidence = conf })
    end,
  })
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
