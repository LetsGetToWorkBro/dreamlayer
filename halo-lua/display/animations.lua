
local M = {}

M.EASE_ENTRANCE = "ease_out_expo"
M.EASE_EXIT     = "linear"
M.EASE_BREATHE  = "ease_in_out_sine"
M.EASE_DRAW     = "ease_out"

M.ENTER_DURATION_MS  = 180
M.ENTER_SCALE_FROM   = 0.94
M.ENTER_SCALE_TO     = 1.0
M.ENTER_OPACITY_FROM = 0.0
M.ENTER_OPACITY_TO   = 1.0

M.STAGGER_PRIMARY_MS  =   0
M.STAGGER_EYEBROW_MS  =  40
M.STAGGER_DETAIL_MS   =  60
M.STAGGER_FOOTER_MS   =  80

M.EXIT_DURATION_MS = 120

M.BREATHE_CYCLE_MS   = 3200
M.BREATHE_R_MIN      =  5
M.BREATHE_R_MAX      = 10
M.BREATHE_GLOW_R     = 16
M.BREATHE_GLOW_ALPHA = 0.18

M.SATELLITE_R    = 2
M.SATELLITE_DIST = 22
M.SATELLITES = {
  { x = 128, y = 106 },
  { x = 144, y = 112 },
  { x = 150, y = 128 },
  { x = 144, y = 144 },
  { x = 128, y = 150 },
  { x = 112, y = 144 },
  { x = 106, y = 128 },
  { x = 112, y = 112 },
}

M.SPINNER_RADIUS_PX  = 52
M.SPINNER_STROKE_PX  =  2
M.SPINNER_RPM_MS     = 900
M.SPINNER_ARC_MIN_DEG   =  80
M.SPINNER_ARC_MAX_DEG   = 260
M.SPINNER_ARC_BREATH_MS = 1800

M.WAVE_BAR_COUNT  = 7
M.WAVE_BAR_WIDTH  = 2
M.WAVE_BAR_GAP    = 6
M.WAVE_BAR_Y      = 138
M.WAVE_BAR_H_MIN  =  6
M.WAVE_BAR_H_MAX  = 22
M.WAVE_BAR_CENTERS = { 101, 109, 117, 128, 139, 147, 155 }

M.DRAWON_START_MS    = 100
M.DRAWON_DURATION_MS = 300

M.DISMISS_MS = {
  ReadyCard            =    0,
  SavedMemoryCard      = 1200,
  QueryListeningCard   =    0,
  LoadingCard          =    0,
  ObjectRecallCard     = 3500,
  CommitmentRecallCard = 4000,
  ProactiveMemoryCard  = 3500,
  PersonContextCard    = 3500,
  PrivacyVeilCard    =    0,
  ErrorCard            = 4000,
  LowConfidenceCard    = 3000,
  TruthLensCard        = 5000,
  -- O3 conversation cards (Veritas / answer-ahead / Juno / Listen!)
  FactCheckCard        = 7000,
  AnswerAheadCard      = 8000,
  JunoReplyCard      = 6000,
  HarkCard             = 6500,
  -- World lenses (Scholar / Glance chooser / TasteLens) — match host payloads
  ScholarCard          = 9000,
  GlanceChoiceCard     = 6000,
  TasteCard            = 9000,
  -- Missing frames — match host constructors (cards.py)
  ListeningCard        =    0,
  MessageCard          = 6000,
  UpcomingCard         = 6000,
  HereCard             = 5000,
  PersonDossierCard    = 5000,
  SpokenCaptionCard    =    0,
  MorningBriefCard     = 8000,
}

M.LOADING_TO_OBJECT_SPINNER_FADE_MS = 160
M.LOADING_TO_OBJECT_CARD_START_MS   = 100

-- ---------------------------------------------------------------------------
-- Meridian (Cinema v2) — every duration/geometry constant lives here;
-- display modules read these and NEVER hardcode milliseconds.
-- Survivors from Halo Cinema v1 (Ghost Wake, Truth Ripple, acoustics)
-- keep their SIG_* names. The killed v1 signatures (Iris Bloom, Prism
-- Slide, Confidence Halo orbit, Memory Comet) are removed with their
-- replacements shipping in the same PR — see docs/CINEMA_V2_DELTAS.md.
-- ---------------------------------------------------------------------------

