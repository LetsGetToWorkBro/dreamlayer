--- main.lua : Memoscape Halo boot entry point.
--- Ported to real Brilliant Labs frame.* API.
---
--- CardQueue is wired here as the display layer between the FSM and renderer.
--- Cards arrive via BLE → state_machine.set_card() → queue:push()
--- The tick loop calls queue:tick() every frame → renderer.show_card() on change.
---
--- Cinematic transitions: renderer.bind(time_fn) is called at boot to wire
--- the monotonic clock. renderer.dismiss() is called when the queue expires
--- a card so the EXIT animation plays before the card disappears.

require("compat.frame_adapter")

local renderer      = require("display.renderer")
local cards         = require("display.cards")
local host_comm     = require("ble.host_comm")
local MT            = require("ble.message_types")
local state_machine = require("app.state_machine")
local session       = require("app.session")
local E             = require("app.events")
local CardQueue     = require("app.card_queue")

local HAS_FRAME = (type(_G.frame) == "table")

-- ---------------------------------------------------------------------------
-- Queue instance (shared, module-level)
-- ---------------------------------------------------------------------------
local queue = CardQueue.new()

-- Monotonic ms counter for environments without frame.time
local _boot_t   = os.clock()
local function now_ms()
  if HAS_FRAME and frame.time then
    return math.floor(frame.time.utc() * 1000) % (2^31)
  end
  return math.floor((os.clock() - _boot_t) * 1000)
end

-- Last card shown to renderer — used to detect changes and avoid redundant starts
local _last_shown = nil

-- ---------------------------------------------------------------------------
-- Priority mapping: which card types are URGENT vs CONTEXT vs AMBIENT
-- ---------------------------------------------------------------------------
local CARD_PRIORITY = {
  ObjectRecallCard     = CardQueue.URGENT,
  CommitmentRecallCard = CardQueue.URGENT,
  QueryListeningCard   = CardQueue.URGENT,
  LoadingCard          = CardQueue.URGENT,
  ReadyCard            = CardQueue.URGENT,
  PrivacyPausedCard    = CardQueue.URGENT,
  ProactiveMemoryCard  = CardQueue.CONTEXT,
  PersonContextCard    = CardQueue.CONTEXT,
  SavedMemoryCard      = CardQueue.CONTEXT,
  ErrorCard            = CardQueue.CONTEXT,
  LowConfidenceCard    = CardQueue.AMBIENT,
}

local function card_priority(card)
  return CARD_PRIORITY[card and card.type] or CardQueue.CONTEXT
end

-- ---------------------------------------------------------------------------
-- Inbound BLE dispatch
-- ---------------------------------------------------------------------------
local function process_inbound(msg)
  if not msg or not msg.t then return end
  local t = msg.t

  if t == MT.BUTTON then
    local ev_map = {
      [MT.BTN_SINGLE] = E.EVENTS.single_click,
      [MT.BTN_DOUBLE] = E.EVENTS.double_click,
      [MT.BTN_LONG]   = E.EVENTS.long_press,
    }
    local ev = ev_map[msg.ev]
    if ev then state_machine.dispatch(ev) end

  elseif t == MT.IMU_TAP then
    queue:dismiss(now_ms())
    renderer.dismiss()
    state_machine.dispatch(E.EVENTS.imu_tap)

  elseif t == MT.CONNECT then
    session.start(0)
    queue:clear()
    state_machine.dispatch(E.EVENTS.host_connected)

  elseif t == MT.DISCONNECT then
    session.end_session()
    queue:clear()
    state_machine.dispatch(E.EVENTS.host_disconnected)

  elseif t == MT.CARD then
    state_machine.set_card(msg.payload or msg)

  elseif t == MT.COMMAND then
    state_machine.set_command(msg)

  elseif t == MT.EVENT then
    if msg.name then
      state_machine.dispatch(msg.name, msg)
    end

  else
    host_comm.on_message(msg)
  end
end

local function on_ble_raw(raw)
  local msg = host_comm.on_receive(raw)
  if msg then process_inbound(msg) end
end

-- ---------------------------------------------------------------------------
-- queue_card: enqueue a card with correct priority
-- ---------------------------------------------------------------------------
local function queue_card(card)
  if not card then return end
  queue:push(card, card_priority(card))
end

-- ---------------------------------------------------------------------------
-- Boot
-- ---------------------------------------------------------------------------
local function boot()
  host_comm.bind(_G.halo.bluetooth)

  -- Wire monotonic clock into renderer for animation timing
  renderer.bind(nil, now_ms)

  state_machine.init(renderer, nil, function(old, new_state, _)
    -- Uncomment for debug: print("[fsm] " .. old .. " -> " .. new_state)
  end, queue_card)

  if HAS_FRAME then
    frame.bluetooth.receive_callback(on_ble_raw)
    frame.button.single(function()    state_machine.dispatch(E.EVENTS.single_click) end)
    frame.button.double(function()    state_machine.dispatch(E.EVENTS.double_click) end)
    frame.button.long(function()      state_machine.dispatch(E.EVENTS.long_press)   end)
    frame.imu.tap_callback(function()
      queue:dismiss(now_ms())
      renderer.dismiss()
      state_machine.dispatch(E.EVENTS.imu_tap)
    end)
  end

  state_machine.dispatch(E.EVENTS.startup)
  print(0)  -- signal host: Lua ready
end

boot()

-- ---------------------------------------------------------------------------
-- Main loop
-- ---------------------------------------------------------------------------
while true do
  local ok, err = pcall(function()
    local t = now_ms()

    -- Drive queue auto-dismiss
    local active = queue:tick(t)

    if active ~= _last_shown then
      _last_shown = active
      if active then
        -- New card: show_card() starts ENTER (crossfades if one is already showing)
        renderer.show_card(active)
      else
        -- Queue expired: begin EXIT animation, then fall back to ready card
        renderer.dismiss()
        -- Ready card will be shown after EXIT completes on next nil→show_card
        -- We delay it one tick so the exit plays; state_machine handles it
        -- via the dismiss_timer event path which calls show(cards.ready())
        renderer.show_card(cards.ready())
      end
    end

    -- Advance animations and push frame
    renderer.tick()

    if HAS_FRAME then frame.sleep(0.05) end
  end)
  if not ok then
    local msg = tostring(err or "")
    if msg:find("Emulator stopped") or msg:find("stopped") then
      break
    end
    print("[memoscape] error: " .. msg)
  end
end
