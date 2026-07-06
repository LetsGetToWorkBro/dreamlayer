--- display/renderer.lua
--- Meridian (Cinema v2) render loop for DreamLayer Halo.
---
--- The display is a place, not a stage (docs/CINEMA_V2_THESIS.md): when
--- no card holds focus, renderer.tick() draws the Horizon — the wearer's
--- day as a rim instrument (display/horizon.lua). Cards do not
--- materialize; they CONDENSE inward from their horizon angle and RECEDE
--- home when released (display/focus.lua, docs/cinema_v2/focus.md):
---   CONDENSE  travel 140ms + landing 100ms  head flies rim->core, ring
---             collapses 56->36 gating staggered content layers
---   HOLD      ∞                             static focus ring at r=92,
---             sweep = confidence; card-specific idles unchanged
---   RECEDE    160ms                         text cuts at t=0.4, head
---             flies home, mark pulses on arrival
--- Crossfade = recession and condensation overlapping (40ms lag) — the
--- v1 Prism Slide and its fringe slots are gone (CINEMA_V2_DELTAS.md §2).
---
--- Special behaviours:
---   PrivacyVeilCard / Consent / Forget / PrivateZone → slam entry kept;
---     released with a hard cut, never a recession (no privacy residue)
---   TruthLensCard  → Truth Ripple entry (S5, kept) + Testimony Thread
---     accumulation (docs/cinema_v2/testimony.md); no focus ring (the
---     thread is the card's confidence surface)
---   LoadingCard / QueryListeningCard / CommitmentDriftCard /
---   DeviationAlertCard idles unchanged
---   settings.reduce_motion → content complete on first frame, full-sweep
---     ring + static origin tick; recessions are hard cuts + mark step
---
--- Public API (unchanged from callers):
---   renderer.bind(time_fn)     — wire monotonic clock (called once at boot)
---   renderer.show_card(card)   — begin CONDENSE for card (or crossfade)
---   renderer.dismiss()         — begin RECEDE for current card
---   renderer.tick()            — advance animations, composite, push frame
---   renderer.push/flush/clear  — no-op stubs (backward compat)

local math  = math
local P     = require("display.palette")
local T     = require("display.typography")
local A     = require("display.animations")
local E     = require("lib.easing")
local TR    = require("display.transitions")
local F     = require("display.focus")
local HZ    = require("display.horizon")
local PA    = require("display.palette_animator")
local PX    = require("display.parallax")
local PT    = require("display.particles")

local HAS_FRAME = (type(_G.frame) == "table")

local ease_out_expo    = E.out_expo
local ease_in_out_sine = E.in_out_sine
local ease_linear      = E.linear

-- Card light bands (Lumen): geometry drawn in these bases follows the
-- card slots, so a leased wave program can flow light along it. The
-- slots alias the aurora/dream bank — mode-exclusive by construction.
P.reserve_dynamic("card_a", A.SPEC_BASE_A, 3)
P.reserve_dynamic("card_b", A.SPEC_BASE_B, 4)
P.reserve_dynamic("card_c", A.SPEC_BASE_C, 1)
-- voice aliases card_a's slot (free during listening), NOT fx: fx's base
-- is accent_memory, so painting that slot another hue would recolor every
-- accent_memory draw on the panel (found by the Lumen audit render)
P.reserve_dynamic("voice",  A.VOICE_BASE,  3)

-- Live voice level for QueryListeningCard ({t="amp"} messages, 0-99).
-- nil until the host ever sends one: the waveform then keeps its v1
-- self-running look, so nothing regresses without the host feature.
local _amp_target = nil
local _amp        = 0

-- ---------------------------------------------------------------------------
-- Animation state
-- ---------------------------------------------------------------------------
local _now_fn       = nil   -- injected by bind()
local _boot_t       = os.clock()

local function _now_ms()
  if _now_fn then return _now_fn() end
  return math.floor((os.clock() - _boot_t) * 1000)
end

-- Current card phase
local _card         = nil   -- active card
local _phase        = nil   -- "enter" | "hold" | "exit" | nil
local _phase_start  = 0     -- ms when current phase began
local _idle_t       = 0     -- accumulator for hold-phase idle animations

-- Previous card (crossfade)
local _prev_card    = nil
local _prev_exit_t  = 0     -- 0→1 progress of outgoing exit
local _prev_start   = 0

local renderer = {}

-- ---------------------------------------------------------------------------
-- Math helpers
-- ---------------------------------------------------------------------------
local function floor(n)  return math.floor(n + 0.5) end
local function clamp(v, lo, hi) return math.max(lo, math.min(hi, v)) end
local function lerp(a, b, t)    return a + (b - a) * t end

-- ---------------------------------------------------------------------------
-- Primitive drawing (all frame.display.* line/circle/rect/text)
-- ---------------------------------------------------------------------------

-- color may be a single hex or a band table {hexA, hexB, ...}: banded
-- segments follow the card slots, so a wave program flows light along
-- the pre-drawn curve (Lumen — the memory-trace "conducts")
local function bezier(p0x,p0y,p1x,p1y,p2x,p2y, color, steps)
  if not HAS_FRAME then return end
  steps = steps or 24
  local banded = (type(color) == "table")
  local px,py = p0x,p0y
  for i = 1,steps do
    local t  = i/steps
    local mt = 1-t
    local x  = mt*mt*p0x + 2*mt*t*p1x + t*t*p2x
    local y  = mt*mt*p0y + 2*mt*t*p1y + t*t*p2y
    if math.floor(i*12/steps)%12 < 7 then
      local c = banded and color[(i % #color) + 1] or color
      frame.display.line(floor(px),floor(py),floor(x),floor(y),c)
    end
    px,py = x,y
  end
end

local function arc(cx,cy,r,a0,a1,color,steps)
  if not HAS_FRAME or r <= 0 then return end
  steps = steps or 32
  local sweep = a1-a0
  local function pt(deg)
    local rd = math.rad(deg)
    return cx+r*math.cos(rd), cy+r*math.sin(rd)
  end
  local x0,y0 = pt(a0)
  for i=1,steps do
    local x1,y1 = pt(a0 + sweep*i/steps)
    frame.display.line(floor(x0),floor(y0),floor(x1),floor(y1),color)
    x0,y0 = x1,y1
  end
end

local function polyline(pts,color)
  if not HAS_FRAME then return end
  for i=1,#pts-1 do
    local a,b = pts[i],pts[i+1]
    frame.display.line(floor(a[1]),floor(a[2]),floor(b[1]),floor(b[2]),color)
  end
end

local function closed_poly(pts,color)
  if not HAS_FRAME then return end
  for i=1,#pts do
    local a = pts[i]; local b = pts[(i%#pts)+1]
    frame.display.line(floor(a[1]),floor(a[2]),floor(b[1]),floor(b[2]),color)
  end
end

local function polar_segs(cx,cy,ri,ro,n,lit,color,ghost,skip)
  if not HAS_FRAME then return end
  ghost = ghost or 0x2A3C44
  local lit_set={}
  for _,v in ipairs(lit) do lit_set[v]=true end
  local skip_set={}
  if skip then for _,v in ipairs(skip) do skip_set[v]=true end end
  local step=(2*math.pi)/n
  for i=0,n-1 do
    if not skip_set[i] then
    local a=step*i-math.pi/2
    local xi=cx+ri*math.cos(a); local yi=cy+ri*math.sin(a)
    local xo=cx+ro*math.cos(a); local yo=cy+ro*math.sin(a)
    frame.display.line(floor(xi),floor(yi),floor(xo),floor(yo), lit_set[i] and color or ghost)
    end
  end
end

local function radial_rays(cx,cy,r0,r1,n,color,bloom)
  if not HAS_FRAME then return end
  bloom=bloom or 2
  local step=(2*math.pi)/n
  for i=0,n-1 do
    local a=step*i-math.pi/2
    local x1=cx+r0*math.cos(a); local y1=cy+r0*math.sin(a)
    local x2=cx+r1*math.cos(a); local y2=cy+r1*math.sin(a)
    frame.display.line(floor(x1),floor(y1),floor(x2),floor(y2),color)
    frame.display.circle(floor(x2),floor(y2),bloom,color,false)
  end
end

local function check_glyph(cx,cy,size,color,prog)
  if not HAS_FRAME then return end
  prog = prog or 1.0
  local s=size/60
  local ax=cx-floor(21*s); local ay=cy
  local bx=cx-floor(3*s);  local by=cy+floor(18*s)
  local ccx=cx+floor(21*s);local ccy=cy-floor(22*s)
  frame.display.line(ax,ay,bx,by,color)
  if prog>0.5 then
    local f=math.min(1,(prog-0.5)*2)
    frame.display.line(bx,by,bx+floor((ccx-bx)*f),by+floor((ccy-by)*f),color)
  end
end

local function shield_glyph(cx,cy,size,color,bars)
  if not HAS_FRAME then return end
  if bars==nil then bars=true end
  local hw=size/2
  local pts={}
  for i=0,5 do
    local a=math.rad(60*i-30)
    pts[#pts+1]={floor(cx+hw*math.cos(a)), floor(cy+hw*math.sin(a))}
  end
  closed_poly(pts,color)
  if bars then
    local bh=math.max(3,floor(size*0.24))
    local bw=math.max(2,floor(size*0.08))
    local gap=math.max(2,floor(size*0.07))
    frame.display.rect(cx-gap-bw,cy-bh,bw,bh*2,color,true)
    frame.display.rect(cx+gap,   cy-bh,bw,bh*2,color,true)
  end
end

-- ---------------------------------------------------------------------------
-- Per-card draw functions  (t = eased 0→1 for enter/exit scaling)
-- All radii are multiplied by `scale` = lerp(0.94, 1.0, t) during ENTER,
-- or lerp(1.0, 0.0, t) during EXIT.
-- Text elements are suppressed when their stagger has not yet elapsed.
-- ---------------------------------------------------------------------------

local CX,CY = 128,128

local MAT = require("display.materials")

-- ObjectRecall trace: dim at the wearer, bright at the jewel; the bright
-- half rides the card band bases so the conduct wave still flows there
local RAMP_TRACE_UP = { 0x2A3C44, 0x1A7A60, 0x01FFAA, 0x00FFA9 }

-- Solid: every renderer string goes through the sized-text seam. The
-- size tokens are typography.DEVICE_FONT keys; primitives caches the
-- set_font call and latches the feature off if firmware lacks it.
local PR = require("display.primitives")
local function text(str, x, y, color, size)
  PR.text_center(x, y, str, size, color)
end

-- Wrapped, vertically-centered text block — for the O3 cards whose primary is a
-- spoken sentence rather than a short label. Caps at `max_lines` so it never
-- spills the circular panel; single-line callers still use text()+fit_size.
local function text_block(str, x, y, color, size, width, max_lines)
  local lines = T.wrap(str, size, width) or { str }
  max_lines = max_lines or 3
  local n = math.min(#lines, max_lines)
  local lh = T.block_line_height(size)
  local start = y - (n - 1) * lh / 2
  for i = 1, n do
    text(lines[i], x, floor(start + (i - 1) * lh), color, size)
  end
end

-- stagger helpers: returns true when global enter_t has passed layer threshold
local function layer_ok(enter_t, stagger_ms)
  return enter_t >= (stagger_ms / A.ENTER_DURATION_MS)
end

local function draw_ready(sc, enter_t, exit_t)
  local r  = floor(8  * sc)
  local r2 = floor(24 * sc)
  local r3 = floor(36 * sc)
  local r4 = floor(48 * sc)
  if r<1 then return end
  -- hex core
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    local pts={}
    for i=0,5 do
      local a=math.rad(60*i-30)
      pts[#pts+1]={floor(CX+r*math.cos(a)),floor(CY+r*math.sin(a))}
    end
    closed_poly(pts, P.memory_trace)
  end
  -- rings (Solid: gradient strokes — same call count, living light)
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    MAT.grad_arc(CX,CY,r2, 180,360, MAT.RAMP_MEMORY, 32)
    arc(CX,CY,r3,   0,270, P.accent_memory_dim)
    arc(CX,CY,r4, 270,360, P.border_subtle)
  end
  -- satellite dots
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    for _,deg in ipairs({0,90,180,270}) do
      local rd=math.rad(deg)
      frame.display.circle(floor(CX+r2*math.cos(rd)),floor(CY+r2*math.sin(rd)),2,P.memory_trace,true)
    end
  end
end

-- SavedMemoryCard v2 (Meridian Solid): the confirmation is a jewel —
-- a giant double-struck check inside concentric gradient rings over a
-- soft pane, SAVED in hero type. Spring draw-on, chime, and the burst
-- flair keep their Lumen contracts.
local function draw_saved_memory(card, sc, enter_t, exit_t, idle_t)
  local r = floor(46 * sc)
  if r<1 then return end
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) and exit_t == 0 then
    MAT.glass_disc(CX, 124, floor(66*sc), MAT.PANE, 4)
  end
  frame.display.circle(CX, 124, floor(70*sc), P.border_subtle, false)
  arc(CX,124,floor(62*sc),0,360,P.border_subtle,32)
  arc(CX,124,floor(54*sc),0,360,P.accent_success_dim,28)
  arc(CX,124,r,0,360,P.accent_success,24)
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    -- Lumen: the check draws on with a soft spring; Solid: it is giant
    -- and double-struck (2px stroke reads as engraved, not sketched)
    local prog = E.spring(math.min(1, enter_t*2),
                          A.SPRING_ZETA_SOFT, A.SPRING_OMEGA)
    check_glyph(CX,120,floor(72*sc),P.accent_success, prog)
    check_glyph(CX,121,floor(72*sc),P.accent_success, prog)
  end
  -- Lumen: the chime ring breathes outward once as the card settles
  if enter_t >= 1.0 and exit_t == 0 and idle_t and not TR.reduce_motion()
     and idle_t < A.SIG_CHIME_MS then
    TR.chime(idle_t / A.SIG_CHIME_MS, CX, 120)
  end
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    text("SAVED",CX,42,P.accent_success, "hero")
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    local primary = (card and card.primary) or "Memory saved"
    text(T.truncate(primary, "md", 180),CX,206,P.text_primary, "md")
  end
end

local function draw_query_listening(sc, enter_t, idle_t)
  -- microphone icon
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    frame.display.line(84,CY-6,94,CY,P.memory_trace)
    frame.display.line(84,CY+6,94,CY,P.memory_trace)
    frame.display.line(80,CY,  94,CY,P.memory_trace)
    frame.display.circle(94,CY,2,P.memory_trace,true)
  end
  -- waveform: phase advances with idle_t. Lumen: when the host streams
  -- {t="amp"} the bars track the real voice level (spring-smoothed) and
  -- the whole waveform warms with it through the voice slot — your words
  -- visibly land in the glasses. Without amp data: the v1 look, exactly.
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    local scale = 1.0
    local bar_color = P.accent_attention
    if _amp_target and not TR.reduce_motion() then
      _amp = _amp + 0.35 * (_amp_target - _amp)
      scale = 0.35 + 0.65 * _amp
      bar_color = P.dynamic_color("voice")
      P.shift_dynamic("voice", _amp * A.VOICE_Y_GAIN, 0,
                      _amp * A.VOICE_CR_GAIN)
    end
    local phase_off = idle_t * 0.006  -- slow drift
    local bar_count=32; local bar_w=2; local gap=1
    local total_w=bar_count*(bar_w+gap)-gap
    local start_x=CX-floor(total_w/2)+12
    for i=0,bar_count-1 do
      local envelope=math.sin(math.pi*i/(bar_count-1))
      local phase=math.abs(math.sin(math.pi*2*i/bar_count*3+1.2+phase_off))
      local bh=math.max(2,floor(22*envelope*phase*scale*sc))
      local bx=start_x+i*(bar_w+gap)
      frame.display.line(bx,CY-floor(bh/2),bx,CY+floor(bh/2),bar_color)
    end
  end
end

-- Lumen: the rotating-arc spinner is killed. Twelve STATIC segments band
-- across the three card slots and a palette wave chases light around the
-- stationary ring at the old spinner's RPM — motion by recolouring, not
-- redrawing (docs/PALETTE_CYCLE.md, generalized). Fewer draw calls than
-- the v1 spinner, and reduce_motion degrades to a static gradient ring
-- (strictly better than a frozen spinner arc).
local CHASE_BANDS = { A.SPEC_BASE_A, A.SPEC_BASE_B, A.SPEC_BASE_C }

local function draw_loading(sc, enter_t, idle_t)
  -- ghost rings scale in (r=40 yielded to the chase ring)
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    for _,gr in ipairs({16,28,52}) do
      arc(CX,CY,floor(gr*sc),0,360,P.border_subtle,24)
    end
  end
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    local r = floor(40*sc)
    local n = A.CHASE_SEGMENTS
    local span = 360 / n
    local gap = 6
    for i = 0, n-1 do
      local a0 = -90 + i * span + gap / 2
      arc(CX,CY,r, a0, a0 + span - gap, CHASE_BANDS[i % 3 + 1], 3)
    end
    frame.display.circle(CX,CY,3,P.memory_trace,true)
    frame.display.circle(CX,CY,floor(6*sc),P.accent_memory_dim,false)
    MAT.bloom_ring(CX,CY,6,P.memory_trace)
  end
end

-- ---------------------------------------------------------------------------
-- ObjectRecallCard v3 (Meridian Solid): a spatial scene, not a text list.
-- The place is a translucent field of light; the object is a jewel in it;
-- you are a dot at the bottom; a gradient trace (dim at you, bright at the
-- jewel) connects the two — the memory literally shows where the thing is
-- relative to you. The conduct flair still flows on the trace's bright
-- half (RAMP_MEMORY_LIVE leads with the card band bases). Confidence
-- keeps its color semantics on the jewel.
-- ---------------------------------------------------------------------------
local function draw_object_recall(card, sc, enter_t, exit_t)
  local obj    = ((card.object or card.primary or ""):upper())
  local place  = card.place   or ""
  local detail = card.detail  or ""
  local footer = card.last_seen or card.footer or ""
  local conf   = card.confidence
  local jcol   = P.confidence_med
  if conf then
    if conf>=0.75 then jcol=P.confidence_high
    elseif conf<0.40 then jcol=P.confidence_low end
  end

  -- the place, as a translucent field (panes never draw during exit)
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) and exit_t == 0 then
    MAT.glass_disc(CX, 112, floor(62*sc), MAT.PANE, 3)
  end

  -- gradient trace: you -> object, cooling away from the jewel
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    MAT.grad_bezier(128,192, 168,140, 132,102, RAMP_TRACE_UP, 24)
  end

  -- the object jewel: layered diamonds + orbit arcs + bloom
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    local jx, jy = 128, 88
    local jd = floor(9*sc)
    if jd >= 2 then
      frame.display.line(jx,jy-jd,jx+jd,jy,jcol)
      frame.display.line(jx+jd,jy,jx,jy+jd,jcol)
      frame.display.line(jx,jy+jd,jx-jd,jy,jcol)
      frame.display.line(jx-jd,jy,jx,jy-jd,jcol)
      local di = math.max(1, floor(4*sc))
      frame.display.line(jx,jy-di,jx+di,jy,P.memory_trace)
      frame.display.line(jx+di,jy,jx,jy+di,P.memory_trace)
      frame.display.line(jx,jy+di,jx-di,jy,P.memory_trace)
      frame.display.line(jx-di,jy,jx,jy-di,P.memory_trace)
    end
    arc(jx,jy,floor(14*sc),  0, 90,jcol,8)
    arc(jx,jy,floor(14*sc),120,210,jcol,8)
    arc(jx,jy,floor(14*sc),240,330,jcol,8)
    MAT.bloom_ring(jx, jy, floor(14*sc), jcol)
  end

  -- you, at the bottom of the scene
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    frame.display.circle(128, 198, 3, P.memory_trace, true)
    MAT.bloom_ring(128, 198, 3, P.memory_trace)
  end

  -- type: time eyebrow, object label, HERO place, bracketed detail
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    text(footer, CX, 50, P.text_ghost, "sm")
    text(obj, CX, 66, P.memory_trace, "md")
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    text(place, CX, 150, P.text_primary, T.fit_size(place, 170))
    if detail~="" then text("[ "..detail.." ]",CX,176,P.text_secondary, "md") end
  end
end

local function draw_commitment_recall(card, sc, enter_t, exit_t)
  local person = card.person  or ""
  local task   = card.primary or card.task or ""
  local due    = card.due     or ""
  local conf   = card.confidence
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    text("YOU PROMISED "..person:upper(),CX,68,P.memory_trace, "sm")
  end
  -- Lumen: the chain forges link by link — each spring-widens open on
  -- its own stagger, so the promise visibly locks together (geometry
  -- only; the task text keeps its plain stagger). Settled/reduce frames
  -- are the pre-Lumen chain exactly (spring(1) = 1).
  local link_h=18
  local link_ys={84,108,132}
  local staggers={A.STAGGER_PRIMARY_MS, A.STAGGER_DETAIL_MS, A.STAGGER_FOOTER_MS}
  for li,ly in ipairs(link_ys) do
    if layer_ok(enter_t, staggers[li]) then
      local lt = clamp((enter_t * A.ENTER_DURATION_MS - staggers[li])
                       / (A.ENTER_DURATION_MS - staggers[li] + 1), 0, 1)
      local w = floor(128 * sc * E.spring(lt, A.SPRING_ZETA_SNAPPY,
                                          A.SPRING_OMEGA))
      if w >= 2 then
        local lx=CX-floor(w/2)
        local c=(li==3) and P.memory_trace or P.border_subtle
        polyline({{lx,ly},{lx+w,ly},{lx+w,ly+link_h},{lx,ly+link_h},{lx,ly}},c)
      end
    end
  end
  -- Solid: the live (final) link glows from within; the connectors are
  -- gradient strokes falling toward it
  if enter_t >= 1.0 and exit_t == 0 then
    MAT.glass_capsule(CX-60, 133, 120, 16, MAT.PANE, 3)
  end
  MAT.grad_line(CX,84+link_h, CX,108, { P.border_subtle, P.accent_memory_dim })
  MAT.grad_line(CX,108+link_h,CX,132, { P.accent_memory_dim, P.accent_memory_static })
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    text(task,CX,108+floor(link_h/2),P.text_primary, "md")
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    text(due,CX,132+floor(link_h/2),P.memory_trace, "md")
  end
  local jcol=conf and (conf>=0.75 and P.confidence_high or conf>=0.40 and P.confidence_med or P.confidence_low) or P.text_ghost
  frame.display.circle(CX,168,2,jcol,true)
end

local function draw_proactive_memory(card, sc, enter_t, exit_t)
  local summary = card.primary or card.summary or ""
  local person  = card.person
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    text("LAST TIME HERE",CX,62,P.text_ghost, "sm")
  end
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    radial_rays(CX,CY-10, floor(5*sc),floor(52*sc), 5,P.memory_trace,2)
    frame.display.circle(CX,CY-10,3,P.memory_trace,true)
    MAT.bloom_ring(CX,CY-10,3,P.memory_trace)
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    text(summary,CX,CY+50,P.text_secondary, "lg")
  end
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) and person then
    text("With "..person,CX,CY+78,P.memory_trace, "sm")
  end
end

-- PersonContextCard v2 (Social Lens, Halo Cinema v1 Phase 4):
--   name is PRIMARY; card.why carries "why this person matters right now"
--   (highest-scoring memory involving them in the last 30 days);
--   card.has_avatar marks that a 32×32 contact avatar sprite was streamed
--   separately — the chord arpeggio rings its position. Avatars only ever
--   exist for registered contacts (enforced host-side).
local function draw_person_context(card, sc, enter_t, exit_t)
  local name     = card.primary  or ""
  local headline = card.headline or ""
  local why      = card.why      or ""
  local detail   = card.detail   or ""
  -- Solid: the person is a centerpiece — avatar ring with bloom under an
  -- enlarged crown over a soft pane, name in hero-class type. The chord
  -- arpeggio and the one-why-line spec are unchanged.
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    if exit_t == 0 then
      MAT.glass_disc(CX, 96, floor(56*sc), MAT.PANE, 3)
    end
    frame.display.circle(CX, 84, floor(18*sc), P.border_subtle, false)
    MAT.bloom_ring(CX, 84, floor(18*sc), P.accent_memory_static)
    polar_segs(CX,84, floor(26*sc),floor(44*sc), 12,{0,1,2},P.memory_trace,P.border_subtle,{5,6,7})
    if card.has_avatar then
      -- chord arpeggio around the avatar sprite; confidence shapes the sweep
      TR.chord(enter_t, CX, 84, card.confidence or 1)
    end
  end
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    text(name,CX,148,P.memory_trace, T.fit_size(name, 170, {"hero","xl"}))
    MAT.grad_line(76, 164, 180, 164, MAT.RAMP_MEMORY)
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    -- spec: exactly ONE line of "why this person matters right now"
    local line = why ~= "" and why or headline
    if #line > 34 then line = line:sub(1, 33) .. "\xE2\x80\xA6" end
    text(line,CX,180,P.text_primary, "md")
  end
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) then
    if why ~= "" and headline ~= "" then
      text(headline,CX,196,P.text_secondary, "sm")
    end
    text(detail,CX,210,P.text_ghost, "sm")
  end
end

-- Shield slam: outer rings expand radially; glyph appears only after rings complete
local function draw_privacy_veil(sc, enter_t, exit_t)
  -- Rings slam outward: at enter_t=0 they're r=0, at enter_t=0.6 they're full size
  local ring_t = clamp(enter_t / 0.6, 0, 1)
  local ring_sc = ease_out_expo(ring_t)
  arc(CX,CY,floor(108*ring_sc*sc), 10,350,P.privacy_danger,48)
  arc(CX,CY,floor(88 *ring_sc*sc),  0,360,P.privacy_danger,32)
  -- Shield glyph: slams in after rings reach 60%
  if enter_t >= 0.6 then
    local glyph_t = clamp((enter_t-0.6)/0.4,0,1)
    shield_glyph(CX,CY-14,floor(52*ease_out_expo(glyph_t)*sc),P.privacy_danger,true)
  end
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) then
    text("PAUSED",CX,CY+32,P.privacy_caution, "lg")
    text("Nothing is captured",CX,CY+48,P.text_ghost, "sm")
  end
end

local function draw_error(card, sc, enter_t, exit_t)
  -- Lumen: the attention ring draws on as one sweep from 12 o'clock —
  -- calm and legible (an error should never celebrate itself); settled
  -- and reduce_motion frames are the full pre-Lumen ring
  local ring_sweep = 360 * E.spring(clamp(enter_t, 0, 1),
                                    A.SPRING_ZETA_SOFT, A.SPRING_OMEGA)
  arc(CX,CY,floor(116*sc),-90,-90+ring_sweep,P.warning_amber,
      math.max(6, floor(ring_sweep / 7.5)))
  local tri_cy=CY-8; local ts=floor(56*sc)
  polyline({
    {CX,               tri_cy-floor(ts/2)},
    {CX+floor(ts*0.577),tri_cy+floor(ts/2)},
    {CX-floor(ts*0.577),tri_cy+floor(ts/2)},
    {CX,               tri_cy-floor(ts/2)},
  },P.warning_amber)
  frame.display.circle(CX,tri_cy-6,2,P.warning_amber,true)
  frame.display.line(CX,tri_cy+2,CX,tri_cy+14,P.warning_amber)
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    text((card and card.primary) or "Try again",CX,CY+52,P.text_ghost, "md")
  end
end

local function draw_low_confidence(sc, enter_t, exit_t)
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    text("Not sure",CX,CY-14,P.text_secondary, "lg")
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    text("Try rephrasing",CX,CY+16,P.text_ghost, "md")
  end
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) then
    local dot_r=floor(2*sc)
    if dot_r>=1 then
      frame.display.circle(107,180,dot_r,P.text_ghost,true)
      frame.display.circle(128,184,dot_r,P.text_ghost,true)
      frame.display.circle(149,180,dot_r,P.text_ghost,true)
    end
  end
end

-- ---------------------------------------------------------------------------
-- CommitmentDriftCard
-- Fired by tick_drift() when a commitment exceeds its staleness threshold.
--
-- Layout:
--   EYEBROW   "DRIFT DETECTED"   memory_trace
--   rail      vertical, left edge — full height = full confidence,
--             decayed portion drawn in border_subtle
--   PRIMARY   task summary        text_primary
--   PERSON    "→ <person>"        memory_trace (with chain dots)
--   DETAIL    days-ago footer     text_ghost
--   idle      confidence dot pulses via ease_in_out_sine on idle_t
-- ---------------------------------------------------------------------------
local function draw_commitment_drift(card, sc, enter_t, exit_t, idle_t)
  local task    = card.primary  or card.task    or ""
  local person  = card.person   or ""
  local detail  = card.footer   or card.detail  or ""
  local conf    = card.confidence or 0.5
  local decay   = card.decay    or 0.0   -- 0=fresh, 1=fully stale

  -- Urgency colour: shifts amber → danger as decay increases
  local urgency_col = (decay >= 0.6) and P.privacy_danger or P.warning_amber

  -- Left rail: full bar (border_subtle) with live portion (urgency_col) on top
  local rail_x  = 44
  local rail_y0 = floor(lerp(CY, 68,  sc))
  local rail_y1 = floor(lerp(CY, 192, sc))
  local rail_h  = rail_y1 - rail_y0
  frame.display.line(rail_x, rail_y0, rail_x, rail_y1, P.border_subtle)
  -- live portion = conf * (1-decay) of total rail height
  local live_frac = clamp(conf * (1.0 - decay), 0, 1)
  local live_h    = floor(rail_h * live_frac)
  if live_h > 0 then
    frame.display.line(rail_x, rail_y1-live_h, rail_x, rail_y1, urgency_col)
  end
  frame.display.circle(rail_x, rail_y0, 2, P.border_subtle, true)
  frame.display.circle(rail_x, rail_y1, 3, urgency_col,     true)
  MAT.bloom_ring(rail_x, rail_y1, 3, urgency_col)

  -- Eyebrow
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    text("DRIFT DETECTED", CX, 72, P.memory_trace, "sm")
  end

  -- Primary task text
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    text(task, CX, CY - 12, P.text_primary, "lg")
  end

  -- Person chain: three dots then arrow then name
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    if person ~= "" then
      -- chain dots
      for i = 0, 2 do
        frame.display.circle(CX - 20 + i * 8, CY + 16, 2, P.border_subtle, true)
      end
      text("\xe2\x86\x92 " .. person, CX, CY + 32, P.memory_trace, "md")
    end
  end

  -- Footer detail
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) then
    text(detail, CX, 184, P.text_ghost, "sm")
  end

  -- Hold-phase confidence dot pulse (size oscillates)
  if enter_t >= 1.0 and exit_t == 0 then
    local pulse = ease_in_out_sine((math.sin(idle_t / 600 * math.pi) + 1) / 2)
    local dot_r = floor(lerp(2, 5, pulse) * sc)
    if dot_r >= 1 then
      frame.display.circle(CX, 200, dot_r, urgency_col, true)
    end
  end
end

-- ---------------------------------------------------------------------------
-- TimeScrubNodeCard
-- Streamed one card per node during start_scrub() / scrub() sessions.
--
-- Layout:
--   timeline  horizontal bar (full card width) with node dots
--   current   larger filled dot at card.index position
--   EYEBROW   timestamp / breadcrumb     text_ghost
--   PRIMARY   node summary text          text_primary
--   DETAIL    place name (if present)    memory_trace
--   prev/next faint neighbour labels     text_ghost
-- ---------------------------------------------------------------------------
local function draw_time_scrub_node(card, sc, enter_t, exit_t, idle_t)
  local summary   = card.primary  or card.summary  or ""
  local place     = card.place    or ""
  local timestamp = card.eyebrow  or card.timestamp or ""
  local idx       = card.index    or 1   -- 1-based position
  local total     = card.total    or 1   -- total nodes in session
  local prev_lbl  = card.prev_label or ""
  local next_lbl  = card.next_label or ""

  -- Timeline bar
  local bar_y   = floor(lerp(CY, 82, sc))
  local bar_x0  = floor(lerp(CX, 40,  sc))
  local bar_x1  = floor(lerp(CX, 216, sc))
  local bar_w   = bar_x1 - bar_x0
  if bar_w > 0 then
    frame.display.line(bar_x0, bar_y, bar_x1, bar_y, P.border_subtle)
  end

  -- Node dots along the bar
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) and total > 0 then
    for i = 1, total do
      local nx = bar_x0 + floor(bar_w * (i - 1) / math.max(total - 1, 1))
      if i == idx then
        -- current node: larger dot in memory_trace
        local cur_r = floor(lerp(3, 5, ease_out_expo(clamp((enter_t - A.STAGGER_PRIMARY_MS / A.ENTER_DURATION_MS) * 3, 0, 1))))
        frame.display.circle(nx, bar_y, cur_r, P.memory_trace, true)
        MAT.bloom_ring(nx, bar_y, cur_r, P.memory_trace)
        -- tick below current dot
        frame.display.line(nx, bar_y + cur_r + 1, nx, bar_y + cur_r + 6, P.memory_trace)
      else
        -- ghost dot
        local ghost_r = (i < idx) and 2 or 1
        frame.display.circle(nx, bar_y, ghost_r, P.border_subtle, true)
      end
    end
  end

  -- Eyebrow: timestamp / position
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    local crumb = timestamp ~= "" and timestamp or (idx .. " / " .. total)
    text(crumb, CX, 66, P.text_ghost, "sm")
  end

  -- Primary summary
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    text(summary, CX, CY - 4, P.text_primary, "lg")
  end

  -- Place name
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) and place ~= "" then
    text(place, CX, CY + 22, P.memory_trace, "md")
  end

  -- Prev / next neighbour ghost labels
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) then
    if prev_lbl ~= "" then
      text("\xe2\x97\x80 " .. prev_lbl, 56, 182, P.text_ghost, "sm")
    end
    if next_lbl ~= "" then
      text(next_lbl .. " \xe2\x96\xb6", 200, 182, P.text_ghost, "sm")
    end
  end
