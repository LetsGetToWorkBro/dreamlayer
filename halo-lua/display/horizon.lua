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

local A  = require("display.animations")
local P  = require("display.palette")
local E  = require("lib.easing")
local PT = require("display.particles")

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
local _shatter       = nil   -- { deg=, until_ms= } (impact ring, Lumen)
local _reveal_t0     = nil   -- wake reveal start (Lumen)

local KIND_MEMORY, KIND_PROMISE, KIND_PERSON, KIND_ELDER, KIND_FUTURE_CAP =
  1, 2, 3, 4, 5
local KIND_PREMONITION = 6   -- future ghost (shimmers, never breathes loud)

-- Meridian Lumen slot aliases (docs/cinema_v2/lumen.md). The aurora bands
-- alias the dream-only slots (sky 1 / drift 3 / drift 4) — mode-exclusive,
-- the same aliasing rule the v1 prism fringes used — and the premonition
-- shimmer aliases energy (2). Base hexes sit one LSB off their visual
-- twins (border_subtle / text_ghost) so each band maps to its own slot on
-- the indexed panel without capturing the static tokens (the base-hex
-- conflation documented in docs/CINEMA_V2_RISKS.md).
P.reserve_dynamic("aurora_a", A.AURORA_BASE_A, 3)
P.reserve_dynamic("aurora_b", A.AURORA_BASE_B, 4)
P.reserve_dynamic("aurora_c", A.AURORA_BASE_C, 1)
P.reserve_dynamic("premo",    A.PREMO_BASE,    2)

-- Parallax (RIM depth): the whole instrument shifts rigidly by the offset
-- the renderer passes into draw(opts.ox/oy) — the day ring reads as
-- anchored in the world, one tier behind the focused content.
local _ox, _oy = 0, 0

local function fl(n) return math.floor(n + 0.5) end
local function polar(r, deg)
  local rad = math.rad(deg)
  return CX + _ox + r * math.cos(rad), CY + _oy + r * math.sin(rad)
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

  -- Lumen: the moment a promise crosses INTO shattered (state 5), it
  -- physically breaks — six shards fall inward off the rim and a short
  -- impact ring marks the break. Detected as a state transition between
  -- consecutive frames, so a promise that arrives already shattered (or
  -- a reconnect replay) never re-breaks. reduce_motion: the shards
  -- module no-ops and the ring is skipped at draw; the drifting-halves
  -- idle pose is unchanged either way.
  local now = now_ms or M._now_ms()
  local old_state = {}
  for _, mk in ipairs(_marks) do
    if mk.kind == KIND_PROMISE then
      old_state[fl(mk.deg * 10)] = mk.state
    end
  end
  for _, mk in ipairs(marks) do
    if mk.kind == KIND_PROMISE and mk.state == 5 then
      local prev = old_state[fl(mk.deg * 10)]
      if prev and prev ~= 5 then
        PT.shards(mk.deg, A.SHARD_N, { t0 = now, seed = 11 })
        _shatter = { deg = mk.deg, until_ms = now + A.SHATTER_FLASH_MS }
      end
    end
  end

  _marks         = marks
  _seq           = seq
  _paused        = (msg.paused == 1 or msg.paused == true)
  _last_frame_ms = now
  return true
end

--- Wake (Lumen): the horizon draws on radially from the now-notch over
--- WAKE_REVEAL_MS — the instrument assembles instead of appearing.
--- Pure draw-order gating; no new geometry.
function M.wake(now_ms)
  _reveal_t0 = now_ms or M._now_ms()
end

--- Angular reach of the wake reveal at `now` (nil = fully revealed).
--- Both dial arms sweep out from the notch to the ±150-degree caps.
local function reveal_reach(now, reduce_motion)
  if not _reveal_t0 or reduce_motion then return nil end
  local t = (now - _reveal_t0) / A.WAKE_REVEAL_MS
  if t >= 1 then
    _reveal_t0 = nil
    return nil
  end
  if t < 0 then return 0 end
  return E.out_cubic(t) * (A.MER_WINDOW_HOURS * A.MER_DEG_PER_HOUR)
end

--- Angular distance from the now-notch, measured around the dial.
local function notch_dist(deg)
  return math.abs(((deg - A.MER_NOW_DEG + 180) % 360) - 180)
end

function M._now_ms()
  return math.floor(os.clock() * 1000)
end

-- ---------------------------------------------------------------------------
-- Rendering
-- ---------------------------------------------------------------------------

--- The rim track: 1px ghost arc across the active window; its absence at
--- the bottom is the seam (past ends, future begins).
--- Aurora (Lumen): in pure idle the 72 segments band across the three
--- aurora slots whose lumas the palette animator cycles — light flows
--- slowly along the day-ring with ZERO new geometry. Focused/dim/
--- reduce_motion frames draw the static ghost track, unchanged.
local AURORA_BANDS = { A.AURORA_BASE_A, A.AURORA_BASE_B, A.AURORA_BASE_C }

