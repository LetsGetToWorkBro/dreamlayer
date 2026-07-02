--- display/diagnostics.lua
--- DreamLayer Halo — diagnostics overlay.
---
--- Activated by: long_press (toggle on/off).
--- Verbosity cycled by: single_click while open (MINIMAL → NORMAL → VERBOSE → MINIMAL).
--- Auto-hides after DIAG_TTL_MS if no further interaction.
---
--- Renders a corner HUD on top of the normal card frame:
---
---   TOP-LEFT     FSM state abbrev  |  card type abbrev
---   TOP-RIGHT    FPS (8-frame avg) |  heap free KB
---   BOT-LEFT     BLE rx / tx msgs  |  last msg type
---   BOT-RIGHT    queue depth (U/C/A) | phase / idle_t
---
--- VERBOSE mode adds a mid-panel with the active card's key/value fields
--- and the renderer's animation phase + eased scale.
---
--- All drawing goes through frame.display primitives.  When HAS_FRAME is
--- false (emulator / Python test) every draw call is a no-op and only
--- the state/counter API is active (so tests can assert against it).
---
--- Public API:
---   diag.bind(state_fn, queue_fn, renderer_fn)
---       Wire live data sources once at boot.
---       state_fn()   → string   current FSM state name
---       queue_fn()   → {urgent=N, context=N, ambient=N, depth=N}
---       renderer_fn()→ {phase=str, idle_t=N, card_type=str}
---   diag.toggle()     open/close overlay
---   diag.cycle()      step verbosity (call when overlay is open)
---   diag.ble_rx(t)    increment rx counter, record last msg type string
---   diag.ble_tx(t)    increment tx counter, record last msg type string
---   diag.frame_tick() call once per main-loop tick (before diag.tick)
---   diag.tick()       composite overlay onto current frame buffer
---   diag.is_open()    bool

local math = math
local HAS_FRAME = (type(_G.frame) == "table")

-- ---------------------------------------------------------------------------
-- Constants
-- ---------------------------------------------------------------------------
local DIAG_TTL_MS      = 5000   -- auto-hide after 5 s of no interaction
local FPS_WINDOW       = 8      -- rolling average over N frames
local CORNER_PAD       = 4      -- px from edge
local LINE_H           = 9      -- px per text row
local PANEL_W          = 120    -- max panel width (half of 256 - 2*pad)

-- Verbosity levels
local V_MINIMAL  = 1
local V_NORMAL   = 2
local V_VERBOSE  = 3

-- Palette (distinct from card palette to remain legible over any card)
local C_BG       = 0x0A0F10   -- near-black with a hint of teal
local C_BORDER   = 0x1E3038
local C_LABEL    = 0x4A7F8A   -- muted teal for labels
local C_VALUE    = 0xC8E0E4   -- high-contrast value text
local C_WARN     = 0xF0A020   -- amber for anomalies
local C_CRIT     = 0xE03030   -- red for critical
local C_OK       = 0x40C060   -- green for healthy values

-- FSM state → 4-char abbreviation
local FSM_ABBREV = {
  idle              = "IDLE",
  listening         = "LSTN",
  processing        = "PROC",
  recalling         = "RCLL",
  saving            = "SAVE",
  privacy           = "PRIV",
  error             = "ERR!",
  loading           = "LOAD",
  connected         = "CONN",
  disconnected      = "DISC",
}

-- Card type → short label
local CARD_ABBREV = {
  ReadyCard             = "RDY ",
  SavedMemoryCard       = "SAVE",
  QueryListeningCard    = "LSTN",
  LoadingCard           = "LOAD",
  ObjectRecallCard      = "OBJ ",
  CommitmentRecallCard  = "CMMT",
  ProactiveMemoryCard   = "PROA",
  PersonContextCard     = "PERS",
  PrivacyVeilCard     = "PRIV",
  ErrorCard             = "ERR!",
  LowConfidenceCard     = "LOWC",
  CommitmentDriftCard   = "DRFT",
  TimeScrubNodeCard     = "SCRB",
  DeviationAlertCard    = "DEVN",
}

-- ---------------------------------------------------------------------------
-- Module state
-- ---------------------------------------------------------------------------
local diag = {}

local _open       = false
local _verbosity  = V_NORMAL
local _last_touch = 0       -- ms of last toggle/cycle; drives TTL

-- Wired data sources (set by bind())
local _state_fn    = nil
local _queue_fn    = nil
local _renderer_fn = nil

-- FPS tracking
local _frame_times  = {}   -- ring of last FPS_WINDOW frame timestamps
local _fps_idx      = 0
local _fps_val      = 0.0

-- BLE counters
local _ble_rx_count = 0
local _ble_tx_count = 0
local _ble_last_rx  = ""
local _ble_last_tx  = ""

-- Frame counter for flicker effects
local _frame_n = 0

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------
local function _now_ms()
  if HAS_FRAME and frame.time then
    return math.floor(frame.time.utc() * 1000) % (2^31)
  end
  return math.floor(os.clock() * 1000)
