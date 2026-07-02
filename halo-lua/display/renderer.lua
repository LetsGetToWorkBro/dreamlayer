--- display/renderer.lua
--- Halo Cinema v1 transition system for DreamLayer Halo.
---
--- Three animation phases per card, routed per card type through the
--- SIGNATURES table to display/transitions.lua (docs/HALO_CINEMA_V1.md):
---   ENTER  per-signature   iris (default 240ms) | comet (460ms) |
---                          ripple (400ms) — staggered layers throughout
---   HOLD   ∞               confidence_halo on recall cards +
---                          card-specific idle (spinner / waveform / pulse)
---   EXIT   120 ms  linear  exit_contract: geometry contracts, text cuts
---
--- Special behaviours:
---   PrivacyVeilCard   → rumble dim then shield slam (rings, glyph delayed)
---   LoadingCard         → spinner angle advances each tick during HOLD
---   QueryListeningCard  → waveform phase advances each tick during HOLD
---   CommitmentDriftCard → confidence dot pulses during HOLD
---   DeviationAlertCard  → ripple ring expands during HOLD
---   TruthLensCard       → 9-ring gauge, Truth Ripple entry
---   show_card(new) during ENTER/HOLD → Prism Slide: outgoing card refracts
---                                       while the new card irises in
---   settings.reduce_motion → every signature renders its static variant
---
--- Public API (unchanged from callers):
---   renderer.bind(time_fn)     — wire monotonic clock (called once at boot)
---   renderer.show_card(card)   — begin ENTER for card (or crossfade)
---   renderer.dismiss()         — begin EXIT for current card
---   renderer.tick()            — advance animations, composite, push frame
---   renderer.push/flush/clear  — no-op stubs (backward compat)

local math  = math
local P     = require("display.palette")
local T     = require("display.typography")
local A     = require("display.animations")
local E     = require("lib.easing")
local TR    = require("display.transitions")

local HAS_FRAME = (type(_G.frame) == "table")

local ease_out_expo    = E.out_expo
local ease_in_out_sine = E.in_out_sine
local ease_linear      = E.linear

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

local function bezier(p0x,p0y,p1x,p1y,p2x,p2y, color, steps)
  if not HAS_FRAME then return end
  steps = steps or 24
  local px,py = p0x,p0y
  for i = 1,steps do
    local t  = i/steps
    local mt = 1-t
    local x  = mt*mt*p0x + 2*mt*t*p1x + t*t*p2x
    local y  = mt*mt*p0y + 2*mt*t*p1y + t*t*p2y
    if math.floor(i*12/steps)%12 < 7 then
      frame.display.line(floor(px),floor(py),floor(x),floor(y),color)
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
  -- rings
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    arc(CX,CY,r2, 180,360, P.accent_memory)
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

local function draw_saved_memory(card, sc, enter_t, exit_t)
  local r = floor(48 * sc)
  if r<1 then return end
  arc(CX,CY,r,0,360,P.accent_success,48)
  arc(CX,CY,r,-90,0,P.accent_success,12)
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    check_glyph(CX,CY-8,floor(56*sc),P.accent_success, math.min(1, enter_t*2))
  end
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    frame.display.text("SAVED",CX,CY-42,P.accent_success)
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    frame.display.text((card and card.primary) or "Memory saved",CX,CY+22,P.text_primary)
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
  -- waveform: phase advances with idle_t
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    local phase_off = idle_t * 0.006  -- slow drift
    local bar_count=32; local bar_w=2; local gap=1
    local total_w=bar_count*(bar_w+gap)-gap
    local start_x=CX-floor(total_w/2)+12
    for i=0,bar_count-1 do
      local envelope=math.sin(math.pi*i/(bar_count-1))
      local phase=math.abs(math.sin(math.pi*2*i/bar_count*3+1.2+phase_off))
      local bh=math.max(2,floor(22*envelope*phase*sc))
      local bx=start_x+i*(bar_w+gap)
      frame.display.line(bx,CY-floor(bh/2),bx,CY+floor(bh/2),P.accent_attention)
    end
  end
end