local function draw_track(aurora, reach)
  local a0 = A.MER_SEAM_TO_DEG
  local a1 = 360 + A.MER_SEAM_FROM_DEG
  if not aurora and not reach then
    arc(A.MER_TRACK_R, a0, a1, P.border_subtle, 72)
    return
  end
  local steps = 72
  local sweep = a1 - a0
  local x0, y0 = polar(A.MER_TRACK_R, a0)
  for i = 1, steps do
    local mid = a0 + sweep * (i - 0.5) / steps
    local x1, y1 = polar(A.MER_TRACK_R, a0 + sweep * i / steps)
    if HAS_FRAME and (not reach or notch_dist(mid) <= reach) then
      frame.display.line(fl(x0), fl(y0), fl(x1), fl(y1),
                         aurora and AURORA_BANDS[(i - 1) % 3 + 1]
                                or  P.border_subtle)
    end
    x0, y0 = x1, y1
  end
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

-- A commitment is a physics object: it does not merely change colour
-- between states, it *behaves*. Blooming breathes, cracking trembles,
-- shattered throws shards that drift apart. reduce_motion freezes each to
-- its still, information-preserving pose. Motion is driven by now_ms and
-- the mark's own angle, so every promise animates on its own phase.
local function draw_promise(mk, stack, now_ms, reduce_motion)
  local state = mk.state or 2
  local st = PROMISE_STATE[state] or PROMISE_STATE[2]
  local base_r = (st.r == "slip") and A.MER_PROMISE_SLIP_R or A.MER_PROMISE_R
  local r = base_r - (stack or 0) * A.MER_PROMISE_STACK_PX
  now_ms = now_ms or 0
  local seed = fl(mk.deg * 53)

  if state == 5 then
    -- shattered: a fractured tick whose two halves drift apart, plus two
    -- shards thrown off the break. Still (reduce_motion) = a clean gap.
    local spread = 0
    if not reduce_motion then
      local ph = ((now_ms + seed) % 2600) / 2600     -- slow, ~2.6s
      spread = E.in_out_sine(ph) * 2                  -- 0..2px of separation
    end
    radial_tick(mk.deg, r - 7 - spread, r - 2 - spread, st.color, 2)
    radial_tick(mk.deg, r + 1 + spread, r + 6 + spread, st.color, 2)
    if HAS_FRAME and not reduce_motion and spread > 0.8 then
      local rad = math.rad(mk.deg)
      local px, py = -math.sin(rad), math.cos(rad)
      local sx, sy = polar(r + 8, mk.deg)
      frame.display.circle(fl(sx + px * spread), fl(sy + py * spread), 1,
                           st.color, true)
      frame.display.circle(fl(sx - px * spread), fl(sy - py * spread), 1,
                           st.color, true)
    end
    return
  end

  if not HAS_FRAME then return end
  local dot = (stack or 0) > 0 and math.max(2, st.dot - 1) or st.dot
  local deg = mk.deg
  local rr = r

  if state == 1 and not reduce_motion then
    -- blooming: a gentle breath, the object drawing sap
    local ph = ((now_ms + seed) % A.BREATHE_CYCLE_MS) / A.BREATHE_CYCLE_MS
    local grow = E.in_out_sine((math.sin(ph * 2 * math.pi) + 1) / 2)
    dot = dot + fl(grow * 1.5)                         -- 2 -> ~3.5px
  elseif state == 4 and not reduce_motion then
    -- cracking: a fast, small radial tremor — the object under stress
    local ph = ((now_ms + seed) % 220) / 220
    rr = r + (E.in_out_sine(ph) - 0.5) * 2            -- ±1px jitter
  end

  local x, y = polar(rr, deg)
  frame.display.circle(fl(x), fl(y), dot, st.color, true)
  if st.stem > 0 then
    radial_tick(deg, rr - st.stem - 3, rr - 3, st.color)
  end
  -- cracking also grows a hairline fissure stem toward the rim
  if state == 4 then
    radial_tick(deg, rr + 3, rr + 6, st.color)
  end
end