end

-- ---------------------------------------------------------------------------
-- DeviationAlertCard
-- Fired by TellEngine when a new transcript contradicts a prior commitment.
--
-- Layout:
--   EYEBROW   "Sounds different…"   warning_amber
--   separator horizontal rule
--   PRIOR     prior_summary (what was promised)  text_ghost  (above divider)
--   divider   dashed rule
--   NEW       new_summary (what was just said)   text_primary (below divider)
--   SCORE_DOT coloured dot encodes deviation score
--   hold      ripple ring expands & fades with idle_t
-- ---------------------------------------------------------------------------
local function draw_deviation_alert(card, sc, enter_t, exit_t, idle_t)
  local prior_text = card.prior_summary  or card.footer   or ""
  local new_text   = card.new_summary    or card.primary  or ""
  local score      = card.score          or 0.0

  -- Score → colour: low=med, high=danger
  local score_col = (score >= 0.75) and P.privacy_danger
                 or (score >= 0.50) and P.warning_amber
                 or P.confidence_med

  -- Outer attention ring scales in with enter
  local ring_r = floor(lerp(52, 108, ease_out_expo(enter_t)) * sc)
  if ring_r >= 1 then
    arc(CX, CY, ring_r, 0, 360, P.warning_amber, 48)
  end

  -- Eyebrow
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    text("SOUNDS DIFFERENT", CX, 66, P.warning_amber, "sm")
  end

  -- Separator
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    local sep_x0 = floor(lerp(CX, 52,  sc))
    local sep_x1 = floor(lerp(CX, 204, sc))
    frame.display.line(sep_x0, 78, sep_x1, 78, P.border_subtle)
  end

  -- Prior summary (above central divider)
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    text(prior_text, CX, 100, P.text_ghost, "md")
  end

  -- Central dashed divider
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    local d_x0 = floor(lerp(CX, 80,  sc))
    local d_x1 = floor(lerp(CX, 176, sc))
    local dash_w = 6; local gap = 4; local x = d_x0
    while x < d_x1 do
      local xe = math.min(x + dash_w, d_x1)
      frame.display.line(x, 120, xe, 120, P.border_subtle)
      x = x + dash_w + gap
    end
  end

  -- New summary (below central divider)
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    text(new_text, CX, 142, P.text_primary, "lg")
  end

  -- Score dot
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) then
    local dot_r = floor(lerp(2, 5, score) * sc)
    if dot_r >= 1 then
      frame.display.circle(CX, 170, dot_r, score_col, true)
      MAT.bloom_ring(CX, 170, dot_r, score_col)
    end
  end

  -- Hold-phase: ripple ring expands outward then resets.
  -- Kill list #4: no fake alpha via arc step-count flicker — the ring dims
  -- honestly through the fx dynamic slot's luma.
  if enter_t >= 1.0 and exit_t == 0 then
    local ripple_period = 2400  -- ms per cycle
    local rp = (idle_t % ripple_period) / ripple_period
    local rr = floor(lerp(6, 44, rp) * sc)
    if rr >= 4 then
      P.set_dynamic_y("fx", (1.0 - rp) * 520)
      arc(CX, CY, rr, 0, 360, P.dynamic_color("fx"), 20)
    end
  end
