--- display/cards.lua
--- Card payload constructors for Halo-Lua side.
--- Uses updated palette keys to match Python themes.py (transformative pass).

local P = require("display.palette")
local T = require("display.typography")
local A = require("display.animations")

local M = {}

--- Updated conf_color using new palette keys (mirrors Python themes.conf_color)
local function conf_color(c)
  if not c then return P.text_ghost end
  if c >= 0.75 then return P.confidence_high
  elseif c >= 0.40 then return P.confidence_med
  else return P.confidence_low end
end

function M.ready()
  return {
    type       = "ReadyCard",
    dismiss_ms = A.DISMISS_MS and A.DISMISS_MS.ReadyCard or 0,
    -- Visual: hexagon core + 3 asymmetric partial-arc rings + 4 satellite dots
    -- Rendered by renderer.lua draw_ready()
  }
end

function M.saved_memory(label)
  return {
    type       = "SavedMemoryCard",
    dismiss_ms = A.DISMISS_MS and A.DISMISS_MS.SavedMemoryCard or 1200,
    primary    = label or "Memory saved",
    -- Visual: mid-draw checkmark + seal arc + inline SAVED text
  }
end

function M.query_listening()
  return {
    type       = "QueryListeningCard",
    dismiss_ms = A.DISMISS_MS and A.DISMISS_MS.QueryListeningCard or 0,
    -- Visual: sine-envelope waveform + cardioid mic glyph, no text label
  }
end

function M.loading()
  return {
    type       = "LoadingCard",
    dismiss_ms = A.DISMISS_MS and A.DISMISS_MS.LoadingCard or 0,
    -- Visual: ghost rings + bright arc with 3 echoes + pulsing center dot
  }
end

function M.object_recall(o)
  local obj      = o.object or ""
  local place    = o.place  or ""
  local detail   = o.detail or ""
  local lastseen = o.last_seen or ""
  local conf     = o.confidence
  -- Truncate detail: 17 chars + ellipsis
  if #detail > 18 then detail = detail:sub(1,17) .. "\xE2\x80\xA6" end
  return {
    type       = "ObjectRecallCard",
    dismiss_ms = A.DISMISS_MS and A.DISMISS_MS.ObjectRecallCard or 3500,
    object     = obj,
    primary    = obj,
    place      = place,
    detail     = detail,
    last_seen  = lastseen,
    footer     = lastseen,
    confidence = conf,
    conf_color = conf_color(conf),
    -- Visual: Bezier trace, diamond jewel+orbit arcs, place at curve endpoint,
    --         detail in [ ... ] bracket
  }
end

function M.commitment_recall(c)
  local person = c.person or ""
  local task   = c.task or ""
  local due    = c.due or ""
  local conf   = c.confidence
  return {
    type       = "CommitmentRecallCard",
    dismiss_ms = A.DISMISS_MS and A.DISMISS_MS.CommitmentRecallCard or 4000,
    person     = person,
    primary    = task,
    task       = task,
    eyebrow    = "You promised " .. person,
    due        = due,
    footer     = due,
    confidence = conf,
    conf_color = conf_color(conf),
    -- Visual: 3 linked chain rects, last link bright, connector lines
  }
end

function M.proactive_memory(p)
  local summary = p.summary or ""
  local person  = p.person
  local payload = {
    type       = "ProactiveMemoryCard",
    dismiss_ms = A.DISMISS_MS and A.DISMISS_MS.ProactiveMemoryCard or 3500,
    primary    = summary,
    summary    = summary,
    person     = person,
    -- Visual: 5-ray radial field, tip bloom, LAST TIME HERE eyebrow
  }
  if person then payload.footer = "With " .. person end
  return payload
end

function M.person_context(p)
  return {
    type      = "PersonContextCard",
    dismiss_ms = A.DISMISS_MS and A.DISMISS_MS.PersonContextCard or 3500,
    primary   = p.person or "",
    headline  = p.headline or "",
    detail    = p.detail or "",
    -- Visual: polar segment array (12 segs, 3 lit), name on ring zone
  }