end

local function _clamp(v,lo,hi) return math.max(lo, math.min(hi, v)) end
local function _floor(n) return math.floor(n + 0.5) end

local function _abbrev_state(s)
  if not s then return "----" end
  return FSM_ABBREV[s] or (s:sub(1,4):upper())
end

local function _abbrev_card(t)
  if not t then return "----" end
  return CARD_ABBREV[t] or (t:sub(1,4):upper())
end

local function _heap_kb()
  -- collectgarbage returns bytes on standard Lua; Frame may not support it
  local ok, val = pcall(collectgarbage, "count")
  if ok and type(val) == "number" then
    -- "count" returns KB already in Lua 5.x
    return string.format("%.0fK", val)
  end
  return "---"
end

-- ---------------------------------------------------------------------------
-- Drawing primitives
-- ---------------------------------------------------------------------------
local function _rect(x,y,w,h,color)
  if not HAS_FRAME then return end
  frame.display.rect(x,y,w,h,color,true)
end

local function _line(x0,y0,x1,y1,color)
  if not HAS_FRAME then return end
  frame.display.line(x0,y0,x1,y1,color)
end

local function _text(str,x,y,color)
  if not HAS_FRAME or str==nil or str=="" then return end
  frame.display.text(tostring(str),x,y,color)
end

-- Draw a small filled panel background
local function _panel_bg(x,y,w,h)
  _rect(x,y,w,h,C_BG)
  _line(x,y,x+w,y,C_BORDER)
  _line(x,y+h,x+w,y+h,C_BORDER)
  _line(x,y,x,y+h,C_BORDER)
  _line(x+w,y,x+w,y+h,C_BORDER)
end

