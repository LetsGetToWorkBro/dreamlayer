--- display/themes/cyberpunk.lua — a reference Forkable Skin (3.6).
---
--- Neon on black: magenta memory, cyan structure, hot accents. Same renderer,
--- same budgets, same primitives — 30-odd lines of data restyle the whole
--- in-eye identity. Load with theme.apply(require("display.themes.cyberpunk")).
return {
  name = "Cyberpunk",
  colors = {
    background      = 0x000000,   -- the waveguide is emissive: black = clear
    surface         = 0x0A0512,
    text_primary    = 0xF2E9FF,   -- near-white with a violet cast
    text_secondary  = 0x9A7CC0,
    text_ghost      = 0x4A2E6B,
    accent_memory   = 0xFF2CD4,   -- neon magenta is the memory family here
    accent_attention = 0x00E5FF,  -- cyan pulls the eye
    accent_success  = 0x39FF14,   -- acid green
    accent_error    = 0xFF3355,
    border_subtle   = 0x2A1240,
    warning_amber   = 0xFF7A00,
    privacy_danger  = 0xFF0044,
    privacy_caution = 0xFFB000,
  },
  typography = {
    -- a touch tighter/technical; still inside the [10,22] band
    hero = { sz = 21 },
    sm   = { sz = 11 },
  },
  motion = {
    card_in_ms  = 160,   -- snappier, more electric
    card_out_ms = 120,
  },
}
