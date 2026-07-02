--- display/horizon.lua
--- The Horizon: Meridian's persistent rim instrument
--- (docs/cinema_v2/horizon.md). The resting display is the wearer's day —
--- one mark per remembered event at its time-angle on a 12h dial, now at
--- 12 o'clock, past clockwise, promises counterclockwise, a permanent
--- seam at the bottom antipode. This module is a dumb plotter: angles
--- arrive precomputed in {t="horizon"} frames (ble/message_types.lua
--- HORIZON); the device does no clock math, so skew cannot shear the dial.
---
--- Public API:
---   horizon.on_frame(msg)                  BLE handler ({t="horizon"})
---   horizon.draw(opts)                     render one pass (no clear/show)
---     opts = { now_ms=, dim=bool (dream light: memory marks -> floor),
---              focus=bool (one tier down under a focused card) }
---   horizon.set_highlight(deg, now_ms)     provenance brighten (anchor echo)
---   horizon.pulse_mark(deg, now_ms)        arrival pulse after recession
---   horizon.marks() / horizon.is_paused()  state hooks for tests
---   horizon.reset()                        test hook

local A = require("display.animations")
local P = require("display.palette")
local E = require("lib.easing")

local HAS_FRAME = (type(_G.frame) == "table")

local M = {}

local CX, CY = 128, 128

-- Frame state (last valid {t="horizon"} payload)
local _marks         = {}    -- { {deg=, kind=, state=, luma=}, ... }
local _seq           = -1
local _paused        = false
local _last_frame_ms = nil
local _highlight     = nil   -- { deg=, until_ms= }
local _scrub         = nil   -- { deg= } (Yesterlight detached notch)
local _pulse         = nil   -- { deg=, until_ms= }

local KIND_MEMORY, KIND_PROMISE, KIND_PERSON, KIND_ELDER, KIND_FUTURE_CAP =
  1, 2, 3, 4, 5
local KIND_PREMONITION = 6   -- future ghost (shimmers, never breathes loud)

local function fl(n) return math.floor(n + 0.5) end
local function polar(r, deg)
  local rad = math.rad(deg)
  return CX + r * math.cos(rad), CY + r * math.sin(rad)
end

local function radial_tick(deg, r0, r1, color, width)
  if not HAS_FRAME then return end
  local x0, y0 = polar(r0, deg)
  local x1, y1 = polar(r1, deg)
  frame.display.line(fl(x0), fl(y0), fl(x1), fl(y1), color)
  if width and width >= 2 then
    local rad = math.rad(deg)
    local px, py = -math.sin(rad), math.cos(rad)
    frame.display.line(fl(x0 + px), fl(y0 + py), fl(x1 + px), fl(y1 + py), color)
  end
end

local function arc(r, a0, a1, color, steps)
  if not HAS_FRAME or r <= 0 then return end
  steps = steps or 48
  local sweep = a1 - a0
  local x0, y0 = polar(r, a0)
  for i = 1, steps do
    local x1, y1 = polar(r, a0 + sweep * i / steps)
    frame.display.line(fl(x0), fl(y0), fl(x1), fl(y1), color)
    x0, y0 = x1, y1
  end
end