-- Draw label + value on one line; value coloured by state
local function _kv(label,value,x,y,val_color)
  val_color = val_color or C_VALUE
  _text(label,x,y,C_LABEL)
  _text(value,x+_floor(#label*5)+2,y,val_color)
end

-- ---------------------------------------------------------------------------
-- Panel renderers
-- ---------------------------------------------------------------------------

-- TOP-LEFT: FSM state + card type
local function _panel_tl(px,py)
  local state_str  = _state_fn  and _state_fn()   or "?"
  local rinfo      = _renderer_fn and _renderer_fn() or {}
  local card_type  = rinfo.card_type or ""
  local phase      = rinfo.phase     or "-"

  local state_col = C_VALUE
  if state_str == "error" then state_col = C_CRIT
  elseif state_str == "privacy" then state_col = C_WARN end

  local w = 60; local h = LINE_H*2+6
  _panel_bg(px,py,w,h)
  _kv("FSM:",_abbrev_state(state_str), px+2,py+2, state_col)
  _kv("CRD:",_abbrev_card(card_type),  px+2,py+2+LINE_H, C_VALUE)
end

-- TOP-RIGHT: FPS + heap
local function _panel_tr(px,py)
  local fps_str  = string.format("%.0f",_fps_val)
  local heap_str = _heap_kb()

  local fps_col = C_OK
  if _fps_val < 15 then fps_col = C_CRIT
  elseif _fps_val < 18 then fps_col = C_WARN end

  local w = 56; local h = LINE_H*2+6
  local x = px - w
  _panel_bg(x,py,w,h)
  _kv("FPS:",fps_str,   x+2,py+2,       fps_col)
  _kv("MEM:",heap_str,  x+2,py+2+LINE_H,C_VALUE)
end

-- BOTTOM-LEFT: BLE rx/tx + last type
local function _panel_bl(px,py)
  local rx_str  = tostring(_ble_rx_count)
  local tx_str  = tostring(_ble_tx_count)
  local lrx_str = _ble_last_rx ~= "" and _ble_last_rx:sub(1,4) or "---"

  local w = 72; local h = LINE_H*3+6
  local y = py - h
  _panel_bg(px,y,w,h)
  _kv("RX: ",rx_str,   px+2,y+2,          C_VALUE)
  _kv("TX: ",tx_str,   px+2,y+2+LINE_H,   C_VALUE)
  _kv("LST:",lrx_str,  px+2,y+2+LINE_H*2, C_LABEL)
end

-- BOTTOM-RIGHT: queue depth
local function _panel_br(px,py)
  local qinfo = _queue_fn and _queue_fn() or {urgent=0,context=0,ambient=0,depth=0}
  local rinfo = _renderer_fn and _renderer_fn() or {phase="-",idle_t=0}

  local depth_col = C_OK
  if qinfo.depth >= 5 then depth_col = C_CRIT
  elseif qinfo.depth >= 3 then depth_col = C_WARN end

  local w = 68; local h = LINE_H*3+6
  local x = px - w; local y = py - h
  _panel_bg(x,y,w,h)
  _kv("Q: ",  string.format("%dU/%dC/%dA",qinfo.urgent,qinfo.context,qinfo.ambient),
      x+2,y+2, depth_col)
  _kv("PHS:", rinfo.phase:sub(1,4):upper(), x+2,y+2+LINE_H,   C_VALUE)
  _kv("IDL:", string.format("%dms",rinfo.idle_t or 0), x+2,y+2+LINE_H*2, C_LABEL)
end

-- MIDDLE (VERBOSE only): card fields
local function _panel_mid(cx, cy)
  local rinfo = _renderer_fn and _renderer_fn() or {}
  local card  = rinfo.card
  if not card then return end

  local fields = {}
  for k,v in pairs(card) do
    if type(v) ~= "table" and type(v) ~= "function" then
      fields[#fields+1] = string.format("%s=%s", tostring(k):sub(1,6), tostring(v):sub(1,8))
    end
  end
  table.sort(fields)

  local max_rows = 5
  local w = 128; local h = math.min(#fields,max_rows)*LINE_H + 6
  local x = cx - _floor(w/2); local y = cy - _floor(h/2)
  _panel_bg(x,y,w,h)
  for i=1,math.min(#fields,max_rows) do
    _text(fields[i], x+2, y+2+(i-1)*LINE_H, C_LABEL)
  end
end

-- TTL progress bar along the top edge (shows how long overlay stays open)
local function _ttl_bar(elapsed_ms)
  if not HAS_FRAME then return end
  local frac = 1.0 - _clamp(elapsed_ms / DIAG_TTL_MS, 0, 1)
  local bar_w = _floor(256 * frac)
  if bar_w < 1 then return end
  frame.display.line(0,0,bar_w,0,C_BORDER)
end

-- ---------------------------------------------------------------------------
-- Public API
-- ---------------------------------------------------------------------------

--- Bind live data source functions.  Call once at boot.
function diag.bind(state_fn, queue_fn, renderer_fn)
  _state_fn    = state_fn
  _queue_fn    = queue_fn
  _renderer_fn = renderer_fn
end

--- Toggle overlay open/closed.
function diag.toggle()
  _open = not _open
  _last_touch = _now_ms()
  -- Reset verbosity to NORMAL each time it opens
  if _open then _verbosity = V_NORMAL end
end

--- Cycle verbosity.  No-op when overlay is closed.
function diag.cycle()
  if not _open then return end
  _verbosity = (_verbosity % 3) + 1
  _last_touch = _now_ms()
end

--- Record an inbound BLE message type string.
function diag.ble_rx(msg_type)
  _ble_rx_count = _ble_rx_count + 1
  _ble_last_rx  = tostring(msg_type or "")
end

--- Record an outbound BLE message type string.
function diag.ble_tx(msg_type)
  _ble_tx_count = _ble_tx_count + 1
  _ble_last_tx  = tostring(msg_type or "")
end

--- Must be called once per main-loop tick to maintain FPS counter.
function diag.frame_tick()
  _frame_n = _frame_n + 1
  local now = _now_ms()
  _frame_times[(_fps_idx % FPS_WINDOW) + 1] = now
  _fps_idx = _fps_idx + 1

  if _fps_idx >= FPS_WINDOW then
    -- oldest sample is at the slot we're about to overwrite
    local oldest_slot = (_fps_idx % FPS_WINDOW) + 1
    local oldest = _frame_times[oldest_slot]
    if oldest and oldest > 0 then
      local elapsed = now - oldest
      if elapsed > 0 then
        _fps_val = (FPS_WINDOW - 1) / (elapsed / 1000.0)
      end
    end
  end
end

--- Returns true when overlay is currently visible.
function diag.is_open()
  return _open
end

--- Composite diagnostics overlay onto the current frame buffer.
--- Call after renderer.tick() so overlay is always on top.
function diag.tick()
  -- Always advance frame tick for FPS tracking
  diag.frame_tick()

  if not _open then return end

  -- Auto-hide after TTL
  local now     = _now_ms()
  local elapsed = now - _last_touch
  if elapsed >= DIAG_TTL_MS then
    _open = false
    return
  end

  -- Draw four corner panels
  local pad = CORNER_PAD
  local W,H = 256,256   -- Frame display dimensions

  _panel_tl(pad, pad)       -- top-left
  _panel_tr(W-pad, pad)     -- top-right  (x is right edge)
  _panel_bl(pad, H-pad)     -- bottom-left (y is bottom edge)
  _panel_br(W-pad, H-pad)   -- bottom-right

  if _verbosity == V_VERBOSE then
    _panel_mid(W/2, H/2)
  end

  -- TTL drain bar
  _ttl_bar(elapsed)

  -- Verbosity indicator dot row (bottom center)
  for i=1,3 do
    local dot_x = _floor(W/2) - 8 + (i-1)*8
    local dot_col = (i == _verbosity) and C_VALUE or C_BORDER
    if HAS_FRAME then
      frame.display.circle(dot_x, H-6, 2, dot_col, true)
    end
  end
end

-- Expose level constants for tests
diag.V_MINIMAL = V_MINIMAL
diag.V_NORMAL  = V_NORMAL
diag.V_VERBOSE = V_VERBOSE
diag.DIAG_TTL_MS = DIAG_TTL_MS

return diag