-- S2 Ghost Wake (WorldAnchorCard ENTER: per-char Perlin condensation)
M.SIG_GHOSTWAKE_MS        = 320
M.SIG_GHOSTWAKE_JITTER_PX = 2
M.SIG_GHOSTWAKE_Y_FROM    = 0      -- ghost slot luma ramp (0-1023 scale)
M.SIG_GHOSTWAKE_Y_TO      = 400

-- S5 Truth Ripple (Truth Lens verdict ENTER: ripple from eye landmark)
M.SIG_RIPPLE_MS      = 400
M.SIG_RIPPLE_R_MAX   = 120
M.SIG_RIPPLE_CR      = 80     -- warm shift peak on the ripple slot
M.SIG_RIPPLE_COLD_MS = 240    -- cold recovery on false-positive dismiss
M.SIG_RIPPLE_CB      = 60     -- cold shift on recovery

-- HUD acoustics analogs (docs/HALO_CINEMA_V1.md §1.3, kept)
M.SIG_CHIME_MS       = 220    -- memory saved: single expanding ring
M.SIG_CHIME_R_FROM   = 8
M.SIG_CHIME_R_TO     = 28
M.SIG_CHORD_STEP_MS  = 40     -- person recognized: 3-arc arpeggio step
M.SIG_RUMBLE_MS      = 100    -- privacy veil: full-field dim pre-slam
M.SIG_RUMBLE_Y_DROP  = 160    -- dynamic slot luma drop during rumble

-- ---------------------------------------------------------------------------
-- Focus law (docs/cinema_v2/focus.md): condensation / recession
-- ---------------------------------------------------------------------------
M.SIG_FOCUS_TRAVEL_MS   = 140   -- head flight rim -> core
M.SIG_FOCUS_LAND_MS     = 100   -- landing ring collapse + content bloom
M.SIG_FOCUS_TRAIL_MS    = 60    -- ghost-slot Y ramp trailing edge (from v1 iris)
M.SIG_FOCUS_LAND_R_FROM = 56
M.SIG_FOCUS_LAND_R_TO   = 36
M.SIG_FOCUS_RING_R      = 92    -- landed hold ring radius (sweep = confidence)
M.SIG_RECEDE_MS         = 200   -- content contracts, head settles home
                                -- (Lumen: 160 -> 200 with the soft-spring
                                -- deceleration; CINEMA_V2_RISKS.md §4
                                -- pre-cleared up to 240 — recession should
                                -- read as "filed", not "escaped")
