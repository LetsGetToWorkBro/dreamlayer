
local utils = require("lib.utils")
local M = {}

M.SIZE_HERO = "hero"
M.SIZE_XL   = "xl"
M.SIZE_LG   = "lg"
M.SIZE_MD   = "md"
M.SIZE_SM   = "sm"

-- ---------------------------------------------------------------------------
-- Meridian Solid: THE device font seam. frame.display.set_font(fid, sz, sc)
-- exists in the adapter and is wired through primitives.set_font_size —
-- fid/sz/sc here are the single table to recalibrate on real glass
-- (docs/cinema_v2/solid.md). The raster harness maps sz*sc to a PIL font
-- of the same pixel size, so goldens carry the same hierarchy the panel
-- will. If firmware's set_font differs, only this table changes; if it's
-- absent, primitives latches the feature off and text stays single-size.
-- ---------------------------------------------------------------------------
M.DEVICE_FONT = {
  hero = { fid = 1, sz = 22, sc = 1.0 },
  xl   = { fid = 1, sz = 19, sc = 1.0 },
  lg   = { fid = 1, sz = 17, sc = 1.0 },
  md   = { fid = 1, sz = 13, sc = 1.0 },
  sm   = { fid = 1, sz = 10, sc = 1.0 },
}
M.DEFAULT_SIZE = "md"

-- Average glyph advance per size, measured against the reference face
-- (DejaVuSans-Bold; test_typography_metrics.py pins these to PIL within
-- ±2px). The old table equated font px with advance — nearly 2x too
-- wide, which would starve every hero string of room it actually has.
local AVG_W  = { hero = 12, xl = 11, lg = 10, md = 8, sm = 6 }
local BASE_H = { hero = 30, xl = 26, lg = 22, md = 17, sm = 13 }

M.LINE_SPACING = 1.55

function M.line_height(size)
  local base = BASE_H[size] or 17
  return math.floor(base * M.LINE_SPACING / 2 + 0.5) * 2
end

function M.max_chars(size, width_px)
  return math.floor(width_px / (AVG_W[size] or 13))
end

function M.truncate(text, size, width_px)
  local maxc = M.max_chars(size, width_px)
  if #text <= maxc then return text end
  if maxc <= 1 then return "\xE2\x80\xA6" end
  return text:sub(1, maxc - 1) .. "\xE2\x80\xA6"
end

function M.wrap(text, size, width_px)
  return utils.wrap(text, M.max_chars(size, width_px))
end

function M.avg_w_with_tracking(size, tracking_px)
  return (AVG_W[size] or 10) + (tracking_px or 0)
end

--- Largest size token whose average-width estimate fits `width_px`.
--- ladder defaults to the full descent; every hero string goes through
--- this so a long place name drops to xl/lg instead of clipping the
--- circular panel ("CONSISTENT" at hero > a 108px capsule -> xl).
function M.fit_size(text, width_px, ladder)
  ladder = ladder or { "hero", "xl", "lg", "md" }
  local n = #tostring(text)
  for _, size in ipairs(ladder) do
    if n * (AVG_W[size] or 13) <= width_px then return size end
  end
  return ladder[#ladder]
end

return M