local function draw_loading(sc, enter_t, idle_t)
  -- ghost rings scale in
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    for _,gr in ipairs({16,28,40,52}) do
      arc(CX,CY,floor(gr*sc),0,360,P.border_subtle,24)
    end
  end
  -- spinner: angle advances with idle_t
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    local spin_deg = (idle_t / A.SPINNER_RPM_MS) * 360
    local arc_sweep = lerp(A.SPINNER_ARC_MIN_DEG, A.SPINNER_ARC_MAX_DEG,
                           ease_in_out_sine((math.sin(idle_t/A.SPINNER_ARC_BREATH_MS * math.pi)+1)/2))
    local r = floor(40*sc)
    arc(CX,CY,r, spin_deg,      spin_deg+arc_sweep*0.6, P.memory_trace,16)
    arc(CX,CY,r, spin_deg-30,   spin_deg,               P.accent_memory,4)
    arc(CX,CY,r, spin_deg-60,   spin_deg-30,            P.accent_memory_dim,2)
    frame.display.circle(CX,CY,3,P.memory_trace,true)
    frame.display.circle(CX,CY,floor(6*sc),P.accent_memory_dim,false)
  end
end

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
  -- memory rail: scales from center outward
  local rail_top = floor(lerp(CY, 72,  sc))
  local rail_bot = floor(lerp(CY, 188, sc))
  frame.display.line(44,rail_top,44,rail_bot,P.memory_trace)
  frame.display.circle(44,rail_top,3,P.memory_trace,true)
  frame.display.circle(44,rail_bot,3,jcol,true)
  -- eyebrow
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    frame.display.text(obj,54,80,P.memory_trace)
  end
  -- bezier arc
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    bezier(46,90,200,62,155,150,P.memory_trace,32)
    local jx=floor(46*0.3025+2*0.55*0.45*200+0.2025*155)
    local jy=floor(90*0.3025+2*0.55*0.45*62 +0.2025*150)
    local jd=floor(4*sc)
    if jd>=1 then
      frame.display.line(jx,jy-jd,jx+jd,jy,jcol)
      frame.display.line(jx+jd,jy,jx,jy+jd,jcol)
      frame.display.line(jx,jy+jd,jx-jd,jy,jcol)
      frame.display.line(jx-jd,jy,jx,jy-jd,jcol)
    end
    arc(jx,jy,floor(10*sc),  0, 90,jcol,8)
    arc(jx,jy,floor(10*sc),120,210,jcol,8)
    arc(jx,jy,floor(10*sc),240,330,jcol,8)
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    frame.display.text(place,155,150,P.text_primary)
    if detail~="" then frame.display.text("[ "..detail.." ]",CX,178,P.text_secondary) end
  end
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) then
    frame.display.text(footer,CX,198,P.text_ghost)
  end
end

local function draw_commitment_recall(card, sc, enter_t, exit_t)
  local person = card.person  or ""
  local task   = card.primary or card.task or ""
  local due    = card.due     or ""
  local conf   = card.confidence
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    frame.display.text("YOU PROMISED "..person:upper(),CX,68,P.memory_trace)
  end
  local link_w,link_h=floor(128*sc),18
  local lx=CX-floor(link_w/2)
  local link_ys={84,108,132}
  for li,ly in ipairs(link_ys) do
    local c=(li==3) and P.memory_trace or P.border_subtle
    polyline({{lx,ly},{lx+link_w,ly},{lx+link_w,ly+link_h},{lx,ly+link_h},{lx,ly}},c)
  end
  frame.display.line(CX,84+link_h, CX,108,P.border_subtle)
  frame.display.line(CX,108+link_h,CX,132,P.border_subtle)
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    frame.display.text(task,CX,108+floor(link_h/2),P.text_primary)
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    frame.display.text(due,CX,132+floor(link_h/2),P.memory_trace)
  end
  local jcol=conf and (conf>=0.75 and P.confidence_high or conf>=0.40 and P.confidence_med or P.confidence_low) or P.text_ghost
  frame.display.circle(CX,168,2,jcol,true)
end

local function draw_proactive_memory(card, sc, enter_t, exit_t)
  local summary = card.primary or card.summary or ""
  local person  = card.person
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    frame.display.text("LAST TIME HERE",CX,62,P.text_ghost)
  end
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    radial_rays(CX,CY-10, floor(5*sc),floor(52*sc), 5,P.memory_trace,2)
    frame.display.circle(CX,CY-10,3,P.memory_trace,true)
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    frame.display.text(summary,CX,CY+50,P.text_secondary)
  end
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) and person then
    frame.display.text("With "..person,CX,CY+78,P.memory_trace)
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
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    polar_segs(CX,100, floor(38*sc),floor(56*sc), 12,{0,1,2},P.memory_trace,P.border_subtle,{5,6,7})
    frame.display.text(name,CX,100,P.memory_trace)
    if card.has_avatar then
      -- chord arpeggio around the avatar sprite (drawn at top center by
      -- the sprite handler); confidence shapes the arc sweep
      TR.chord(enter_t, CX, 56, card.confidence or 1)
    end
  end
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    frame.display.line(floor(lerp(CX,72,sc)),116, floor(lerp(CX,184,sc)),116, P.border_subtle)
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    -- spec: exactly ONE line of "why this person matters right now"
    local line = why ~= "" and why or headline
    if #line > 34 then line = line:sub(1, 33) .. "\xE2\x80\xA6" end
    frame.display.text(line,CX,138,P.text_primary)
  end
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) then
    if why ~= "" and headline ~= "" then
      frame.display.text(headline,CX,158,P.text_secondary)
    end
    frame.display.text(detail,CX,176,P.text_ghost)
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
    frame.display.text("PRIVACY VEIL",CX,CY+32,P.privacy_caution)
    frame.display.text("Nothing is captured",CX,CY+48,P.text_ghost)
  end