end

-- ---------------------------------------------------------------------------
-- TruthLensCard — the Testimony Thread (Meridian, docs/cinema_v2/testimony.md)
-- Replaces the v1 9-ring gauge (CINEMA_V2_DELTAS.md §5). The nine pipeline
-- stages draw as ONE arc at TESTIMONY_R, accumulating clockwise from 12 in
-- stage order after the Truth Ripple lands: truthful = continuous stroke in
-- accent_success, deceptive = torn (3 dashes, ±TESTIMONY_TEAR_PX radial
-- jitter) in accent_attention, insufficient = an honest empty slot. Slot
-- boundaries are 1px ghost ticks (ordinal addressability without labels).
-- Center: verdict word + backing capsule (v1's armor was right) +
-- confidence dot. thread_t: 0..1 accumulation progress (1 when settled).
-- ---------------------------------------------------------------------------
local TESTIMONY_DIR_COLOR = {
  truthful  = P.accent_success,
  deceptive = P.accent_attention,
}
-- Solid: older testimony cools to the dim twin — temporal order becomes
-- a visible bit (bright = the newest evidence), direction hue preserved
local TESTIMONY_DIR_DIM = {
  truthful  = P.accent_success_dim,
  deceptive = P.accent_attention_dim,
}

local function draw_testimony_stage(i, stage, fraction, bright)
  local dir = stage.direction or "insufficient"
  if dir == "insufficient" then return end
  local conf = clamp(stage.confidence or 0, 0, 1)
  local a0 = -90 + (i - 1) * A.TESTIMONY_SLOT_DEG + 2
  local span = conf * (A.TESTIMONY_SLOT_DEG - 4) * clamp(fraction, 0, 1)
  if span <= 1 then return end
  local color = bright and TESTIMONY_DIR_COLOR[dir]
                       or  TESTIMONY_DIR_DIM[dir]
  if dir == "truthful" then
    arc(CX, CY, A.TESTIMONY_R, a0, a0 + span, color, 12)
  else
    local dash = span / 4
    local offsets = { -A.TESTIMONY_TEAR_PX, A.TESTIMONY_TEAR_PX, -A.TESTIMONY_TEAR_PX }
    for d = 1, 3 do
      local da0 = a0 + (d - 1) * (dash + dash / 2)
      local da1 = math.min(da0 + dash, a0 + span)
      if da1 > da0 then
        arc(CX, CY, A.TESTIMONY_R + offsets[d], da0, da1, color, 4)
      end
    end
  end
end

-- one deterministic 3-shard spit as each torn stage reveals (Lumen);
-- keyed per stage, reset on every show_card
local _tear_fired = {}

local function draw_testimony(card, sc, enter_t, exit_t, idle_t, thread_t)
  local stages  = card.stages or {}
  local verdict = card.verdict or card.primary or ""
  local conf    = card.confidence
  thread_t = TR.reduce_motion() and 1 or (thread_t or 1)

  -- slot boundary ticks (compass rose of the pipeline)
  for i = 0, 8 do
    local deg = math.rad(-90 + i * A.TESTIMONY_SLOT_DEG)
    local x1 = CX + (A.TESTIMONY_R - 2) * math.cos(deg)
    local y1 = CY + (A.TESTIMONY_R - 2) * math.sin(deg)
    local x2 = CX + (A.TESTIMONY_R + 2) * math.cos(deg)
    local y2 = CY + (A.TESTIMONY_R + 2) * math.sin(deg)
    frame.display.line(floor(x1), floor(y1), floor(x2), floor(y2), P.border_subtle)
  end

  -- the thread accumulates in stage order: stage i draws over
  -- [(i-1)/9, i/9] of thread_t. Solid: the newest revealed stage is the
  -- bright one; everything older has cooled to its dim twin.
  local newest = math.min(9, math.floor(thread_t * 9) + 1)
  for i = 1, 9 do
    local stage = stages[i]
    if stage then
      local fraction = clamp(thread_t * 9 - (i - 1), 0, 1)
      draw_testimony_stage(i, stage, fraction, i >= newest)
      -- a torn stage spits three fragments the moment it reveals — the
      -- thread visibly fails to hold there (deterministic per stage)
      if stage.direction == "deceptive" and fraction > 0
         and not _tear_fired[i] and not TR.reduce_motion() then
        _tear_fired[i] = true
        local mid = math.rad(-90 + (i - 0.5) * A.TESTIMONY_SLOT_DEG)
        PT.burst(CX + A.TESTIMONY_R * math.cos(mid),
                 CY + A.TESTIMONY_R * math.sin(mid),
                 A.TEAR_SPIT_N,
                 { t0 = _now_ms(), seed = i * 31, speed = 22,
                   ttl_ms = A.TEAR_SPIT_MS, color = P.accent_attention })
      end
    end
  end

  -- Lumen: once the thread settles, light runs its path once — a glint
  -- travels the full nine slots and is gone (enter-adjacent, one-shot)
  if thread_t >= 1 and idle_t and idle_t > 0 and idle_t < A.SPEC_SWEEP_MS
     and not TR.reduce_motion() then
    local st = idle_t / A.SPEC_SWEEP_MS
    local g0 = -90 + (360 - 12) * ease_in_out_sine(st)
    arc(CX, CY, A.TESTIMONY_R + 1, g0, g0 + 12, P.confidence_high, 3)
  end

  -- verdict first, evidence second: word appears with the ripple landing.
  -- Solid: the verdict sits in a glass capsule in hero-class type — the
  -- reading of the card, weighted like one.
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    local vsize  = T.fit_size(verdict, 130, { "hero", "xl", "lg" })
    local half_w = floor(#verdict * T.avg_w_with_tracking(vsize, 0) / 2) + 10
    half_w = math.max(half_w, 26)
    frame.display.rect(CX - half_w, CY - 16, half_w * 2, 33, P.background, true)
    if exit_t == 0 then
      MAT.glass_capsule(CX - half_w, CY - 16, half_w * 2, 32, MAT.PANE, 3)
    end
    -- capsule outline: two rails + rounded ends
    local cr = 16
    frame.display.line(CX - half_w + cr, CY - 16,
                       CX + half_w - cr, CY - 16, P.border_subtle)
    frame.display.line(CX - half_w + cr, CY + 16,
                       CX + half_w - cr, CY + 16, P.border_subtle)
    arc(CX - half_w + cr, CY, cr,  90, 270, P.border_subtle, 6)
    arc(CX + half_w - cr, CY, cr, -90,  90, P.border_subtle, 6)
    text(verdict, CX, CY, P.text_primary, vsize)
  end
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) and conf then
    local jcol = (conf >= 0.75 and P.confidence_high)
              or (conf >= 0.40 and P.confidence_med)
              or  P.confidence_low
    frame.display.circle(CX, CY + 26, 3, jcol, true)
  end
end

-- ---------------------------------------------------------------------------
-- Layout-driven cards (ForgetLast / PrivateZone / ConsentRequired /
-- LiveCaption). These payloads self-describe via card.layout (hud/cards.py
-- builds it); v1 queued them URGENT and then drew NOTHING for them — a
-- consent prompt rendered as a black screen (found during the Meridian
-- golden pass; the committed goldens were black discs too). One generic
-- renderer honors the layout on both sides.
-- ---------------------------------------------------------------------------
local function draw_layout_card(card, sc, enter_t, exit_t)
  local layout = card.layout or {}
  local function row(name, str, fallback_y, fallback_color, stagger_ms, size)
    if not str or str == "" then return end
    if not layer_ok(enter_t, stagger_ms) then return end
    local spec = layout[name] or {}
    text(str, floor(spec.x or CX), floor(spec.y or fallback_y),
         spec.color or fallback_color, spec.size or size)
  end
  -- Solid: layout cards sit on the glass bed too — EXCEPT privacy-class ones
  -- (they carry a shield/lock glyph; "privacy cards get no pane" stands).
  local privacy = layout.shield ~= nil or layout.lock ~= nil
  if not privacy and layer_ok(enter_t, A.STAGGER_PRIMARY_MS) and exit_t == 0 then
    MAT.glass_disc(CX, 128, floor(74*sc), MAT.PANE, 4)
  end
  local sep = layout.separator
  if sep and layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    if privacy then
      frame.display.line(floor(sep.x1 or 48), floor(sep.y or 80),
                         floor(sep.x2 or 208), floor(sep.y or 80),
                         P.border_subtle)
    else
      MAT.grad_line(floor(sep.x1 or 48), floor(sep.y or 80),
                    floor(sep.x2 or 208), floor(sep.y or 80), MAT.RAMP_MEMORY)
    end
  end
  local glyph = layout.shield or layout.lock
  if glyph and layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    shield_glyph(floor(glyph.x or CX), floor(glyph.y or 44),
                 floor((glyph.r or 10) * 2 * sc), glyph.color or P.privacy_caution,
                 layout.shield ~= nil)
  end
  row("eyebrow", card.eyebrow, 64, P.text_secondary, A.STAGGER_EYEBROW_MS, "sm")
  row("primary", card.primary, 112, P.text_primary,  A.STAGGER_PRIMARY_MS, "lg")
  row("detail",  card.detail,  144, P.text_secondary, A.STAGGER_DETAIL_MS, "md")
  row("footer",  card.footer,  168, P.text_ghost,     A.STAGGER_FOOTER_MS, "sm")
  if card.confidence and layout.conf_dot then
    local d = layout.conf_dot
    local jcol = (card.confidence >= 0.75 and P.confidence_high)
              or (card.confidence >= 0.40 and P.confidence_med)
              or  P.confidence_low
    frame.display.circle(floor(d.x or CX), floor(d.y or 185), d.r or 3, jcol, true)
  end
end

-- ---------------------------------------------------------------------------
-- O3 conversation cards (Meridian Solid + Lumen). Same material language as the
-- hero cards: a surface-luma glass pane (panes never draw during exit), gradient
-- separators, a bloomed status cue that spring-settles in, hero-class type via
-- the fit ladder (wrapped for spoken sentences), secondary text cooled to the
-- verdict/tone dim twin. reduce_motion: springs collapse to their still pose and
-- the idle breathe is skipped; the materials stay (static richness, not motion).
-- ---------------------------------------------------------------------------

-- Verdict/tone mapping lives HERE, not in the cards.lua constructors:
-- the real BLE pipeline (main.lua -> queue -> renderer) delivers host
-- payloads that never pass through a constructor, so a draw fn may only
-- rely on semantic fields (verdict / importance / kind). Found by the
-- standards review of #86 — every BLE-delivered FactCheck rendered its
-- verdict cue ghost-gray.
local FACT_COLOR = {
  supported          = P.accent_success,
  disputed           = P.warning_amber,
  self_contradiction = P.accent_attention,
  unverified         = P.text_ghost_static,
}
local FACT_DIM = {
  supported          = P.accent_success_dim,
  disputed           = P.warning_amber_dim,
  self_contradiction = P.accent_attention_dim,
  unverified         = P.border_subtle,
}

--- The card's semantic accent, derived from its own fields — used for
--- the focus travel/landing color so BLE-delivered cards match their
--- verdict/tone even without a constructor-set conf_color.
local function card_tone(card)
  if not card then return nil end
  if card.type == "FactCheckCard" then
    return FACT_COLOR[card.verdict]
  elseif card.type == "HarkCard" then
    return card.importance == "urgent" and P.warning_amber
                                        or P.accent_memory
  elseif card.type == "OracleReplyCard" then
    return card.kind == "action" and P.accent_success or P.accent_memory
  elseif card.type == "ScholarCard" or card.type == "TasteCard" then
    -- the honest "connect a Brain" state tones ghost; a real read is memory
    return card.unavailable and P.text_ghost_static or P.accent_memory
  elseif card.type == "GlanceChoiceCard" then
    return P.accent_memory
  elseif card.type == "UpcomingCard" then
    -- an event within 5 min warms to amber (the travel ring matches)
    return (tonumber(card.minutes) or 99) <= 5 and P.warning_amber
                                                or P.accent_memory
  end
  return nil
end

local function draw_oracle_reply(card, sc, enter_t, exit_t)
  local action = card.kind == "action"
  local accent = action and P.accent_success or P.accent_memory
  local ramp   = action and MAT.RAMP_SUCCESS or MAT.RAMP_MEMORY
  local body   = card.primary or ""
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) and exit_t == 0 then
    MAT.glass_disc(CX, 132, floor(78*sc), MAT.PANE, 4)
  end
  frame.display.circle(CX, 132, floor(82*sc), P.border_subtle, false)
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    frame.display.circle(CX-40, 64, 3, accent, true)
    MAT.bloom_ring(CX-40, 64, 3, accent)
    text("ORACLE", CX+6, 64, accent, "sm")
    MAT.grad_line(60, 82, 196, 82, ramp)
  end
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    if #body <= 20 then
      text(body, CX, 132, P.text_primary, T.fit_size(body, 200))
    else
      text_block(body, CX, 128, P.text_primary, "md", 182, 3)
    end
  end
