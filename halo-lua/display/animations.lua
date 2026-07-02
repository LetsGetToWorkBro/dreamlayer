
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
}

M.LOADING_TO_OBJECT_SPINNER_FADE_MS = 160
M.LOADING_TO_OBJECT_CARD_START_MS   = 100

-- ---------------------------------------------------------------------------
-- Halo Cinema v1 — motion signature timing (docs/HALO_CINEMA_V1.md §1.1)
-- Every signature duration/geometry constant lives here; transitions.lua
-- reads these and NEVER hardcodes milliseconds.
-- ---------------------------------------------------------------------------

-- S1 Iris Bloom (default card ENTER: radial mask reveal)
M.SIG_IRIS_MS        = 180
M.SIG_IRIS_R_FROM    = 112    -- safe-area edge radius
M.SIG_IRIS_R_TO      = 36     -- content core radius where the ring lands
M.SIG_IRIS_TRAIL_MS  = 60     -- ghost-slot Y ramp trailing edge

-- S2 Ghost Wake (WorldAnchorCard ENTER: per-char Perlin condensation)
M.SIG_GHOSTWAKE_MS        = 320
M.SIG_GHOSTWAKE_JITTER_PX = 2
M.SIG_GHOSTWAKE_Y_FROM    = 0      -- ghost slot luma ramp (0-1023 scale)
M.SIG_GHOSTWAKE_Y_TO      = 400

-- S3 Prism Slide (card→card crossfade: chromatic split on dynamic slots)
M.SIG_PRISM_MS       = 140
M.SIG_PRISM_SPLIT_PX = 2
M.SIG_PRISM_CB       = 96     -- cool fringe Cb push
M.SIG_PRISM_CR       = 96     -- warm fringe Cr pull

-- S4 Confidence Halo (HOLD idle for recall cards: orbital confidence arc)
M.SIG_HALO_PERIOD_MS = M.BREATHE_CYCLE_MS   -- one orbit per breathe cycle
M.SIG_HALO_R_BASE    = 24
M.SIG_HALO_R_CONF    = 40     -- radius = R_BASE + confidence * R_CONF

-- S5 Truth Ripple (Truth Lens verdict ENTER: ripple from eye landmark)
M.SIG_RIPPLE_MS      = 400
M.SIG_RIPPLE_R_MAX   = 120
M.SIG_RIPPLE_CR      = 80     -- warm shift peak on the ripple slot
M.SIG_RIPPLE_COLD_MS = 240    -- cold recovery on false-positive dismiss
M.SIG_RIPPLE_CB      = 60     -- cold shift on recovery

-- S6 Memory Comet (ProactiveMemoryCard ENTER: recency-angle comet)
M.SIG_COMET_MS           = 280
M.SIG_COMET_TAIL         = 3      -- fading tail samples
M.SIG_COMET_DEG_PER_WEEK = 30     -- entry angle sweep per week of recency
M.SIG_COMET_MAX_DEG      = 330    -- cap (just shy of a full sweep)

-- HUD acoustics analogs (docs/HALO_CINEMA_V1.md §1.3)
M.SIG_CHIME_MS       = 220    -- memory saved: single expanding ring
M.SIG_CHIME_R_FROM   = 8
M.SIG_CHIME_R_TO     = 28
M.SIG_CHORD_STEP_MS  = 40     -- person recognized: 3-arc arpeggio step
M.SIG_RUMBLE_MS      = 100    -- privacy veil: full-field dim pre-slam
M.SIG_RUMBLE_Y_DROP  = 160    -- dynamic slot luma drop during rumble

return M
