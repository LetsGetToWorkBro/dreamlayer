--- display/renderer.lua
--- Ported to real Brilliant Labs frame.* API.
--- All draw calls use frame.display.* directly.
--- Every render path: frame.display.clear(0x000000) -> draw -> frame.display.show()
---
--- Primitive approximations implemented as line-segment polylines.
---
--- FIXES:
---   - draw_ready: hex_pts flattened to {x1,y1,x2,y2,...} for frame.display.polygon
---   - draw_object_recall: AAA layout (left rail, left-anchored eyebrow,
---     wide bezier arc, 6px jewel, orbit r=12, hero place right of center)
---   - HAS_FRAME guard on all primitives and public API
---   - tick throttle %3 (~3fps)

local math = math
local P    = require("display.palette")
local T    = require("display.typography")

local HAS_FRAME = (type(_G.frame) == "table")

local renderer = {}

local _current_card = nil
local _tick_count   = 0

-- ---------------------------------------------------------------------------
-- Layer constants (kept for API compatibility)
-- ---------------------------------------------------------------------------
renderer.LAYER_BG      = 0
renderer.LAYER_CONTENT = 10
renderer.LAYER_OVERLAY = 20
renderer.LAYER_HUD     = 30

-- ---------------------------------------------------------------------------
-- Utility helpers
-- ---------------------------------------------------------------------------

local function floor(n) return math.floor(n + 0.5) end

-- ---------------------------------------------------------------------------
-- Primitive approximations
-- ---------------------------------------------------------------------------

local function bezier(p0x, p0y, p1x, p1y, p2x, p2y, color, steps)
  if not HAS_FRAME then return end
  steps = steps or 24
  local px, py = p0x, p0y
  for i = 1, steps do
    local t  = i / steps
    local mt = 1 - t
    local x  = mt*mt*p0x + 2*mt*t*p1x + t*t*p2x
    local y  = mt*mt*p0y + 2*mt*t*p1y + t*t*p2y
    local seg_idx = math.floor(i * 12 / steps) % 12
    if seg_idx < 7 then
      frame.display.line(floor(px), floor(py), floor(x), floor(y), color)
    end
    px, py = x, y
  end
end

local function elliptical_arc(cx, cy, rx, ry, start_deg, end_deg, color, steps)
  if not HAS_FRAME then return end
  steps = steps or 32
  local sweep = end_deg - start_deg
  local function rad_pt(deg)
    local r = math.rad(deg)
    return cx + rx * math.cos(r), cy + ry * math.sin(r)
  end
  local x0, y0 = rad_pt(start_deg)
  for i = 1, steps do
    local x1, y1 = rad_pt(start_deg + sweep * i / steps)
    frame.display.line(floor(x0), floor(y0), floor(x1), floor(y1), color)
    x0, y0 = x1, y1
  end
end

local function polyline(pts, color)
  if not HAS_FRAME then return end
  for i = 1, #pts - 1 do
    local a, b = pts[i], pts[i+1]
    frame.display.line(floor(a[1]), floor(a[2]), floor(b[1]), floor(b[2]), color)
  end
end

local function polar_segments(cx, cy, r_inner, r_outer, n_segs, lit_indices, color, ghost_color)
  if not HAS_FRAME then return end
  ghost_color = ghost_color or 0x2A3C44
  local lit_set = {}
  for _, v in ipairs(lit_indices) do lit_set[v] = true end
  local step = (2 * math.pi) / n_segs
  for i = 0, n_segs - 1 do
    local angle = step * i - math.pi / 2
    local xi = cx + r_inner * math.cos(angle)
    local yi = cy + r_inner * math.sin(angle)
    local xo = cx + r_outer * math.cos(angle)
    local yo = cy + r_outer * math.sin(angle)
    local c = lit_set[i] and color or ghost_color
    frame.display.line(floor(xi), floor(yi), floor(xo), floor(yo), c)
  end
end

local function radial_rays(cx, cy, r_min, r_max, n_rays, color, bloom_r)
  if not HAS_FRAME then return end
  bloom_r = bloom_r or 2
  local step = (2 * math.pi) / n_rays
  for i = 0, n_rays - 1 do
    local angle = step * i - math.pi / 2
    local x1 = cx + r_min * math.cos(angle)
    local y1 = cy + r_min * math.sin(angle)
    local x2 = cx + r_max * math.cos(angle)
    local y2 = cy + r_max * math.sin(angle)
    frame.display.line(floor(x1), floor(y1), floor(x2), floor(y2), color)
    frame.display.circle(floor(x2), floor(y2), bloom_r, color, false)
  end
end