end

local function draw_answer_ahead(card, sc, enter_t, exit_t)
  local answer   = card.primary or ""
  local question = card.detail  or ""
  local footer   = card.footer  or ""
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) and exit_t == 0 then
    MAT.glass_disc(CX, 128, floor(78*sc), MAT.PANE, 4)
  end
  frame.display.circle(CX, 128, floor(82*sc), P.border_subtle, false)
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    -- dot sits clear of the 25-char eyebrow (its bloom was grazing the
    -- first glyph — found in the golden eyeball pass)
    frame.display.circle(CX-88, 70, 3, P.accent_memory, true)
    MAT.bloom_ring(CX-88, 70, 3, P.accent_memory)
    text(card.eyebrow or "ON THE TIP OF YOUR TONGUE", CX+4, 70, P.accent_memory, "sm")
    MAT.grad_line(52, 88, 204, 88, MAT.RAMP_MEMORY)
  end
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    if #answer <= 22 then
      text(answer, CX, 126, P.text_primary, T.fit_size(answer, 196))
    else
      text_block(answer, CX, 122, P.text_primary, "md", 188, 2)
    end
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) and question ~= "" then
    text(T.truncate(question, "sm", 200), CX, 166, P.accent_memory_dim, "sm")
  end
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) and footer ~= "" then
    text(footer, CX, 198, P.text_ghost, "sm")
  end