--- A future ghost: a dim dot ahead of now. Lumen: the v1 70%-duty
--- visibility blink — the codebase's one true temporal dither — is
--- killed; the dot is always drawn, in the `premo` slot whose luma the
--- palette animator breathes (renderer's premonition_shimmer program).
--- One shared phase: future ghosts are one ambient layer, like ghost
--- text. reduce_motion: the program holds base — a static dim dot,
--- probability visible, nothing flickers. Never brighter than the v1
--- static dot (SHIMMER_Y_HI = the ghost base luma; the breath dims).
local function draw_premonition(mk)
  local x, y = polar(A.MER_MARK_BASE_R, mk.deg)
  if HAS_FRAME then
    frame.display.circle(fl(x), fl(y), 1, P.dynamic_color("premo"), true)
  end
end

local function draw_notch(now_ms, reduce_motion)
  local len
  if reduce_motion then
    len = A.MER_NOW_LEN_MIN + 2  -- static mid-length tick, info preserved
  else
    -- Lumen heartbeat: a fast spring rise (the beat) then a long soft
    -- decay — alive, not metronomic. Same cycle, same length range.
    local phase = ((now_ms or 0) % A.BREATHE_CYCLE_MS) / A.BREATHE_CYCLE_MS
    local beat
    if phase < A.HEARTBEAT_RISE_FRAC then
      beat = E.spring(phase / A.HEARTBEAT_RISE_FRAC,
                      A.SPRING_ZETA_SNAPPY, A.SPRING_OMEGA)
    else
      beat = 1 - E.in_out_sine((phase - A.HEARTBEAT_RISE_FRAC)
                               / (1 - A.HEARTBEAT_RISE_FRAC))
    end
    len = A.MER_NOW_LEN_MIN + (A.MER_NOW_LEN_MAX - A.MER_NOW_LEN_MIN) * beat
  end
  local color = _paused and P.status_paused or P.accent_memory
  radial_tick(A.MER_NOW_DEG, 96, fl(96 + len), color, 2)
  -- Solid: one bloom dot at the tip — the heartbeat catches the light
  if HAS_FRAME then
    local bx, by = polar(96 + len + 2, A.MER_NOW_DEG)
    frame.display.circle(fl(bx), fl(by), 2,
                         _paused and P.status_paused or P.accent_memory_dim,
                         false)
  end
end

--- One full horizon pass. Never clears, never shows — the caller owns
--- the frame (renderer idle, card backdrop, dream terrain).
function M.draw(opts)
  opts = opts or {}
  local now = opts.now_ms or M._now_ms()
  _ox, _oy = opts.ox or 0, opts.oy or 0

  -- wake reveal (Lumen): while active, only geometry inside the swept
  -- span draws — the day assembles outward from the notch
  local reach = reveal_reach(now, opts.reduce_motion)

  -- aurora light only in pure idle: focused/dim frames keep the static
  -- ghost track, and reduce_motion is pixel-identical to the pre-Lumen
  -- horizon (base hexes differ from border_subtle by one invisible LSB,
  -- so even the banded track only moves when the animator runs)
  draw_track(opts.aurora and not opts.reduce_motion
             and not opts.dim and not opts.focus, reach)

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
    if reach and notch_dist(mk.deg) > reach then
      -- outside the wake sweep: this mark hasn't been revealed yet
    elseif mk.kind == KIND_MEMORY then
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
      draw_promise(mk, math.min(stack, 2), now, opts.reduce_motion)
    elseif mk.kind == KIND_PREMONITION then
      -- future ghosts stay in dream light too: probability is weather
      draw_premonition(mk)
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

  -- arrival pulse after a recession lands. Lumen: the pulse throws two
  -- ghost echoes that ripple outward and fade as the memory settles into
  -- its place on the day (reduce_motion: the plain brightened mark).
  if _pulse and now <= _pulse.until_ms then
    draw_memory({ deg = _pulse.deg, kind = KIND_MEMORY, luma = 2 }, 0, 3)
    if HAS_FRAME and not opts.reduce_motion then
      -- the echoes trail inward, along the path the content flew home on,
      -- and collapse into the mark as the pulse ends (never past r=112)
      local age = 1 - (_pulse.until_ms - now) / A.MER_ARRIVAL_PULSE_MS
      local e1x, e1y = polar(A.MER_MARK_BASE_R - 10 + 6 * age, _pulse.deg)
      frame.display.circle(fl(e1x), fl(e1y), 1, P.text_ghost, true)
      if age < 0.6 then
        local e2x, e2y = polar(A.MER_MARK_BASE_R - 17 + 8 * age, _pulse.deg)
        frame.display.circle(fl(e2x), fl(e2y), 1, P.border_subtle, true)
      end
    end
  elseif _pulse then
    _pulse = nil
  end

  -- shatter impact (Lumen): a short ring blooms off the break while the
  -- shards (particles, ticked by the renderer) fall inward
  if _shatter and now <= _shatter.until_ms then
    if HAS_FRAME and not opts.reduce_motion then
      local st = 1 - (_shatter.until_ms - now) / A.SHATTER_FLASH_MS
      local sx, sy = polar(A.MER_PROMISE_SLIP_R, _shatter.deg)
      frame.display.circle(fl(sx), fl(sy), fl(3 + 9 * st),
                           P.warning_amber, false)
    end
  elseif _shatter then
    _shatter = nil
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
  _shatter, _reveal_t0 = nil, nil
end

return M