end

function M.privacy_veil()
  return {
    type       = "PrivacyVeilCard",
    dismiss_ms = A.DISMISS_MS and A.DISMISS_MS.PrivacyVeilCard or 0,
    primary    = "Privacy Veil",
    -- Visual: shield+pause-bars glyph, breach halo (340 deg arc), red/amber palette
  }
end

function M.error_card(msg)
  return {
    type       = "ErrorCard",
    dismiss_ms = A.DISMISS_MS and A.DISMISS_MS.ErrorCard or 4000,
    primary    = msg or "Try again",
    -- Visual: amber outline triangle + exclamation + telemetry text
  }
end

function M.low_confidence()
  return {
    type       = "LowConfidenceCard",
    dismiss_ms = A.DISMISS_MS and A.DISMISS_MS.LowConfidenceCard or 3000,
    primary    = "Not sure",
    confidence = 0.0,
    -- Visual: point_cloud_text approximation (ghost text fallback on device)
  }
end

-- ---------------------------------------------------------------------------
-- O3 conversation cards (Veritas / answer-ahead / Oracle / Listen!). Payloads
-- arrive from the host; the constructors pass the fields through and set the
-- travel-ring color (conf_color) so the focus intro matches the verdict/tone.
-- The Meridian Solid materials + Lumen animation live in renderer.lua.
-- ---------------------------------------------------------------------------

local FACT_COLOR = {
  supported          = P.accent_success,
  disputed           = P.warning_amber,
  self_contradiction = P.accent_attention,
  unverified         = P.text_ghost,
}

function M.fact_check(c)
  local verdict = c.verdict or "unverified"
  return {
    type          = "FactCheckCard",
    dismiss_ms    = A.DISMISS_MS and A.DISMISS_MS.FactCheckCard or 7000,
    verdict       = verdict,
    eyebrow       = c.eyebrow or "",
    primary       = c.primary or c.claim or "",
    detail        = c.detail or c.basis or "",
    footer        = c.footer or "",
    corroboration = c.corroboration or "",
    conf_color    = FACT_COLOR[verdict] or P.text_ghost,
    -- Visual: bloomed verdict ring, glass pane, hero claim, dim-twin basis
  }
end

function M.answer_ahead(c)
  return {
    type       = "AnswerAheadCard",
    dismiss_ms = A.DISMISS_MS and A.DISMISS_MS.AnswerAheadCard or 8000,
    eyebrow    = c.eyebrow or "ON THE TIP OF YOUR TONGUE",
    primary    = c.primary or c.answer or "",
    detail     = c.detail or c.question or "",
    footer     = c.footer or "",
    conf_color = P.accent_memory,
    -- Visual: quiet memory pane, hero answer, cooled question beneath
  }
end

function M.oracle_reply(c)
  local action = c.kind == "action"
  return {
    type       = "OracleReplyCard",
    dismiss_ms = A.DISMISS_MS and A.DISMISS_MS.OracleReplyCard or 6000,
    kind       = c.kind or "answer",
    primary    = c.primary or c.text or "",
    conf_color = action and P.accent_success or P.accent_memory,
    -- Visual: memory/success pane, ORACLE eyebrow with a bloom cue, hero reply
  }
end

function M.hark(c)
  local urgent = c.importance == "urgent"
  return {
    type       = "HarkCard",
    dismiss_ms = A.DISMISS_MS and A.DISMISS_MS.HarkCard or 6500,
    importance = c.importance or "normal",
    primary    = c.primary or c.clue or "",
    detail     = c.detail or "",
    conf_color = urgent and P.warning_amber or P.accent_memory,
    -- Visual: bloomed Listen! ring that breathes on hold, hero clue, cooled detail
  }
end

return M