local function check_glyph(cx, cy, size, color, progressive)
  if not HAS_FRAME then return end
  progressive = progressive or 1.0
  local s   = size / 60.0
  local ax  = cx - floor(21*s);  local ay  = cy
  local bx  = cx - floor(3*s);   local by  = cy + floor(18*s)
  local ccx = cx + floor(21*s);  local ccy = cy - floor(22*s)
  frame.display.line(ax, ay, bx, by, color)
  if progressive > 0.5 then
    local frac = math.min(1.0, (progressive - 0.5) * 2)
    local ex = bx + floor((ccx - bx) * frac)
    local ey = by + floor((ccy - by) * frac)
    frame.display.line(bx, by, ex, ey, color)
  end
end

local function shield_glyph(cx, cy, size, color, pause_bars)
  if not HAS_FRAME then return end
  if pause_bars == nil then pause_bars = true end
  local hw = size / 2
  local pts = {}
  for i = 0, 5 do
    local angle = math.rad(60 * i - 30)
    pts[#pts+1] = { floor(cx + hw * math.cos(angle)),
                    floor(cy + hw * math.sin(angle)) }
  end
  pts[#pts+1] = pts[1]
  polyline(pts, color)
  if pause_bars then
    local bar_h = math.max(3, floor(size * 0.24))
    local bar_w = math.max(2, floor(size * 0.08))
    local gap   = math.max(2, floor(size * 0.07))
    frame.display.rect(cx - gap - bar_w, cy - bar_h, bar_w, bar_h * 2, color, true)
    frame.display.rect(cx + gap,          cy - bar_h, bar_w, bar_h * 2, color, true)
  end
end

local function point_cloud_text(text, cx, cy, color)
  if not HAS_FRAME then return end
  frame.display.text(text, cx, cy, color)
end

-- ---------------------------------------------------------------------------
-- Card draw functions
-- ---------------------------------------------------------------------------

local CX, CY = 128, 128

local function draw_ready()
  -- BUG FIX: frame.display.polygon requires a flat array {x1,y1,x2,y2,...}
  -- not a table of {x,y} sub-tables. Build flat array directly.
  local hex_pts = {}
  for i = 0, 5 do
    local angle = math.rad(60 * i - 30)
    hex_pts[#hex_pts+1] = floor(CX + 8 * math.cos(angle))
    hex_pts[#hex_pts+1] = floor(CY + 8 * math.sin(angle))
  end
  frame.display.polygon(hex_pts, P.memory_trace)
  -- Asymmetric partial-arc rings
  elliptical_arc(CX, CY, 24, 24, 180, 360, P.accent_memory)
  elliptical_arc(CX, CY, 36, 36,   0, 270, P.accent_memory_dim)
  elliptical_arc(CX, CY, 48, 48, 270, 360, P.border_subtle)
  -- 4 satellite dots
  for _, deg in ipairs({0, 90, 180, 270}) do
    local r  = math.rad(deg)
    local sx = floor(CX + 24 * math.cos(r))
    local sy = floor(CY + 24 * math.sin(r))
    frame.display.circle(sx, sy, 2, P.memory_trace, true)
  end
end

local function draw_saved_memory(card)
  elliptical_arc(CX, CY, 48, 48,   0, 360, P.accent_success, 48)
  elliptical_arc(CX, CY, 48, 48, -90,   0, P.accent_success, 12)
  check_glyph(CX, CY - 8, 56, P.accent_success, 0.6)
  frame.display.text("SAVED", CX, CY - 42, P.accent_success)
  local label = (card and card.primary) or "Memory saved"
  frame.display.text(label, CX, CY + 22, P.text_primary)
end

local function draw_query_listening()
  frame.display.line(84, CY-6, 94, CY, P.memory_trace)
  frame.display.line(84, CY+6, 94, CY, P.memory_trace)
  frame.display.line(80, CY,   94, CY, P.memory_trace)
  frame.display.circle(94, CY, 2, P.memory_trace, true)
  local bar_count = 32
  local bar_w     = 2
  local gap       = 1
  local total_w   = bar_count * (bar_w + gap) - gap
  local start_x   = CX - math.floor(total_w / 2) + 12
  for i = 0, bar_count - 1 do
    local envelope = math.sin(math.pi * i / (bar_count - 1))
    local phase    = math.abs(math.sin(math.pi * 2 * i / bar_count * 3 + 1.2))
    local bh       = math.max(2, floor(22 * envelope * phase))
    local bx       = start_x + i * (bar_w + gap)
    frame.display.line(bx, CY - math.floor(bh/2), bx, CY + math.floor(bh/2),
                       P.accent_attention)
  end
end

local function draw_loading()
  for _, gr in ipairs({16, 28, 40, 52}) do
    elliptical_arc(CX, CY, gr, gr, 0, 360, P.border_subtle, 24)
  end
  elliptical_arc(CX, CY, 40, 40,  -70,  50, P.memory_trace, 16)
  elliptical_arc(CX, CY, 40, 40, -100, -70, P.accent_memory,     4)
  elliptical_arc(CX, CY, 40, 40, -130,-100, P.accent_memory_dim, 2)
  frame.display.circle(CX, CY, 3, P.memory_trace,     true)
  frame.display.circle(CX, CY, 6, P.accent_memory_dim, false)
end

local function draw_object_recall(card)
  -- AAA layout: left memory rail, left-anchored eyebrow, wide bezier arc,
  -- 6px jewel with orbit r=12, hero place text right of center.
  local obj    = ((card.object or card.primary or ""):upper())
  local place  = card.place    or ""
  local detail = card.detail   or ""
  local footer = card.last_seen or card.footer or ""
  local conf   = card.confidence
  local jcol = P.confidence_med
  if conf then
    if conf >= 0.75 then jcol = P.confidence_high
    elseif conf < 0.40 then jcol = P.confidence_low end
  end

  -- Left memory rail (x=44, y=72..188)
  frame.display.line(44, 72, 44, 188, P.memory_trace)
  -- Rail top dot
  frame.display.circle(44, 72, 3, P.memory_trace, true)
  -- Rail bottom confidence dot
  frame.display.circle(44, 188, 3, jcol, true)

  -- Eyebrow: object name, left-anchored near rail (not centered)
  frame.display.text(obj, 54, 80, P.memory_trace)

  -- Memory trace: wide bezier from rail anchor -> lower-right hero area
  -- p0=(46,90) rail anchor, p1=(200,62) ctrl pulls up-right, p2=(155,150) endpoint
  bezier(46, 90, 200, 62, 155, 150, P.memory_trace, 32)

  -- Confidence jewel at approximate curve apex (t~0.45)
  -- apex ~ (46*(0.55^2) + 2*0.55*0.45*200 + 0.45^2*155, same for y)
  local jx = floor(46*0.3025 + 2*0.55*0.45*200 + 0.2025*155)  -- ~152
  local jy = floor(90*0.3025 + 2*0.55*0.45*62  + 0.2025*150)  -- ~84
  local jd = 6  -- 6px diamond, clearly visible
  frame.display.line(jx,    jy-jd, jx+jd, jy,    jcol)
  frame.display.line(jx+jd, jy,    jx,    jy+jd, jcol)
  frame.display.line(jx,    jy+jd, jx-jd, jy,    jcol)
  frame.display.line(jx-jd, jy,    jx,    jy-jd, jcol)
  -- Orbit arcs r=12 (clearly visible, not 8)
  elliptical_arc(jx, jy, 12, 12,   0, 90, jcol, 8)
  elliptical_arc(jx, jy, 12, 12, 120,210, jcol, 8)
  elliptical_arc(jx, jy, 12, 12, 240,330, jcol, 8)

  -- Hero place text: right of center (x=155), large, dominant
  frame.display.text(place, 155, 150, P.text_primary)

  -- Detail bracket
  if detail ~= "" then
    frame.display.text("[ " .. detail .. " ]", CX, 178, P.text_secondary)
  end
  -- Footer
  frame.display.text(footer, CX, 198, P.text_ghost)
end

local function draw_commitment_recall(card)
  local person = card.person  or ""
  local task   = card.primary or card.task or ""
  local due    = card.due     or ""
  local conf   = card.confidence
  frame.display.text("YOU PROMISED " .. person:upper(), CX, 68, P.memory_trace)
  local link_w, link_h = 128, 18
  local lx     = CX - math.floor(link_w / 2)
  local link_ys = {84, 108, 132}
  for li, ly in ipairs(link_ys) do
    local c = (li == 3) and P.memory_trace or P.border_subtle
    polyline({
      {lx,        ly},         {lx+link_w, ly},
      {lx+link_w, ly+link_h},  {lx,        ly+link_h}, {lx, ly}
    }, c)
  end
  frame.display.line(CX, 84+link_h,  CX, 108, P.border_subtle)
  frame.display.line(CX, 108+link_h, CX, 132, P.border_subtle)
  frame.display.text(task, CX, 108 + math.floor(link_h/2), P.text_primary)
  frame.display.text(due,  CX, 132 + math.floor(link_h/2), P.memory_trace)
  local jcol = conf and (conf >= 0.75 and P.confidence_high or
                         conf >= 0.40 and P.confidence_med  or P.confidence_low)
               or P.text_ghost
  frame.display.circle(CX, 168, 2, jcol, true)
end

local function draw_proactive_memory(card)
  local summary = card.primary or card.summary or ""
  local person  = card.person
  frame.display.text("LAST TIME HERE", CX, 62, P.text_ghost)
  radial_rays(CX, CY - 10, 5, 52, 5, P.memory_trace, 2)
  frame.display.circle(CX, CY - 10, 3, P.memory_trace, true)
  frame.display.text(summary, CX, CY + 50, P.text_secondary)
  if person then
    frame.display.text("With " .. person, CX, CY + 78, P.memory_trace)
  end
end

local function draw_person_context(card)
  local name     = card.primary  or ""
  local headline = card.headline or ""
  local detail   = card.detail   or ""
  polar_segments(CX, 100, 38, 56, 12, {0, 1, 2}, P.memory_trace, P.border_subtle)
  frame.display.text(name, CX, 100, P.memory_trace)
  frame.display.line(72, 116, 184, 116, P.border_subtle)
  frame.display.text(headline, CX, 140, P.text_primary)
  frame.display.text(detail,   CX, 164, P.text_secondary)
end

local function draw_privacy_paused()
  elliptical_arc(CX, CY, 108, 108,  10, 350, P.privacy_danger, 48)
  elliptical_arc(CX, CY,  88,  88,   0, 360, P.privacy_danger, 32)
  shield_glyph(CX, CY - 14, 52, P.privacy_danger, true)
  frame.display.text("PAUSED",              CX, CY + 32, P.privacy_caution)
  frame.display.text("Nothing is captured", CX, CY + 48, P.text_ghost)
end

local function draw_error(card)
  elliptical_arc(CX, CY, 116, 116, 0, 360, P.warning_amber, 48)
  local tri_cy = CY - 8
  local ts = 56
  polyline({
    {CX,                    tri_cy - math.floor(ts/2)},
    {CX + floor(ts*0.577),  tri_cy + math.floor(ts/2)},
    {CX - floor(ts*0.577),  tri_cy + math.floor(ts/2)},
    {CX,                    tri_cy - math.floor(ts/2)},
  }, P.warning_amber)
  frame.display.circle(CX, tri_cy - 6,  2, P.warning_amber, true)
  frame.display.line(  CX, tri_cy + 2, CX, tri_cy + 14, P.warning_amber)
  local msg = (card and card.primary) or "Try again"
  frame.display.text(msg, CX, CY + 52, P.text_ghost)
end

local function draw_low_confidence()
  point_cloud_text("Not sure",       CX, CY - 14, P.text_secondary)
  point_cloud_text("Try rephrasing", CX, CY + 16, P.text_ghost)
  frame.display.circle(107, 180, 2, P.text_ghost, true)
  frame.display.circle(128, 184, 2, P.text_ghost, true)
  frame.display.circle(149, 180, 2, P.text_ghost, true)
end

-- ---------------------------------------------------------------------------
-- Dispatch table
-- ---------------------------------------------------------------------------
local CARD_DRAW = {
  ReadyCard            = function(_) draw_ready()              end,
  SavedMemoryCard      = function(c) draw_saved_memory(c)      end,
  QueryListeningCard   = function(_) draw_query_listening()    end,
  LoadingCard          = function(_) draw_loading()            end,
  ObjectRecallCard     = function(c) draw_object_recall(c)     end,
  CommitmentRecallCard = function(c) draw_commitment_recall(c) end,
  ProactiveMemoryCard  = function(c) draw_proactive_memory(c)  end,
  PersonContextCard    = function(c) draw_person_context(c)    end,
  PrivacyPausedCard    = function(_) draw_privacy_paused()     end,
  ErrorCard            = function(c) draw_error(c)             end,
  LowConfidenceCard    = function(_) draw_low_confidence()     end,
}

-- ---------------------------------------------------------------------------
-- Public API
-- ---------------------------------------------------------------------------

function renderer.show_card(card)
  if not card or not HAS_FRAME then return end
  local draw_fn = CARD_DRAW[card.type]
  if not draw_fn then return end
  frame.display.clear(0x000000)
  draw_fn(card)
  frame.display.show()
  _current_card = card
end

function renderer.tick()
  if not HAS_FRAME then return end
  _tick_count = _tick_count + 1
  if _current_card and (_tick_count % 3 == 0) then
    local draw_fn = CARD_DRAW[_current_card.type]
    if draw_fn then
      frame.display.clear(0x000000)
      draw_fn(_current_card)
      frame.display.show()
    end
  end
end

function renderer.push(layer, fn) if fn then fn() end end
function renderer.flush() end
function renderer.clear() end
function renderer.bind(disp, time_fn) end

return renderer