end

local function draw_fact_check(card, sc, enter_t, exit_t, idle_t)
  local color = FACT_COLOR[card.verdict] or card.conf_color
                or P.text_ghost_static
  local dim   = FACT_DIM[card.verdict] or P.border_subtle
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) and exit_t == 0 then
    MAT.glass_disc(CX, 134, floor(74*sc), MAT.PANE, 4)
  end
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    -- the status cue springs in, then blooms; disputed/contradiction pulse once
    local rp = E.spring(math.min(1, enter_t*2), A.SPRING_ZETA_SNAPPY, A.SPRING_OMEGA)
    frame.display.circle(CX, 54, math.max(2, floor(9*rp)), color, false)
    MAT.bloom_ring(CX, 54, 9, color)
    if idle_t and idle_t < A.FACT_PULSE_MS and not TR.reduce_motion()
       and (card.verdict == "self_contradiction" or card.verdict == "disputed") then
      local ph = idle_t / A.FACT_PULSE_MS
      frame.display.circle(CX, 54, floor(9 + 11*math.sin(ph*math.pi)), dim, false)
    end
    text(card.eyebrow or "", CX, 82, color, "sm")
    MAT.grad_line(44, 96, 212, 96, { color, dim, P.border_subtle })
  end
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    local claim = card.primary or ""
    if #claim <= 22 then
      text(claim, CX, 130, P.text_primary, T.fit_size(claim, 200))
    else
      text_block(claim, CX, 126, P.text_primary, "md", 188, 2)
    end
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) and (card.detail or "") ~= "" then
    text(T.truncate(card.detail, "sm", 210), CX, 170, dim, "sm")
  end
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) and (card.footer or "") ~= "" then
    text(card.footer, CX, 200, P.text_ghost, "sm")
  end
end

local function draw_hark(card, sc, enter_t, exit_t, idle_t)
  local urgent = card.importance == "urgent"
  local color  = urgent and P.warning_amber or P.accent_memory
  local dim    = urgent and P.warning_amber_dim or P.accent_memory_dim
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) and exit_t == 0 then
    MAT.glass_disc(CX, 134, floor(74*sc), MAT.PANE, 4)
  end
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    local rp = E.spring(math.min(1, enter_t*2), A.SPRING_ZETA_SNAPPY, A.SPRING_OMEGA)
    frame.display.circle(CX, 58, math.max(3, floor(12*rp)), color, false)
    frame.display.circle(CX, 58, 3, color, true)
    MAT.bloom_ring(CX, 58, 12, color)
    -- "Listen!": the ring breathes on hold to catch the eye (urgent breathes harder)
    if idle_t and not TR.reduce_motion() then
      local period = urgent and A.HARK_BREATHE_URGENT_MS
                             or  A.HARK_BREATHE_MS
      local ph = (idle_t % period) / period
      frame.display.circle(CX, 58, floor(12 + 8*math.sin(ph*math.pi)), dim, false)
    end
    text("LISTEN", CX, 84, color, "sm")
    MAT.grad_line(48, 98, 208, 98, { color, dim, P.border_subtle })
  end
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    local clue = card.primary or ""
    if #clue <= 22 then
      text(clue, CX, 132, P.text_primary, T.fit_size(clue, 200))
    else
      text_block(clue, CX, 128, P.text_primary, "md", 188, 2)
    end
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) and (card.detail or "") ~= "" then
    text(T.truncate(card.detail, "sm", 200), CX, 172, dim, "sm")
  end
end

-- ---------------------------------------------------------------------------
-- World lenses (Scholar / Glance chooser / TasteLens) — Meridian Solid + Lumen,
-- same material language as the O3 cards: a surface-luma glass pane (never
-- during exit), a bloomed status cue that spring-settles in, an eyebrow over a
-- gradient separator, hero-class type via the fit ladder, secondary rows cooled
-- to dim twins. The honest "connect a Brain" state tones ghost, never a guess.
-- ---------------------------------------------------------------------------

-- the ✕ veto mark the TasteLens host emits leads a vetoed row (U+2715)
local VETO_MARK = "\xE2\x9C\x95"

