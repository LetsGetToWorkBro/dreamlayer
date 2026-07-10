--- display/themes/high_contrast.lua — a reference Forkable Skin (3.6).
---
--- An accessibility skin: maximum luminance separation, larger base type, the
--- boldest unambiguous accents. Proof that a theme is also an acccommodation —
--- the same card, legible to more eyes. Load with
--- theme.apply(require("display.themes.high_contrast")).
return {
  name = "High Contrast",
  colors = {
    background      = 0x000000,
    surface         = 0x000000,   -- no surface tint — text floats on pure black
    text_primary    = 0xFFFFFF,   -- maximum contrast
    text_secondary  = 0xD0D0D0,
    text_ghost      = 0x808080,   -- still readable, unlike the default ghost
    accent_memory   = 0x00FFB0,
    accent_attention = 0xFFD400,  -- amber-yellow reads for most color vision
    accent_success  = 0x00FF66,
    accent_error    = 0xFF4040,
    border_subtle   = 0x606060,   -- borders you can actually see
    warning_amber   = 0xFFA000,
    privacy_danger  = 0xFF0000,
    privacy_caution = 0xFFC000,
  },
  typography = {
    -- one step larger across the reading sizes, still within the band
    md = { sz = 15 },
    sm = { sz = 12 },
    lg = { sz = 19 },
  },
  motion = {
    -- calmer, longer transitions are easier to track
    card_in_ms  = 300,
    card_out_ms = 260,
  },
}