-- ---------------------------------------------------------------------------
-- Frame ingestion: {t="horizon", seq=n, paused=0|1, v={dd,code, dd,code,…}}
-- code = kind*100 + state*10 + luma (docs/cinema_v2/horizon_frame.md).
-- Malformed frames are dropped whole; the previous day never blanks.
-- ---------------------------------------------------------------------------
function M.on_frame(msg, now_ms)
  if type(msg) ~= "table" then return false end
  local v = msg.v
  if v ~= nil and type(v) ~= "table" then return false end
  v = v or {}
  if #v % 2 ~= 0 then return false end
  local seq = tonumber(msg.seq) or 0
  if seq <= _seq and _seq >= 0 then return false end   -- stale/out-of-order

  local marks = {}
  for i = 1, #v, 2 do
    local dd   = tonumber(v[i])
    local code = tonumber(v[i + 1])
    if not dd or not code then return false end
    local kind  = math.floor(code / 100)
    local state = math.floor(code / 10) % 10
    local luma  = code % 10
    if kind < KIND_MEMORY or kind > KIND_PREMONITION or luma > 2 then
      return false
    end
    if #marks >= A.MER_MARKS_MAX then break end
    marks[#marks + 1] = { deg = dd / 10, kind = kind, state = state, luma = luma }
  end

  _marks         = marks
  _seq           = seq
  _paused        = (msg.paused == 1 or msg.paused == true)
  _last_frame_ms = now_ms or M._now_ms()
  return true
end

function M._now_ms()
  return math.floor(os.clock() * 1000)
end

-- ---------------------------------------------------------------------------
-- Rendering
-- ---------------------------------------------------------------------------

--- The rim track: 1px ghost arc across the active window; its absence at
--- the bottom is the seam (past ends, future begins).
local function draw_track()
  arc(A.MER_TRACK_R, A.MER_SEAM_TO_DEG, 360 + A.MER_SEAM_FROM_DEG,
      P.border_subtle, 72)
end

local MEM_STYLE = {
  [0] = { color = P.border_subtle },
  [1] = { color = P.accent_memory_dim },
  [2] = { color = P.accent_memory },
}

local PROMISE_STATE = {
  [1] = { r = nil, dot = 2, color = P.confidence_low, stem = 0 },  -- blooming
  [2] = { r = nil, dot = 3, color = P.confidence_low, stem = 0 },  -- healthy
  [3] = { r = nil, dot = 3, color = P.warning_amber,  stem = 3 },  -- drifting
  [4] = { r = "slip", dot = 3, color = P.warning_amber, stem = 0 }, -- cracking
  [5] = { r = "slip", dot = 0, color = P.status_paused, stem = 0 }, -- shattered
}

local function draw_memory(mk, tier_drop, extra_len)
  local luma = math.max(0, (mk.luma or 1) - (tier_drop or 0))
  local st = MEM_STYLE[luma]
  local len = A.MER_MARK_LEN[luma] + (extra_len or 0)
  radial_tick(mk.deg, A.MER_MARK_BASE_R, A.MER_MARK_BASE_R + len, st.color)
end

local function draw_person(mk, tier_drop)
  local luma  = math.max(0, (mk.luma or 2) - (tier_drop or 0))
  local color = luma >= 2 and P.accent_memory
             or luma >= 1 and P.accent_memory_dim
             or P.border_subtle
  radial_tick(mk.deg, A.MER_MARK_BASE_R, A.MER_MARK_BASE_R + 5, color)
  if HAS_FRAME then
    local dx, dy = polar(110, mk.deg)
    frame.display.circle(fl(dx), fl(dy), 2, color, false)
  end
end

local function draw_promise(mk, stack)
  local st = PROMISE_STATE[mk.state or 2] or PROMISE_STATE[2]
  local base_r = (st.r == "slip") and A.MER_PROMISE_SLIP_R or A.MER_PROMISE_R
  local r = base_r - (stack or 0) * A.MER_PROMISE_STACK_PX
  if (mk.state or 2) == 5 then
    -- shattered: the fractured tick — two segments, 3px gap
    radial_tick(mk.deg, r - 7, r - 2, st.color, 2)
    radial_tick(mk.deg, r + 1, r + 6, st.color, 2)
  elseif HAS_FRAME then
    local x, y = polar(r, mk.deg)
    local dot = (stack or 0) > 0 and math.max(2, st.dot - 1) or st.dot
    frame.display.circle(fl(x), fl(y), dot, st.color, true)
    if st.stem > 0 then
      radial_tick(mk.deg, r - st.stem - 3, r - 3, st.color)
    end
  end
end

--- A future ghost: a dim dot ahead of now that shimmers on a slow
--- phase (reduce_motion: a static dim dot — probability stays visible,
--- the flicker goes). Never brighter than a real luma-1 mark.
local function draw_premonition(mk, now_ms, reduce_motion)
  local visible = true
  if not reduce_motion then
    local phase = ((now_ms or 0) + fl(mk.deg * 37)) % 1400
    visible = phase < 980   -- ~70% duty shimmer, desynced per mark
  end
  if visible then
    local x, y = polar(A.MER_MARK_BASE_R, mk.deg)
    if HAS_FRAME then
      frame.display.circle(fl(x), fl(y), 1, P.text_ghost, true)
    end
  end
end

local function draw_notch(now_ms, reduce_motion)
  local len
  if reduce_motion then
    len = A.MER_NOW_LEN_MIN + 2  -- static mid-length tick, info preserved
  else
    local phase = ((now_ms or 0) % A.BREATHE_CYCLE_MS) / A.BREATHE_CYCLE_MS
    local breathe = E.in_out_sine((math.sin(phase * 2 * math.pi) + 1) / 2)
    len = A.MER_NOW_LEN_MIN + (A.MER_NOW_LEN_MAX - A.MER_NOW_LEN_MIN) * breathe
  end
  local color = _paused and P.status_paused or P.accent_memory
  radial_tick(A.MER_NOW_DEG, 96, fl(96 + len), color, 2)
end

--- One full horizon pass. Never clears, never shows — the caller owns
--- the frame (renderer idle, card backdrop, dream terrain).
function M.draw(opts)
  opts = opts or {}
  local now = opts.now_ms or M._now_ms()

  draw_track()

  -- staleness: no frame for MER_STALE_MS -> marks drop one luma tier
  -- (device liveness stays on the notch, memory-link health on the marks)
  local tier_drop = 0
  if _last_frame_ms and (now - _last_frame_ms) > A.MER_STALE_MS then
    tier_drop = tier_drop + 1
  end
  if opts.focus then tier_drop = tier_drop + 1 end

  -- memory-mark merge: marks within MER_MARK_MERGE_DEG collapse into one
  -- longer tick (density encoding); promises never merge (each is an
  -- obligation) — they stack radially instead.
  local drawn_deg = {}       -- memory merge accumulator: deg -> extra_len
  local promise_stack = {}   -- rounded deg -> count
  local paused = _paused

  for _, mk in ipairs(paused and {} or _marks) do
    if mk.kind == KIND_MEMORY then
      local merged = false
      for deg, _ in pairs(drawn_deg) do
        if math.abs(deg - mk.deg) <= A.MER_MARK_MERGE_DEG then
          drawn_deg[deg] = math.min(drawn_deg[deg] + 2, 8)
          merged = true
          break
        end
      end
      if not merged then drawn_deg[mk.deg] = 0 end
    end
  end

  for _, mk in ipairs(paused and {} or _marks) do
    if mk.kind == KIND_MEMORY then
      local extra = drawn_deg[mk.deg]
      if extra ~= nil then   -- cluster representative
        local dim_mk = mk
        if opts.dim then
          dim_mk = { deg = mk.deg, kind = mk.kind, luma = 0 }
          draw_memory(dim_mk, 0, extra)
        else
          draw_memory(mk, tier_drop, extra)
        end
        drawn_deg[mk.deg] = nil   -- draw each cluster once
      end
    elseif mk.kind == KIND_PERSON then
      if opts.dim then
        draw_person({ deg = mk.deg, kind = mk.kind, luma = 0 }, 0)
      else
        draw_person(mk, tier_drop)
      end
    elseif mk.kind == KIND_PROMISE then
      -- promises never dim (they don't sleep) and never tier-drop
      local key = fl(mk.deg / A.MER_MARK_MERGE_DEG)
      local stack = promise_stack[key] or 0
      promise_stack[key] = stack + 1
      draw_promise(mk, math.min(stack, 2))
    elseif mk.kind == KIND_PREMONITION then
      -- future ghosts stay in dream light too: probability is weather
      draw_premonition(mk, now, opts.reduce_motion)
    elseif mk.kind == KIND_ELDER then
      radial_tick(A.MER_ELDER_DEG, A.MER_MARK_BASE_R, A.MER_MARK_BASE_R + 4,
                  P.text_ghost)
    elseif mk.kind == KIND_FUTURE_CAP then
      if HAS_FRAME then
        local x, y = polar(A.MER_PROMISE_R, A.MER_FUTURE_CAP_DEG)
        frame.display.circle(fl(x), fl(y), 2, P.text_ghost, true)
      end
    end
  end

  -- provenance highlight (anchor echo): full-tier overdraw at the angle
  if _highlight and now <= _highlight.until_ms then
    draw_memory({ deg = _highlight.deg, kind = KIND_MEMORY, luma = 2 }, 0, 3)
  elseif _highlight then
    _highlight = nil
  end

  -- arrival pulse after a recession lands
  if _pulse and now <= _pulse.until_ms then
    draw_memory({ deg = _pulse.deg, kind = KIND_MEMORY, luma = 2 }, 0, 3)
  elseif _pulse then
    _pulse = nil
  end

  draw_notch(now, opts.reduce_motion)

  -- Yesterlight: the visited hour gets its own still notch, in the
  -- paused hue — the past does not breathe
  if _scrub then
    radial_tick(_scrub.deg, 96, fl(96 + A.MER_NOW_LEN_MIN + 2),
                P.status_paused, 2)
  end
end

--- Yesterlight ({t="yesterlight"}): while active the now-notch detaches
--- and a scrub notch marks the visited hour; an optional echo brightens
--- the anchor living at that hour (same provenance path as set_highlight).
function M.on_yesterlight(msg, now_ms)
  if not msg then return end
  if (msg.active or 0) == 1 and msg.notch_dd then
    _scrub = { deg = msg.notch_dd / 10 }
    if msg.echo_dd then
      M.set_highlight(msg.echo_dd / 10, now_ms)
    end
  else
    _scrub = nil
  end
end

function M.scrub() return _scrub end

function M.set_highlight(deg, now_ms)
  _highlight = { deg = deg, until_ms = (now_ms or M._now_ms()) + A.MER_HIGHLIGHT_MS }
end

function M.pulse_mark(deg, now_ms)
  _pulse = { deg = deg, until_ms = (now_ms or M._now_ms()) + A.MER_ARRIVAL_PULSE_MS }
end

-- ---------------------------------------------------------------------------
-- State hooks (tests / diagnostics)
-- ---------------------------------------------------------------------------
function M.marks() return _marks end
function M.is_paused() return _paused end
function M.seq() return _seq end
function M.last_frame_ms() return _last_frame_ms end

function M.reset()
  _marks, _seq, _paused, _last_frame_ms = {}, -1, false, nil
  _highlight, _pulse, _scrub = nil, nil, nil
end

return M