-- shared World-lens bed: pane + eyebrow with a bloomed cue over a separator.
local function world_bed(card, sc, enter_t, exit_t, accent, eyebrow, cue_hollow)
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) and exit_t == 0 then
    MAT.glass_disc(CX, 128, floor(76*sc), MAT.PANE, 4)
  end
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    -- a bloomed cue dot springs in beside the eyebrow (hollow when ghost)
    local rp = E.spring(math.min(1, enter_t*2), A.SPRING_ZETA_SNAPPY, A.SPRING_OMEGA)
    local cw = math.max(2, floor(6*rp))
    frame.display.circle(CX-84, 60, cw, accent, not cue_hollow)
    MAT.bloom_ring(CX-84, 60, 5, accent)
    text(eyebrow, CX+8, 60, accent, "sm")
    MAT.grad_line(44, 76, 212, 76, { accent, P.accent_memory_dim, P.border_subtle })
  end
end

-- stacked info rows for Scholar / Taste: capped, chord-safe, veto rows cooled.
local function world_rows(items, enter_t, y0)
  if not layer_ok(enter_t, A.STAGGER_DETAIL_MS) then return end
  local y = y0
  for i = 1, math.min(#items, 4) do
    if y > 200 then break end            -- stay inside the circular chord
    local row = tostring(items[i] or "")
    if row ~= "" then
      local veto = row:sub(1, #VETO_MARK) == VETO_MARK
      local col  = veto and P.accent_attention_dim or P.text_secondary
      frame.display.circle(30, y, 2, veto and P.accent_attention_dim
                                         or P.accent_memory_dim, true)
      text(T.truncate(row, "sm", 188), CX+6, y, col, "sm")
      y = y + 22
    end
  end
end

local function draw_scholar(card, sc, enter_t, exit_t)
  local unavail = card.unavailable and true or false
  local accent  = unavail and P.text_ghost_static or P.accent_memory
  local eyebrow = (card.eyebrow or "") ~= "" and card.eyebrow
                  or (unavail and "SCHOLAR" or "ANSWER")
  world_bed(card, sc, enter_t, exit_t, accent, eyebrow, unavail)
  local body  = card.primary or ""
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    if body ~= "" then
      if #body <= 22 then
        text(body, CX, 104, P.text_primary, T.fit_size(body, 200))
      else
        text_block(body, CX, 102, P.text_primary, "md", 190, 2)
      end
    elseif unavail then
      text("Connect a Brain", CX, 116, P.text_ghost, "md")
    end
  end
  world_rows(card.items or {}, enter_t, body ~= "" and 138 or 150)
  if (card.detail or "") ~= "" and body == "" and not unavail
     and layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    text(T.truncate(card.detail, "sm", 200), CX, 150, P.text_ghost, "sm")
  end
end

local function draw_taste(card, sc, enter_t, exit_t)
  local unavail = card.unavailable and true or false
  local accent  = unavail and P.text_ghost_static or P.accent_memory
  world_bed(card, sc, enter_t, exit_t, accent,
            (card.eyebrow or "") ~= "" and card.eyebrow or "BEST PICK", unavail)
  local winner = card.primary or ""
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    if winner ~= "" then
      text(winner, CX, 104, P.text_primary, T.fit_size(winner, 200))
      if (card.detail or "") ~= "" then
        text(T.truncate(card.detail, "sm", 200), CX, 128, P.accent_memory_dim, "sm")
      end
    elseif unavail then
      text("Connect a Brain", CX, 116, P.text_ghost, "md")
    end
  end
  world_rows(card.items or {}, enter_t, winner ~= "" and 150 or 138)
end

-- Glance chooser: up to three option nodes on an upper arc, each a bloomed dot
-- with its label just inside the ring. A circular-native interaction surface —
-- the options live AROUND the ring, not stacked as a line (docstring intent).
local GLANCE_ANGLES = {
  [1] = { -90 },
  [2] = { -120, -60 },
  [3] = { -150, -90, -30 },
}

local function draw_glance_choice(card, sc, enter_t, exit_t)
  local opts = {}
  for _, o in ipairs(card.options or {}) do
    if o and o.label and o.label ~= "" then opts[#opts+1] = o.label end
    if #opts >= 3 then break end
  end
  local n = #opts
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) and exit_t == 0 then
    MAT.glass_disc(CX, 128, floor(72*sc), MAT.PANE, 4)
  end
  if (card.scene or "") ~= "" and layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    text(T.truncate(card.scene, "md", 150), CX, 128, P.text_secondary, "md")
  end
  local angles = GLANCE_ANGLES[n] or {}
  for i = 1, n do
    local rp = TR.reduce_motion() and 1
               or E.spring(clamp(enter_t*2 - (i-1)*0.3, 0, 1),
                           A.SPRING_ZETA_SNAPPY, A.SPRING_OMEGA)
    if rp > 0.05 then
      local rad = math.rad(angles[i])
      local r   = A.GLANCE_NODE_R * rp
      local nx  = CX + r * math.cos(rad)
      local ny  = CY + r * math.sin(rad)
      frame.display.circle(floor(nx), floor(ny), 4, P.accent_memory, true)
      MAT.bloom_ring(floor(nx), floor(ny), 4, P.accent_memory)
      if rp > 0.9 then
        local lx = CX + (r-20) * math.cos(rad)
        local ly = CY + (r-20) * math.sin(rad)
        text(T.truncate(opts[i], "sm", 96), floor(lx), floor(ly),
             P.text_primary, "sm")
      end
    end
  end
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    text(card.eyebrow or "WHAT DO YOU WANT?", CX, 200, P.accent_memory, "sm")
  end
end

-- ---------------------------------------------------------------------------
-- Missing frames (Meridian Solid + Lumen). Seven glass-bound cards that had no
-- device renderer and drew a black frame on the real BLE path. Same material
-- language as the O3 / World-lens cards: the world_bed pane+cue+separator, hero
-- type via the fit ladder / text_block, secondary cooled to dim twins.
-- ---------------------------------------------------------------------------

-- ListeningCard: Oracle's wake-acknowledgment cue — a soft pulse ring that
-- breathes on hold (reduce_motion: a still ring), distinct from the active
-- capture waveform (draw_query_listening). Not the same card.
local function draw_listening(card, sc, enter_t, exit_t, idle_t)
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) and exit_t == 0 then
    MAT.glass_disc(CX, 118, floor(74*sc), MAT.PANE, 4)
  end
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    -- the wake ring springs in, then breathes to signal "I'm listening"
    local rp = E.spring(math.min(1, enter_t*2), A.SPRING_ZETA_SNAPPY, A.SPRING_OMEGA)
    local base = floor(28*rp)
    frame.display.circle(CX, 104, base, P.accent_memory, false)
    MAT.bloom_ring(CX, 104, base, P.accent_memory)
    if idle_t and not TR.reduce_motion() then
      local ph = (idle_t % A.LISTEN_PULSE_MS) / A.LISTEN_PULSE_MS
      frame.display.circle(CX, 104, floor(base + 10*math.sin(ph*math.pi)),
                           P.accent_memory_dim, false)
    end
    frame.display.circle(CX, 104, 3, P.accent_memory, true)
  end
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    text(card.eyebrow or "ORACLE", CX, 158, P.accent_memory, "sm")
    text(card.primary or "Listening\xE2\x80\xA6", CX, 180, P.text_primary, "md")
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) and (card.detail or "") ~= "" then
    text(card.detail, CX, 202, P.text_ghost, "sm")
  end
end

-- MessageCard: a text/email arriving. Channel cue (Text/Mail) as the eyebrow,
-- sender in hero, body wrapped, a quiet reply/dismiss affordance hint.
local function draw_message(card, sc, enter_t, exit_t)
  local kind = card.headline or "Text"
  world_bed(card, sc, enter_t, exit_t, P.accent_memory, kind:upper(), false)
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    text(T.truncate(card.primary or "Message", "lg", 190), CX, 104,
         P.text_primary, T.fit_size(card.primary or "Message", 190, {"hero","xl","lg"}))
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) and (card.detail or "") ~= "" then
    text_block(card.detail, CX, 142, P.text_secondary, "sm", 190, 2)
  end
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) then
    text("tap to reply", CX, 198, P.accent_memory_dim, "sm")
  end
end

-- UpcomingCard: an event about to start. The "when" (in N min / now) is the
-- bloomed hero cue; warms to amber as the minutes run out.
local function draw_upcoming(card, sc, enter_t, exit_t)
  local soon  = (tonumber(card.minutes) or 99) <= 5
  local accent = soon and P.warning_amber or P.accent_memory
  world_bed(card, sc, enter_t, exit_t, accent,
            (card.headline or "SOON"):upper(), false)
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    text(T.truncate(card.primary or "", "lg", 196), CX, 108, P.text_primary,
         T.fit_size(card.primary or "", 196, {"hero","xl","lg"}))
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) and (card.detail or "") ~= "" then
    text(T.truncate(card.detail, "sm", 196), CX, 148, accent, "sm")
  end
end

-- HereCard: something you left is right here, surfaced as you arrive.
local function draw_here(card, sc, enter_t, exit_t)
  world_bed(card, sc, enter_t, exit_t, P.accent_memory,
            (card.headline or "you left this here"):upper(), false)
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    text(T.truncate(card.primary or "", "lg", 196), CX, 108, P.text_primary,
         T.fit_size(card.primary or "", 196, {"hero","xl","lg"}))
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) and (card.detail or "") ~= "" then
    text(T.truncate(card.detail, "sm", 196), CX, 150, P.accent_memory_dim, "sm")
  end
end

-- PersonDossierCard: "YOU KNOW" — the conversation ledger for a person.
local function draw_person_dossier(card, sc, enter_t, exit_t)
  world_bed(card, sc, enter_t, exit_t, P.accent_memory,
            card.eyebrow or "YOU KNOW", false)
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    text(T.truncate(card.person or card.primary or "", "hero", 200), CX, 104,
         P.text_primary, T.fit_size(card.person or card.primary or "", 200, {"hero","xl"}))
    if (card.headline or "") ~= "" then
      text(T.truncate(card.headline, "sm", 200), CX, 130, P.accent_memory_dim, "sm")
    end
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) and (card.detail or "") ~= "" then
    text(T.truncate(card.detail, "sm", 200), CX, 158, P.text_secondary, "sm")
  end
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) and (card.footer or "") ~= "" then
    text(T.truncate(card.footer, "sm", 200), CX, 184, P.text_ghost, "sm")
  end
end

-- SpokenCaptionCard: a live caption of what a familiar voice just said.
local function draw_spoken_caption(card, sc, enter_t, exit_t)
  world_bed(card, sc, enter_t, exit_t, P.accent_memory,
            card.eyebrow or "HEARD", false)
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    local body = card.primary or ""
    if #body <= 20 then
      text(body, CX, 116, P.text_primary, T.fit_size(body, 200, {"xl","lg","md"}))
    else
      text_block(body, CX, 116, P.text_primary, "md", 194, 3)
    end
  end
end

