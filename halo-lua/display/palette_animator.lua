--- display/palette_animator.lua
--- Meridian Lumen: the scheduler that makes light itself the animation
--- medium (docs/cinema_v2/lumen.md). Where palette_cycle.lua is Dream
--- Mode's chroma engine (slash-instance sky slots), this is Memory
--- Mode's: registered *programs* animate leased dynamic-slot lumas every
--- renderer tick — flowing light over already-drawn geometry, zero
--- geometry cost, no BLE.
---
--- Programs (all pure functions of now_ms — deterministic, golden-safe):
---   wave   { names, period_ms, y_amp }        traveling luma wave across
---                                             the named slots (aurora)
---   shimmer{ name, period_ms, y_lo, y_hi,     desynced luma breath
---            phase_ms }                       (premonitions — replaces
---                                             the v1 duty-cycle blink)
---   flash  { name, t0, dur_ms, y_hi }         one-shot luma spike decaying
---                                             to base; auto-stops
---   sweep  { names, t0, dur_ms, y_amp }       one bright glint traveling
---                                             across the named slots once
---                                             (specular); auto-stops
---   fade   { names, t0, dur_ms, target,       scene fade: scales every
---            reverse }                        named slot's base luma
---                                             (dream door, privacy slam)
---
--- Contract:
---   * every program leases its slots (palette.lease) under its own id;
---     a program whose lease is refused does not run — one live writer
---     per slot, structurally.
---   * hard budget: at most animations.PAL_WRITES_MAX assign calls per
---     tick; programs beyond budget skip a tick (they are ambient by
---     definition, so a skipped tick is invisible).
---   * reduce_motion: every program holds its still pose (wave/shimmer:
---     base arrangement; flash/sweep: base; fade: the target level —
---     the light level is information, the motion is not).
---
--- Public API:
---   PA.run(id, spec) -> bool     register/replace a program (leases slots)
---   PA.stop(id)                  remove a program (releases + restores)
---   PA.stop_all()
---   PA.active(id) -> bool
---   PA.tick(now_ms, reduce_motion)
---   PA.writes_last_tick() -> n   diagnostics/budget assertion hook

local A = require("display.animations")
local P = require("display.palette")

local M = {}

local _programs = {}   -- id -> spec (validated, with cached base lumas)
local _order    = {}   -- ids in registration order (deterministic ticks)
local _writes   = 0

local function clamp1023(v)
  if v < 0 then return 0 elseif v > 1023 then return 1023 end
  return v
end

local function base_y(name)
  local y = P.hex_to_ycbcr(P.dynamic_color(name))
  return y
end

local function names_of(spec)
  if spec.names then return spec.names end
  return { spec.name }
end

--- Register (or replace) program `id`. Leases every slot the program
--- names; on any refused lease the whole program is rolled back and
--- run() returns false — partial programs never run.
function M.run(id, spec)
  if not id or type(spec) ~= "table" or not spec.kind then return false end
  M.stop(id)
  for _, name in ipairs(names_of(spec)) do
    if not P.lease(name, id) then
      P.release(id)
      return false
    end
  end
  -- cache base lumas once (hex->YCbCr math off the hot path)
  spec._base = {}
  for i, name in ipairs(names_of(spec)) do
    spec._base[i] = base_y(name)
  end
  _programs[id] = spec
  _order[#_order + 1] = id
  return true
end

function M.stop(id)
  if not _programs[id] then return end
  _programs[id] = nil
  for i = #_order, 1, -1 do
    if _order[i] == id then table.remove(_order, i) end
  end
  P.release(id)   -- restores base colors
end

function M.stop_all()
  for i = #_order, 1, -1 do
    M.stop(_order[i])
  end
end

function M.active(id)
  return _programs[id] ~= nil
end

-- ---------------------------------------------------------------------------
-- Per-kind evaluation: returns the target luma for slot index i (1-based)
-- at now_ms, or nil for "no write this tick". `done` flags auto-stop.
-- ---------------------------------------------------------------------------
local function eval(spec, i, n, now_ms, reduce_motion)
  local base = spec._base[i]

  if spec.kind == "wave" then
    if reduce_motion then return base end
    local period = spec.period_ms or A.AURORA_PERIOD_MS
    local amp    = spec.y_amp or A.AURORA_Y_AMP
    local phase  = (now_ms % period) / period
    return base + amp * math.sin(2 * math.pi * (phase + (i - 1) / n))

  elseif spec.kind == "shimmer" then
    if reduce_motion then return base end
    local period = spec.period_ms or A.SHIMMER_PERIOD_MS
    local lo     = spec.y_lo or A.SHIMMER_Y_LO
    local hi     = spec.y_hi or A.SHIMMER_Y_HI
    local phase  = ((now_ms + (spec.phase_ms or 0)) % period) / period
    local s      = (math.sin(2 * math.pi * phase) + 1) / 2
    return lo + (hi - lo) * s

  elseif spec.kind == "flash" then
    local t = (now_ms - (spec.t0 or 0)) / (spec.dur_ms or A.SHATTER_FLASH_MS)
    if reduce_motion or t >= 1 then
      spec._done = true
      return base
    end
    if t < 0 then return nil end
    return base + ((spec.y_hi or 900) - base) * (1 - t)

  elseif spec.kind == "sweep" then
    local t = (now_ms - (spec.t0 or 0)) / (spec.dur_ms or A.SPEC_SWEEP_MS)
    if reduce_motion or t >= 1 then
      spec._done = true
      return base
    end
    if t < 0 then return nil end
    -- one glint travels across the slots; each slot brightens as the
    -- glint passes its position, width one slot
    local pos  = t * n
    local dist = math.abs((i - 0.5) - pos)
    local glow = math.max(0, 1 - dist)
    return base + (spec.y_amp or 360) * glow

  elseif spec.kind == "fade" then
    local t = (now_ms - (spec.t0 or 0)) / (spec.dur_ms or A.MER_DREAM_ENTER_MS)
    local target = spec.target or 0.3
    local f
    if reduce_motion then
      f = spec.reverse and 1.0 or target
    elseif t <= 0 then
      f = spec.reverse and target or 1.0
    elseif t >= 1 then
      f = spec.reverse and 1.0 or target
      if spec.reverse then spec._done = true end
    else
      f = spec.reverse and (target + (1 - target) * t)
                        or (1 - (1 - target) * t)
    end
    return base * f
  end

  return nil
end

--- Advance every program one tick. Budgeted: at most PAL_WRITES_MAX
--- assign calls; later programs skip a tick when the budget is spent.
function M.tick(now_ms, reduce_motion)
  _writes = 0
  local finished = nil
  for _, id in ipairs(_order) do
    local spec = _programs[id]
    if spec then
      local names = names_of(spec)
      local n = #names
      for i = 1, n do
        if _writes >= A.PAL_WRITES_MAX then break end
        local y = eval(spec, i, n, now_ms, reduce_motion)
        if y then
          P.set_dynamic_y(names[i], clamp1023(y))
          _writes = _writes + 1
        end
      end
      if spec._done then
        finished = finished or {}
        finished[#finished + 1] = id
      end
    end
  end
  if finished then
    for _, id in ipairs(finished) do M.stop(id) end
  end
end

function M.writes_last_tick()
  return _writes
end

--- Test hook.
function M._reset_for_test()
  M.stop_all()
  _writes = 0
end

return M