end

local function draw_error(card, sc, enter_t, exit_t)
  arc(CX,CY,floor(116*sc),0,360,P.warning_amber,48)
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
    frame.display.text((card and card.primary) or "Try again",CX,CY+52,P.text_ghost)
  end
end

local function draw_low_confidence(sc, enter_t, exit_t)
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    frame.display.text("Not sure",CX,CY-14,P.text_secondary)
  end
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    frame.display.text("Try rephrasing",CX,CY+16,P.text_ghost)
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

  -- Eyebrow
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    frame.display.text("DRIFT DETECTED", CX, 72, P.memory_trace)
  end

  -- Primary task text
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    frame.display.text(task, CX, CY - 12, P.text_primary)
  end

  -- Person chain: three dots then arrow then name
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) then
    if person ~= "" then
      -- chain dots
      for i = 0, 2 do
        frame.display.circle(CX - 20 + i * 8, CY + 16, 2, P.border_subtle, true)
      end
      frame.display.text("\xe2\x86\x92 " .. person, CX, CY + 32, P.memory_trace)
    end
  end

  -- Footer detail
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) then
    frame.display.text(detail, CX, 184, P.text_ghost)
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
    frame.display.text(crumb, CX, 66, P.text_ghost)
  end

  -- Primary summary
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    frame.display.text(summary, CX, CY - 4, P.text_primary)
  end

  -- Place name
  if layer_ok(enter_t, A.STAGGER_DETAIL_MS) and place ~= "" then
    frame.display.text(place, CX, CY + 22, P.memory_trace)
  end

  -- Prev / next neighbour ghost labels
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) then
    if prev_lbl ~= "" then
      frame.display.text("\xe2\x97\x80 " .. prev_lbl, 56, 182, P.text_ghost)
    end
    if next_lbl ~= "" then
      frame.display.text(next_lbl .. " \xe2\x96\xb6", 200, 182, P.text_ghost)
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
    frame.display.text("SOUNDS DIFFERENT", CX, 66, P.warning_amber)
  end

  -- Separator
  if layer_ok(enter_t, A.STAGGER_EYEBROW_MS) then
    local sep_x0 = floor(lerp(CX, 52,  sc))
    local sep_x1 = floor(lerp(CX, 204, sc))
    frame.display.line(sep_x0, 78, sep_x1, 78, P.border_subtle)
  end

  -- Prior summary (above central divider)
  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    frame.display.text(prior_text, CX, 100, P.text_ghost)
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
    frame.display.text(new_text, CX, 142, P.text_primary)
  end

  -- Score dot
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) then
    local dot_r = floor(lerp(2, 5, score) * sc)
    if dot_r >= 1 then
      frame.display.circle(CX, 170, dot_r, score_col, true)
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
-- TruthLensCard — 9-ring gauge (Halo Cinema v1, Phase 4)
-- One ring per analysis stage: face, AU, voice, prosody, linguistic,
-- narrative, fusion, aggregate, verdict.  Ring i sits at radius
-- GAUGE_R0 + (i-1)*GAUGE_PITCH, filled clockwise from 12 o'clock by that
-- stage's confidence, colored by its signal direction:
--   truthful → accent_success, deceptive → accent_attention,
--   insufficient → text_ghost.
-- Center holds the fused verdict word + a confidence dot.
-- ENTER uses Truth Ripple from card.origin (eye landmark), handled by the
-- signature dispatcher; reduce_motion draws all rings statically.
-- ---------------------------------------------------------------------------
-- r=34..66: the clear r<34 core keeps the verdict word off the rings
local GAUGE_R0    = 34
local GAUGE_PITCH = 4

local GAUGE_DIR_COLOR = {
  truthful     = P.accent_success,
  deceptive    = P.accent_attention,
  insufficient = P.text_ghost,
}