-- MorningBriefCard: "YOUR DAY" — the wake brief, with up to three bullets.
local function draw_morning_brief(card, sc, enter_t, exit_t)
  world_bed(card, sc, enter_t, exit_t, P.accent_memory,
            card.eyebrow or "YOUR DAY", false)
  local bullets = card.bullets or {}
  if #bullets == 0 then
    for _, k in ipairs({ card.detail, card.footer }) do
      if k and k ~= "" then bullets[#bullets+1] = k end
    end
  end
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    local body = card.primary or ""
    if #body <= 22 then
      text(body, CX, 104, P.text_primary, T.fit_size(body, 196))
    else
      text_block(body, CX, 102, P.text_primary, "md", 190, 2)
    end
  end
  world_rows(bullets, enter_t, #(card.primary or "") <= 22 and 138 or 150)
end

-- ---------------------------------------------------------------------------
-- Dispatch table
-- Each entry: function(card, sc, enter_t, exit_t, idle_t)
-- sc      = effective scale factor (0→1 for enter, 1→0 for exit)
-- enter_t = raw 0→1 (used for stagger thresholds; 1.0 during hold/exit)
-- exit_t  = raw 0→1 (0 until exit begins)
-- idle_t  = ms elapsed in hold phase (for spinning/waving/pulsing)
-- ---------------------------------------------------------------------------
local DRAW = {
  ReadyCard             = function(c,sc,et,xt,it) draw_ready(sc,et,xt)                    end,
  SavedMemoryCard       = function(c,sc,et,xt,it) draw_saved_memory(c,sc,et,xt,it)        end,
  QueryListeningCard    = function(c,sc,et,xt,it) draw_query_listening(sc,et,it)           end,
  LoadingCard           = function(c,sc,et,xt,it) draw_loading(sc,et,it)                  end,
  ObjectRecallCard      = function(c,sc,et,xt,it) draw_object_recall(c,sc,et,xt)          end,
  CommitmentRecallCard  = function(c,sc,et,xt,it) draw_commitment_recall(c,sc,et,xt)      end,
  ProactiveMemoryCard   = function(c,sc,et,xt,it) draw_proactive_memory(c,sc,et,xt)       end,
  PersonContextCard     = function(c,sc,et,xt,it) draw_person_context(c,sc,et,xt)         end,
  PrivacyVeilCard     = function(c,sc,et,xt,it) draw_privacy_veil(sc,et,xt)           end,
  ErrorCard             = function(c,sc,et,xt,it) draw_error(c,sc,et,xt)                  end,
  LowConfidenceCard     = function(c,sc,et,xt,it) draw_low_confidence(sc,et,xt)           end,
  -- new engines
  CommitmentDriftCard   = function(c,sc,et,xt,it) draw_commitment_drift(c,sc,et,xt,it)    end,
  TimeScrubNodeCard     = function(c,sc,et,xt,it) draw_time_scrub_node(c,sc,et,xt,it)     end,
  DeviationAlertCard    = function(c,sc,et,xt,it) draw_deviation_alert(c,sc,et,xt,it)     end,
  -- Meridian lens presentation
  TruthLensCard         = function(c,sc,et,xt,it,tt) draw_testimony(c,sc,et,xt,it,tt)     end,
  -- O3 conversation cards (Meridian Solid + Lumen)
  FactCheckCard         = function(c,sc,et,xt,it) draw_fact_check(c,sc,et,xt,it)          end,
  AnswerAheadCard       = function(c,sc,et,xt,it) draw_answer_ahead(c,sc,et,xt)           end,
  OracleReplyCard       = function(c,sc,et,xt,it) draw_oracle_reply(c,sc,et,xt)           end,
  HarkCard              = function(c,sc,et,xt,it) draw_hark(c,sc,et,xt,it)                end,
  -- World lenses (Meridian Solid + Lumen)
  ScholarCard           = function(c,sc,et,xt,it) draw_scholar(c,sc,et,xt)               end,
  GlanceChoiceCard      = function(c,sc,et,xt,it) draw_glance_choice(c,sc,et,xt)          end,
  TasteCard             = function(c,sc,et,xt,it) draw_taste(c,sc,et,xt)                  end,
  -- Missing frames (Meridian Solid + Lumen) — were black on the BLE path
  ListeningCard         = function(c,sc,et,xt,it) draw_listening(c,sc,et,xt,it)          end,
  MessageCard           = function(c,sc,et,xt,it) draw_message(c,sc,et,xt)               end,
  UpcomingCard          = function(c,sc,et,xt,it) draw_upcoming(c,sc,et,xt)              end,
  HereCard              = function(c,sc,et,xt,it) draw_here(c,sc,et,xt)                  end,
  PersonDossierCard     = function(c,sc,et,xt,it) draw_person_dossier(c,sc,et,xt)        end,
  SpokenCaptionCard     = function(c,sc,et,xt,it) draw_spoken_caption(c,sc,et,xt)        end,
  MorningBriefCard      = function(c,sc,et,xt,it) draw_morning_brief(c,sc,et,xt)         end,
  -- layout-driven cards (v1 queued these and drew nothing — see
  -- draw_layout_card)
  ForgetLastCard        = function(c,sc,et,xt,it) draw_layout_card(c,sc,et,xt)            end,
  PrivateZoneCard       = function(c,sc,et,xt,it) draw_layout_card(c,sc,et,xt)            end,
  ConsentRequiredCard   = function(c,sc,et,xt,it) draw_layout_card(c,sc,et,xt)            end,
  LiveCaptionCard       = function(c,sc,et,xt,it) draw_layout_card(c,sc,et,xt)            end,
}

-- ---------------------------------------------------------------------------
-- Signature routing (Meridian, docs/cinema_v2/focus.md)
-- enter: focus (default — condense from the card's horizon angle) |
--        ripple (Truth Lens: S5 ripple + testimony accumulation) |
--        slam (privacy class, unchanged)
-- hold : ring (static focus ring, sweep = confidence) on recall cards;
--        card-specific idles stay in the DRAW fns
-- release: recede (shared) — privacy-class cards hard-cut instead
-- ---------------------------------------------------------------------------
-- flair (Lumen): a one-shot hero accent fired when the card reaches HOLD
-- — a particle burst, or a leased light program over the card's banded
-- geometry. Flairs are additive: they never carry information the
-- geometry underneath doesn't, and reduce_motion skips them entirely.
local SIGNATURES = {
  ObjectRecallCard     = { enter = "focus", hold = "ring",
                           flair = "conduct" },
  CommitmentRecallCard = { enter = "focus", hold = "ring" },
  ProactiveMemoryCard  = { enter = "focus", hold = "ring" },
  PersonContextCard    = { enter = "focus", hold = "ring" },
  SavedMemoryCard      = { enter = "focus", flair = "burst" },
  LoadingCard          = { enter = "focus", flair = "chase" },
  TruthLensCard        = { enter = "ripple" },   -- thread is its own gauge
  PrivacyVeilCard    = { enter = "slam" },
  ConsentRequiredCard  = { enter = "slam" },
  ForgetLastCard       = { enter = "slam" },
  PrivateZoneCard      = { enter = "slam" },
}

-- privacy-class cards never leave a mark and never recede (no residue)
local PRIVACY_CLASS = {
  PrivacyVeilCard = true, ConsentRequiredCard = true,
  ForgetLastCard = true, PrivateZoneCard = true,
}

local DEFAULT_SIGNATURE = { enter = "focus" }

local function signature_for(card)
  return (card and SIGNATURES[card.type]) or DEFAULT_SIGNATURE
end

--- Fire a card's flair as it reaches HOLD. "card_light" is the single id
--- for any card-owned light program: show_card/dismiss stop it, so a
--- crossfade can never leave two programs fighting over the card slots.
local function fire_flair(card, now)
  local sig = signature_for(card)
  if not sig.flair or TR.reduce_motion() then return end
  if sig.flair == "burst" then
    PT.burst(CX, CY, A.BURST_N,
             { t0 = now, seed = floor(F.origin_or_now(card) * 7),
               color = P.accent_success })
  elseif sig.flair == "chase" then
    PA.run("card_light",
           { kind = "wave", names = { "card_a", "card_b", "card_c" },
             period_ms = A.SPINNER_RPM_MS, y_amp = A.CHASE_Y_AMP })
  elseif sig.flair == "conduct" then
    PA.run("card_light",
           { kind = "wave", names = { "card_a", "card_b" },
             period_ms = A.CONDUCT_PERIOD_MS, y_amp = A.CONDUCT_Y_AMP })
  end
end

local function enter_ms_for(card)
  local sig = signature_for(card)
  if sig.enter == "slam" then return A.ENTER_DURATION_MS end
  if sig.enter == "ripple" then
    if TR.reduce_motion() then return 0 end
    return A.SIG_RIPPLE_MS + 9 * A.TESTIMONY_STAGE_MS
  end
  return F.enter_ms()
end

-- ---------------------------------------------------------------------------
-- Safety net: any card the host sends whose type has no draw fn used to hit
-- `if not fn then return end` and render a black frame for its whole dismiss
-- window (the failure class that black-framed the O3 / World-lens / missing
-- cards in turn). Now an unmapped type falls back to the layout renderer when
-- it carries a `layout`, else a minimal titled Solid card — never pure black.
-- ---------------------------------------------------------------------------
local function draw_fallback(card, sc, enter_t, exit_t)
  if type(card.layout) == "table" then
    draw_layout_card(card, sc, enter_t, exit_t)
    return
  end
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) and exit_t == 0 then
    MAT.glass_disc(CX, 128, floor(70*sc), MAT.PANE, 4)
  end
  local title = card.primary or card.eyebrow or card.headline
                or (card.type or "Card"):gsub("Card$", "")
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    text(T.truncate(title, "md", 196), CX, 122, P.text_primary,
         T.fit_size(title, 196, {"lg","md"}))
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) and (card.detail or "") ~= "" then
    text(T.truncate(card.detail, "sm", 196), CX, 150, P.text_secondary, "sm")
  end
end

-- ---------------------------------------------------------------------------
-- Internal composite: draw one card, routed through the Focus law.
-- CONDENSE — travel (content absent) then landing (ring gates staggered
--            content); ripple/slam keep their special entries
-- HOLD     — static focus ring (sweep = confidence) on recall cards + idle
-- RECEDE   — exit_contract: geometry contracts, text cuts at t=0.4, head
--            flies home (privacy-class cards hard-cut, no flight)
-- ---------------------------------------------------------------------------
local function composite(card, phase, elapsed_ms, idle_t)
  if not card then return end
  local fn = DRAW[card.type] or draw_fallback
  local sig = signature_for(card)
  local origin_deg = F.origin_or_now(card)

  local enter_t, exit_t, sc

  if phase == "enter" then
    local dur = enter_ms_for(card)
    local raw = (dur <= 0) and 1.0 or clamp(elapsed_ms / dur, 0, 1)
    exit_t = 0
    sc     = 1.0   -- v1 kill list #1 stands: no uniform scale wobble

    if sig.enter == "focus" and not TR.reduce_motion() then
      if elapsed_ms < A.SIG_FOCUS_TRAVEL_MS then
        -- travel: the head flies in from the card's horizon angle;
        -- content is not yet on stage
        F.travel(elapsed_ms / A.SIG_FOCUS_TRAVEL_MS, origin_deg,
                 card.conf_color or card_tone(card) or P.accent_memory)
        return
      end
      -- landing: ring collapse gates the staggered content layers
      local land_t = clamp((elapsed_ms - A.SIG_FOCUS_TRAVEL_MS)
                           / A.SIG_FOCUS_LAND_MS, 0, 1)
      enter_t = land_t
      fn(card, sc, enter_t, exit_t, idle_t or 0)
      F.landing_ring(land_t,
                     card.conf_color or card_tone(card) or P.accent_memory)
      return
    end

    if sig.enter == "slam" then
      -- sub-bass rumble dims the ambient field before the shield slams
      TR.rumble(clamp(elapsed_ms / A.SIG_RUMBLE_MS, 0, 1))
    end

    enter_t = raw
    if sig.enter == "ripple" then
      -- verdict with the ripple, evidence after: thread_t covers the
      -- accumulation window that follows SIG_RIPPLE_MS
      local ripple_t = (dur <= 0) and 1
                     or clamp(elapsed_ms / A.SIG_RIPPLE_MS, 0, 1)
      local thread_t = (dur <= 0) and 1
                     or clamp((elapsed_ms - A.SIG_RIPPLE_MS)
                              / (9 * A.TESTIMONY_STAGE_MS), 0, 1)
      enter_t = ripple_t
      fn(card, sc, enter_t, exit_t, idle_t or 0, thread_t)
      local origin = card.origin or {}
      TR.truth_ripple(ripple_t, origin.x, origin.y)
      return
    end

    fn(card, sc, enter_t, exit_t, idle_t or 0)

    if sig.enter == "focus" and TR.reduce_motion() then
      -- static variant: full ring sweep + origin tick carry both readings
      if card.confidence then
        F.hold_ring(card.confidence, card.conf_color or P.accent_memory)
      end
      F.origin_tick(origin_deg, card.conf_color or P.accent_memory)
    end
    return

  elseif phase == "exit" then
    local raw = clamp(elapsed_ms / F.recede_ms(), 0, 1)
    if TR.reduce_motion() then raw = 1 end
    exit_t = raw
    local scale, text_ok = TR.exit_contract(raw)
    sc      = scale
    -- enter_t < 0 fails every stagger gate: text cuts, geometry contracts
    enter_t = text_ok and 1.0 or -1.0
    if not PRIVACY_CLASS[card.type] then
      F.recede(raw, origin_deg)
    end

  else -- hold
    enter_t = 1.0
    exit_t  = 0
    sc      = 1.0
    if sig.hold == "ring" and card.confidence then
      -- static focus ring: sweep = confidence; identical under
      -- reduce_motion (the v2 standard). idle_t lets the Lumen glint
      -- run once along the arc as the hold settles.
      F.hold_ring(card.confidence, card.conf_color or P.accent_memory,
                  idle_t)
      if TR.reduce_motion() then
        F.origin_tick(origin_deg, card.conf_color or P.accent_memory)
      end
    end
    if sig.enter == "ripple" then
      -- settled thread (thread_t = 1)
      fn(card, sc, enter_t, exit_t, idle_t or 0, 1)
      return
    end
  end

  fn(card, sc, enter_t, exit_t, idle_t or 0)
end

-- ---------------------------------------------------------------------------
-- Public API
-- ---------------------------------------------------------------------------

--- Wire a monotonic clock function (returns ms as integer).
--- Called once from main.lua boot before the loop starts.
function renderer.bind(disp, time_fn)
  if type(time_fn) == "function" then _now_fn = time_fn end
  -- Reserve the Cinema v1 dynamic palette slots up front so the first
  -- crossfade / ghost fade never pays the reservation cost mid-frame.
  local ok, MAT = pcall(require, "display.materials")
  if ok and MAT then MAT.init() end
end

--- Begin CONDENSE for card.
--- If a card is already visible, it begins its RECESSION while the new
--- card condenses in, offset by SIG_FOCUS_XFADE_LAG_MS — recession is
--- ghost-dim and condensation solid, so exactly one primary motion
--- exists per frame (docs/cinema_v2/focus.md).
function renderer.show_card(card)
  if not card then
    renderer.dismiss()
    return
  end
  -- Honor settings.reduce_motion, read once per card ENTER
  local ok, settings = pcall(require, "system.settings")
  if ok and settings and settings.get then
    TR.set_reduce_motion(settings.get("reduce_motion"))
  end
  local now = _now_ms()
  -- A focused card owns its light: the idle programs yield their slots
  -- (release restores base colors, so nothing arrives mid-shimmer), and
  -- any previous card's light program / voice warmth yields with them
  PA.stop("horizon_aurora")
  PA.stop("premonition_shimmer")
  PA.stop("card_light")
  -- the shared slot behind card_a/voice takes the base the incoming
  -- card draws in: voice orange while listening, band teal otherwise
  if card.type == "QueryListeningCard" then
    P.restore("voice")
  else
    P.restore("card_a")
  end
  _tear_fired = {}
  _amp = 0
  -- If something is showing, capture it as the outgoing card
  if _card and _phase ~= "exit" then
    -- never two simultaneous recessions: a third card mid-crossfade
    -- hard-cuts the receding one (bounded motion complexity per frame)
    _prev_card   = _card
    _prev_exit_t = 0
    _prev_start  = now
    _phase_start = now + (TR.reduce_motion() and 0 or A.SIG_FOCUS_XFADE_LAG_MS)
  else
    _phase_start = now
  end
  _card   = card
  _phase  = "enter"
  _idle_t = 0
end

--- Begin RECEDE for the current card.
function renderer.dismiss()
  if not _card then return end
  if _phase == "exit" then return end  -- already receding
  -- light settles before the recession: no flow on a departing card
  PA.stop("card_light")
  P.restore("card_a")
  _phase       = "exit"
  _phase_start = _now_ms()
end

--- Live voice level from the host ({t="amp"}, v = 0..99). nil-safe;
--- the listening waveform springs toward it (see draw_query_listening).
function renderer.on_amp(msg)
  local v = tonumber(msg and (msg.v or msg.amp))
  if not v then return end
  _amp_target = clamp(v / 99, 0, 1)
end

--- Release a finished recession: the content goes home — its mark pulses
--- on the rim. Privacy-class cards leave nothing (no residue contract).
local function finish_recede(card, now)
  if card and not PRIVACY_CLASS[card.type] then
    HZ.pulse_mark(F.origin_or_now(card), now)
  end
end

--- Advance animations and push one composite frame.
--- Called every tick from main.lua (no args needed; reads clock internally).
--- With no focused card this draws the Horizon — the display's resting
--- state is the wearer's day, never a black screen
--- (docs/cinema_v2/horizon.md; CINEMA_V2_DELTAS.md §6).
-- Idle light programs (Lumen): the aurora flows along the day-ring and
-- the premonition layer breathes — only while the Horizon IS the display.
-- show_card() stops both, so a focused card always owns its light.
local function ensure_idle_light()
  if not PA.active("horizon_aurora") then
    PA.run("horizon_aurora",
           { kind = "wave", names = { "aurora_a", "aurora_b", "aurora_c" } })
  end
  if not PA.active("premonition_shimmer") then
    PA.run("premonition_shimmer", { kind = "shimmer", name = "premo" })
  end
end

function renderer.tick()
  if not HAS_FRAME then return end

  local now = _now_ms()

  -- Lumen engines advance once per frame, before any drawing: parallax
  -- samples the IMU, the palette animator runs its light programs.
  -- While a privacy-class card holds, the world grips: offsets freeze
  -- to zero instantly (nothing about the veil may feel ambient).
  local idle = (not _card and not _prev_card)
  if idle then ensure_idle_light() end   -- register before PA.tick: light
                                         -- flows from the first idle frame
  PX.freeze(_card ~= nil and PRIVACY_CLASS[_card.type] or false)
  PX.tick(now)
  PA.tick(now, TR.reduce_motion())
  local rim_ox, rim_oy = PX.offset("rim")

  if idle then
    -- idle: the Horizon is the display
    frame.display.clear(0x000000)
    HZ.draw({ now_ms = now, reduce_motion = TR.reduce_motion(),
              aurora = true, ox = floor(rim_ox), oy = floor(rim_oy) })
    local air_ox, air_oy = PX.offset("air")
    PT.tick(now, air_ox, air_oy)
    frame.display.show()
    return
  end

  local elapsed = now - _phase_start
  local idle_t  = _idle_t

  -- Advance phase (CONDENSE duration is signature-specific)
  if _phase == "enter" and elapsed >= enter_ms_for(_card) then
    _phase       = "hold"
    _phase_start = now
    elapsed      = 0
    idle_t       = 0
    _idle_t      = 0
    fire_flair(_card, now)   -- Lumen: the card's hero accent, once
  elseif _phase == "hold" then
    _idle_t = _idle_t + 50  -- ~50 ms per tick at frame.sleep(0.05)
    idle_t  = _idle_t
  elseif _phase == "exit" and elapsed >= F.recede_ms() then
    -- Recession complete — focus released, mark pulses
    finish_recede(_card, now)
    _card  = nil
    _phase = nil
    frame.display.clear(0x000000)
    HZ.draw({ now_ms = now, reduce_motion = TR.reduce_motion(),
              ox = floor(rim_ox), oy = floor(rim_oy) })
    frame.display.show()
    return
  end

  -- Advance outgoing recession (its own clock, from show_card)
  if _prev_card then
    local prev_elapsed = now - _prev_start
    _prev_exit_t = clamp(prev_elapsed / F.recede_ms(), 0, 1)
    if TR.reduce_motion() then _prev_exit_t = 1 end
    if _prev_exit_t >= 1 then
      finish_recede(_prev_card, now)
      _prev_card = nil  -- crossfade complete
    end
  end

  -- Composite frame: the day stays under the card, one tier down
  frame.display.clear(0x000000)
  HZ.draw({ now_ms = now, focus = true, reduce_motion = TR.reduce_motion(),
            ox = floor(rim_ox), oy = floor(rim_oy) })

  -- Outgoing card recedes underneath
  if _prev_card then
    composite(_prev_card, "exit", (now - _prev_start), 0)
  end

  -- Incoming card on top (its clock may still be inside the crossfade lag)
  if elapsed >= 0 then
    composite(_card, _phase, elapsed, idle_t)
  end

  -- hero particles ride above the card, below nothing (AIR tier)
  local air_ox, air_oy = PX.offset("air")
  PT.tick(now, air_ox, air_oy)

  frame.display.show()
end

-- Backward-compat stubs
function renderer.show_card_immediate(card)
  -- Used by tests and golden export: skip animation, draw the settled
  -- HOLD state once synchronously (horizon backdrop + ring + content)
  if not HAS_FRAME then return end
  if not card then return end
  local fn = DRAW[card.type] or draw_fallback
  frame.display.clear(0x000000)
  HZ.draw({ now_ms = _now_ms(), focus = true, reduce_motion = true })
  local sig = signature_for(card)
  if sig.hold == "ring" and card.confidence then
    F.hold_ring(card.confidence, card.conf_color or P.accent_memory)
  end
  if sig.enter == "ripple" then
    fn(card, 1.0, 1.0, 0, 0, 1)
  else
    fn(card, 1.0, 1.0, 0, 0)
  end
  frame.display.show()
  _card  = card
  _phase = "hold"
  _phase_start = _now_ms()
  _idle_t = 0
end

function renderer.push(layer, fn)  if fn then fn() end end
function renderer.flush()          end
function renderer.clear()          end

--- The renderer's monotonic clock (bound at boot, os.clock fallback).
--- Exposed so main.lua can stamp memory-mode particle spawns (the dream
--- branch runs on the tick clock; each consumer stays self-consistent).
function renderer.now_ms()         return _now_ms() end

return renderer