M.SIG_RECEDE_TEXT_CUT   = 0.4   -- text cuts at this fraction (kill-list #2)
M.SIG_FOCUS_XFADE_LAG_MS = 40   -- condense start lag during crossfade

-- ---------------------------------------------------------------------------
-- The Horizon (docs/cinema_v2/horizon.md): the persistent rim instrument
-- ---------------------------------------------------------------------------
M.MER_TRACK_R          = 100   -- rim track radius (1px ghost arc)
M.MER_MARK_BASE_R      = 101   -- marks radiate outward from here
M.MER_RIM_R            = 105   -- nominal mark anchor (travel origin)
M.MER_NOW_DEG          = -90   -- 12 o'clock, screen coords
M.MER_DEG_PER_HOUR     = 30    -- full dial = 12h
M.MER_WINDOW_HOURS     = 5     -- lookback/lookahead cap (150 deg each)
M.MER_SEAM_FROM_DEG    = 60    -- past cap edge (seam start)
M.MER_SEAM_TO_DEG      = 120   -- future cap edge (seam end, via bottom)
M.MER_ELDER_DEG        = 58    -- older-than-window compression tick
M.MER_FUTURE_CAP_DEG   = 122   -- further-than-window promise dot
M.MER_MARKS_MAX        = 48
M.MER_MARK_MERGE_DEG   = 3     -- memory marks within this merge (+len)
M.MER_MARK_LEN         = { [0] = 3, [1] = 6, [2] = 9 }  -- by luma tier
M.MER_NOW_LEN_MIN      = 6     -- notch breathe (geometric, no slot)
M.MER_NOW_LEN_MAX      = 9
M.MER_STALE_MS         = 30000 -- no horizon frame for this long -> tier drop
M.MER_ARRIVAL_PULSE_MS = 300   -- mark pulse after recession lands
M.MER_HIGHLIGHT_MS     = 2400  -- anchor-echo provenance brighten
M.MER_DREAM_ENTER_MS   = 300   -- light change into dream (no scene cut)
M.MER_DREAM_EXIT_MS    = 200
M.MER_PROMISE_R        = 105   -- on-rim promise dot anchor
M.MER_PROMISE_SLIP_R   = 95    -- cracking/shattered inward position
M.MER_PROMISE_STACK_PX = 7     -- radial pitch for same-hour promises

-- ---------------------------------------------------------------------------
-- Testimony Thread (docs/cinema_v2/testimony.md): Truth Lens verdict
-- ---------------------------------------------------------------------------
M.TESTIMONY_R        = 64    -- thread radius (clears the verdict capsule)
M.TESTIMONY_SLOT_DEG = 40    -- 9 stages x 40 deg
M.TESTIMONY_STAGE_MS = 80    -- accumulation per stage after the ripple
M.TESTIMONY_TEAR_PX  = 3     -- radial jitter on torn (deceptive) stages

-- ---------------------------------------------------------------------------
-- Meridian Lumen (docs/cinema_v2/lumen.md): material physics + living light.
-- Geometry stays information-bearing; springs, palette light, trails, and
-- IMU world-lock carry the material quality. Host mirror of this bank:
-- host-python/src/dreamlayer/hud/motion_math.py — keep the two in sync.
-- ---------------------------------------------------------------------------

-- Springs (lib/easing.lua spring(t, zeta, omega)). Overshoot of the
-- snappy zeta is exp(-zeta*pi/sqrt(1-zeta^2)) ~ 7.8%, under the cap.
M.SPRING_OMEGA         = 7.4
M.SPRING_ZETA_SOFT     = 0.85  -- no visible overshoot: text-adjacent geometry
M.SPRING_ZETA_SNAPPY   = 0.63  -- rings, notches, dots: the "click" of focus
M.SPRING_OVERSHOOT_MAX = 0.08  -- hard cap, asserted in tests
M.ANTICIPATE_FRAC      = 0.12  -- fraction of travel spent pulling back
M.ANTICIPATE_PX        = 2     -- head sinks this far toward the rim first
M.SQUASH_MAX           = 0.25  -- head elongation along velocity, ratio

-- Palette animator (display/palette_animator.lua)
M.PAL_WRITES_MAX       = 8     -- assign_color_ycbcr budget per tick

-- Worst-case primitive calls per composited frame (asserted in
-- test_draw_budget.py via the raster harness draw_calls counter)
M.DRAW_CALLS_MAX       = 420

-- Horizon aurora: the rim track banded across three leased slots whose
-- luma cycles slowly — light flows along the day-ring, zero new geometry.
-- Base hexes sit one LSB apart around border_subtle so each band maps to
-- its own slot on the indexed panel without colliding with the static
-- border_subtle token (the base-hex conflation documented in
-- docs/CINEMA_V2_RISKS.md).
M.AURORA_PERIOD_MS     = 12000
M.AURORA_Y_AMP         = 120   -- luma swing (0-1023) around the track base
M.AURORA_BASE_A        = 0x2A3C46
M.AURORA_BASE_B        = 0x2B3D45
M.AURORA_BASE_C        = 0x293B43

-- Premonition shimmer: luma breath on the ghost slot replaces the v1
-- 70%-duty visibility blink (the one true temporal-dither; killed).
M.SHIMMER_PERIOD_MS    = 1400
M.SHIMMER_Y_LO         = 180  -- breathes DOWN from the ghost base luma
M.SHIMMER_Y_HI         = 400  -- ...and back: never brighter than the v1 dot
M.PREMO_BASE           = 0x58686E  -- premonition dots: text_ghost, one LSB off

-- Notch heartbeat: two-phase beat replacing sine breathe (rise fraction
-- of BREATHE_CYCLE_MS spent on the spring rise, remainder on soft decay)
M.HEARTBEAT_RISE_FRAC  = 0.22

-- Focus law, Lumen pass
M.TRAIL_SAMPLES        = 5     -- phosphor tail length (was 3)
M.TRAIL_STEP_T         = 0.06  -- t-spacing between tail samples
M.SPEC_SWEEP_MS        = 420   -- one-shot glint run along the hold ring

-- Card light bands: geometry drawn in these hexes maps to the card slots
-- (aliasing the dream/aurora slots — mode-exclusive) so a wave program
-- can flow luma along it. One LSB off memory_trace so the static look is
-- identical when no program runs (reduce_motion / settled states).
M.SPEC_BASE_A          = 0x00FFA9
M.SPEC_BASE_B          = 0x01FFAA
M.SPEC_BASE_C          = 0x00FEAA
M.VOICE_BASE           = 0xE06B53 -- listening bars: accent_attention,
                                  -- one LSB off, aliasing the card_a
                                  -- slot (free while listening — no
                                  -- conduct/chase runs on that card;
                                  -- NEVER on fx: accent_memory draws
                                  -- resolve through fx's slot)
M.CONDUCT_PERIOD_MS    = 2400  -- object-recall rail: place -> object flow
M.CONDUCT_Y_AMP        = 220
M.CHASE_Y_AMP          = 300   -- loading ring luma swing
M.VOICE_Y_GAIN         = 200   -- listening warmth: luma per full amp
M.VOICE_CR_GAIN        = 60    -- ...and warm chroma shift

-- IMU parallax (display/parallax.lua): layers shift against head motion.
-- LOCK (text, verdicts, privacy) never moves; worst case rim mark at
-- r=110 + 1px stays inside SAFE_RADIUS=112.
M.PAR_MAX_PX           = { rim = 1, ring = 2, air = 3 }
M.PAR_RATE_GAIN        = 0.9   -- deg/s of head rate -> px (pre-clamp)
M.PAR_EMA_ALPHA        = 0.35  -- rate smoothing per 50ms tick
M.PAR_SPRING_ZETA      = 0.75  -- return-to-zero spring when the head stops
M.PAR_RETURN_MS        = 260   -- duration of the inertial return

-- Particle pool (display/particles.lua): one global budget shared with
-- dream weather; hero bursts steal from weather, never exceed it.
M.PARTICLE_BUDGET      = 24
M.BURST_N              = 12    -- save-moment burst count
M.BURST_MS             = 480
M.BURST_SPEED          = 46    -- px/s outward
M.SHARD_N              = 6     -- promise-shatter shards
M.SHARD_MS             = 700
M.SHARD_SPEED          = 30    -- px/s, falling inward off the rim
M.TEAR_SPIT_N          = 3     -- testimony tear reveal
M.TEAR_SPIT_MS         = 320

-- Hero moments
M.SHATTER_FLASH_MS     = 150   -- one-shot fx luma flash (single ramp down)
M.WAKE_REVEAL_MS       = 600   -- horizon draws on radially at wake
M.WARP_STREAKS         = 18    -- dream-door starfield streak count
M.WARP_STREAK_LEN      = 14    -- max streak length px

-- Loading palette-chase: 12 static segments banded across three slots;
-- the light chases at the old spinner's RPM (geometry no longer rotates)
M.CHASE_SEGMENTS       = 12

-- O3 conversation cards (Lumen): every duration lives here, never
-- inline in a draw fn (the standing rule).
M.HARK_BREATHE_MS        = 1100  -- Listen! ring breathe period
M.HARK_BREATHE_URGENT_MS = 700   -- ...urgent breathes harder
M.FACT_PULSE_MS          = 420   -- disputed/contradiction one-shot pulse

-- Glance chooser: option nodes on an upper arc that spring in staggered.
M.GLANCE_NODE_R          = 84    -- ring radius the option nodes sit on
M.GLANCE_NODE_STAGGER_MS = 60    -- per-node spring-in delay (left -> right)

-- ListeningCard wake cue: the "I'm listening" ring breathe period.
M.LISTEN_PULSE_MS        = 1400

-- Prism Lens (Lumen rebuild): the kaleidoscope blooms open on a spring,
-- its rotation breathes (speeds and slows on a slow sine), and two thin
-- halo rings counter-rotate against the arms. All rates stay far below
-- photosensitivity thresholds — wonder, not strobe.
M.PRISM_BLOOM_MS       = 600   -- spring unfold on activation
M.PRISM_SPIN_RATE      = 0.00004 -- rad/ms base rotation (v1 rate, kept)
M.PRISM_BREATH_MS      = 5200  -- rotation-rate breathing period
M.PRISM_RING_R_A       = 60    -- inner counter-rotating halo ring
M.PRISM_RING_R_B       = 86    -- outer counter-rotating halo ring

return M