local function draw_truth_gauge(card, sc, enter_t, exit_t, idle_t)
  local stages  = card.stages or {}
  local verdict = card.verdict or card.primary or ""
  local conf    = card.confidence

  for i = 1, 9 do
    local stage = stages[i] or {}
    local r = floor((GAUGE_R0 + (i - 1) * GAUGE_PITCH) * math.max(sc, 0.01))
    if r >= 2 then
      -- ghost track
      arc(CX, CY, r, 0, 360, P.border_subtle, 24)
      -- stage fill: clockwise from 12 o'clock, sweep = stage confidence.
      -- Rings draw on sequentially during ENTER (ring i gated at i/9).
      local ring_gate = TR.reduce_motion() and 1 or clamp(enter_t * 9 - (i - 1), 0, 1)
      local sweep = clamp(stage.confidence or 0, 0, 1) * 360 * ring_gate
      if sweep > 4 then
        local color = GAUGE_DIR_COLOR[stage.direction or "insufficient"] or P.text_ghost
        arc(CX, CY, r, -90, -90 + sweep, color, 28)
      end
    end
  end

  if layer_ok(enter_t, A.STAGGER_PRIMARY_MS) then
    -- black backing capsule keeps ring strokes off the verdict glyphs
    local half_w = floor(#verdict * T.avg_w_with_tracking("md", 0) / 2) + 5
    frame.display.rect(CX - half_w, CY - 15, half_w * 2, 19, P.background, true)
    frame.display.text(verdict, CX, CY - 6, P.text_primary)
  end
  if layer_ok(enter_t, A.STAGGER_FOOTER_MS) and conf then
    local jcol = (conf >= 0.75 and P.confidence_high)
              or (conf >= 0.40 and P.confidence_med)
              or  P.confidence_low
    frame.display.circle(CX, CY + 16, 3, jcol, true)
  end
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
  SavedMemoryCard       = function(c,sc,et,xt,it) draw_saved_memory(c,sc,et,xt)           end,
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
  -- Halo Cinema v1 lenses
  TruthLensCard         = function(c,sc,et,xt,it) draw_truth_gauge(c,sc,et,xt,it)         end,
}

-- ---------------------------------------------------------------------------
-- Signature routing (Halo Cinema v1, docs/HALO_CINEMA_V1.md §1.1)
-- enter: iris (S1, default) | comet (S6) | ripple (S5) | slam (legacy shield)
-- hold : halo (S4) on recall cards; card-specific idles stay in DRAW fns
-- exit : contract (shared); Prism Slide (S3) replaces it during crossfade
-- ---------------------------------------------------------------------------
local SIGNATURES = {
  ObjectRecallCard     = { enter = "iris",   hold = "halo" },
  CommitmentRecallCard = { enter = "iris",   hold = "halo" },
  ProactiveMemoryCard  = { enter = "comet",  hold = "halo" },
  PersonContextCard    = { enter = "iris",   hold = "halo" },
  TruthLensCard        = { enter = "ripple" },
  PrivacyVeilCard    = { enter = "slam" },
}

local DEFAULT_SIGNATURE = { enter = "iris" }

local function signature_for(card)
  return (card and SIGNATURES[card.type]) or DEFAULT_SIGNATURE
end

local function enter_ms_for(card)
  local sig = signature_for(card)
  if sig.enter == "slam" then return A.ENTER_DURATION_MS end
  return TR.enter_duration(sig.enter)
end

-- ---------------------------------------------------------------------------
-- Internal composite: draw one card, routed through its motion signature.
-- ENTER — signature-specific (iris ring, comet flight, truth ripple, slam)
-- HOLD  — confidence halo on recall cards + card idle
-- EXIT  — exit_contract: geometry contracts, text cuts at t=0.4 (the draw
--         fns' stagger gates suppress text when enter_t < 0)
-- ---------------------------------------------------------------------------
local function composite(card, phase, elapsed_ms, idle_t)
  if not card then return end
  local fn = DRAW[card.type]
  if not fn then return end
  local sig = signature_for(card)

  local enter_t, exit_t, sc

  if phase == "enter" then
    local dur = enter_ms_for(card)
    local raw = (dur <= 0) and 1.0 or clamp(elapsed_ms / dur, 0, 1)
    exit_t = 0

    if sig.enter == "comet" and not TR.reduce_motion() then
      -- S6: comet travels first; the card blooms on arrival
      local comet_frac = A.SIG_COMET_MS / (A.SIG_COMET_MS + A.SIG_IRIS_MS)
      if raw < comet_frac then
        TR.memory_comet(raw / comet_frac, card.weeks_old or 0, CX, CY - 10)
        return
      end
      raw = (raw - comet_frac) / (1 - comet_frac)
    end

    enter_t = raw
    sc      = 1.0   -- kill list #1: no more 0.94 uniform scale wobble

    if sig.enter == "slam" then
      -- sub-bass rumble dims the ambient field before the shield slams
      TR.rumble(clamp(elapsed_ms / A.SIG_RUMBLE_MS, 0, 1))
    end

    fn(card, sc, enter_t, exit_t, idle_t or 0)

    if sig.enter == "iris" or sig.enter == "comet" then
      TR.iris_bloom(raw, card.conf_color or P.accent_memory)
    elseif sig.enter == "ripple" then
      local origin = card.origin or {}
      TR.truth_ripple(raw, origin.x, origin.y)
    end
    if sig.enter == "comet" and TR.reduce_motion() then
      -- static recency tick preserves the entry-angle information
      TR.memory_comet(1, card.weeks_old or 0, CX, CY - 10)
    end
    return

  elseif phase == "exit" then
    local raw = clamp(elapsed_ms / A.EXIT_DURATION_MS, 0, 1)
    exit_t = raw
    local scale, text_ok = TR.exit_contract(raw)
    sc      = scale
    -- enter_t < 0 fails every stagger gate: text cuts, geometry contracts
    enter_t = text_ok and 1.0 or -1.0

  else -- hold
    enter_t = 1.0
    exit_t  = 0
    sc      = 1.0
    if sig.hold == "halo" and card.confidence then
      -- S4: halo underneath the card content; radius+sweep encode confidence
      TR.confidence_halo(idle_t or 0, card.confidence,
                         card.conf_color or P.accent_memory_dim)
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

--- Begin ENTER animation for card.
--- If a card is already visible, simultaneously begins its Prism Slide
--- refraction while the new card irises in (S3 crossfade).
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
  -- If something is showing, capture it as the outgoing card
  if _card and _phase ~= "exit" then
    _prev_card   = _card
    _prev_exit_t = 0
    _prev_start  = now
  end
  _card        = card
  _phase       = "enter"
  _phase_start = now
  _idle_t      = 0
end

--- Begin EXIT animation for the current card.
function renderer.dismiss()
  if not _card then return end
  if _phase == "exit" then return end  -- already exiting
  _phase       = "exit"
  _phase_start = _now_ms()
end

--- Advance animations and push one composite frame.
--- Called every tick from main.lua (no args needed; reads clock internally).
function renderer.tick()
  if not HAS_FRAME then return end
  if not _card then return end

  local now     = _now_ms()
  local elapsed = now - _phase_start
  local idle_t  = _idle_t

  -- Advance phase (ENTER duration is signature-specific)
  if _phase == "enter" and elapsed >= enter_ms_for(_card) then
    _phase       = "hold"
    _phase_start = now
    elapsed      = 0
    idle_t       = 0
    _idle_t      = 0
  elseif _phase == "hold" then
    _idle_t = _idle_t + 50  -- ~50 ms per tick at frame.sleep(0.05)
    idle_t  = _idle_t
  elseif _phase == "exit" and elapsed >= A.EXIT_DURATION_MS then
    -- Exit complete — clear card
    _card  = nil
    _phase = nil
    frame.display.clear(0x000000)
    frame.display.show()
    return
  end

  -- Advance outgoing crossfade (Prism Slide runs on its own clock)
  if _prev_card then
    local prev_elapsed = now - _prev_start
    _prev_exit_t = clamp(prev_elapsed / A.SIG_PRISM_MS, 0, 1)
    if _prev_exit_t >= 1 then
      _prev_card = nil  -- crossfade complete
      TR.prism_slide(1)  -- restore fringe slots
    end
  end

  -- Composite frame
  frame.display.clear(0x000000)

  -- Draw outgoing card (refracting out) underneath
  if _prev_card then
    composite(_prev_card, "exit", (now - _prev_start), 0)
    TR.prism_slide(_prev_exit_t)
  end

  -- Draw incoming card on top
  composite(_card, _phase, elapsed, idle_t)

  frame.display.show()
end

-- Backward-compat stubs
function renderer.show_card_immediate(card)
  -- Used by tests: skip animation, draw once synchronously
  if not HAS_FRAME then return end
  if not card then return end
  local fn = DRAW[card.type]
  if not fn then return end
  frame.display.clear(0x000000)
  fn(card, 1.0, 1.0, 0, 0)
  frame.display.show()
  _card  = card
  _phase = "hold"
  _phase_start = _now_ms()
  _idle_t = 0
end

function renderer.push(layer, fn)  if fn then fn() end end
function renderer.flush()          end
function renderer.clear()          end

return renderer
