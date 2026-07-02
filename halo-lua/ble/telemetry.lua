--- ble/telemetry.lua
--- DreamLayer Halo — outbound event telemetry.
---
--- Glasses report key lifecycle events back to the host so the Python
--- side can build feedback loops (adaptive confidence, session analytics,
--- dismissal-rate tracking, etc.).
---
--- Message format (JSON-serialisable dict):
---   { t = "TEL", event = <EVENT_NAME>, ts = <now_ms>, payload = <table|nil> }
---
--- Events:
---   CARD_SHOWN        card became active in renderer (card_type, priority)
---   CARD_DISMISSED    card was dismissed by user tap or auto-expire
---                     (card_type, method: "tap"|"expire"|"superseded")
---   PRIVACY_VEIL    device entered privacy state
---   PRIVACY_RESUMED   device left privacy state
---   QUERY_CANCELLED   user cancelled an in-flight query (double-click)
---   BLE_ERROR         BLE receive error (raw string)
---
--- Public API:
---   telemetry.bind(send_fn)          wire transport; send_fn(msg_table)
---   telemetry.emit(event, payload)   fire an event
---   telemetry.last()                 returns last emitted {event, ts, payload}
---                                    (useful for tests; nil before first emit)

local telemetry = {}

-- ---------------------------------------------------------------------------
-- Event name constants (exported so callers don't use raw strings)
-- ---------------------------------------------------------------------------
telemetry.CARD_SHOWN      = "CARD_SHOWN"
telemetry.CARD_DISMISSED  = "CARD_DISMISSED"
telemetry.PRIVACY_VEIL  = "PRIVACY_VEIL"
telemetry.PRIVACY_RESUMED = "PRIVACY_RESUMED"
telemetry.QUERY_CANCELLED = "QUERY_CANCELLED"
telemetry.BLE_ERROR       = "BLE_ERROR"

-- ---------------------------------------------------------------------------
-- Internal state
-- ---------------------------------------------------------------------------
local _send_fn  = nil   -- injected transport
local _last     = nil   -- last emitted record

local HAS_FRAME = (type(_G.frame) == "table")

local function _now_ms()
  if HAS_FRAME and frame.time then
    return math.floor(frame.time.utc() * 1000) % (2^31)
  end
  return math.floor(os.clock() * 1000)
end

-- ---------------------------------------------------------------------------
-- Tiny table-to-JSON serialiser (no external deps)
-- Only handles flat tables with string/number/boolean/nil values.
-- ---------------------------------------------------------------------------
local function _to_json(t)
  if type(t) ~= "table" then return "null" end
  local parts = {}
  for k, v in pairs(t) do
    local key = '"' .. tostring(k) .. '"'
    local val
    if     type(v) == "string"  then val = '"' .. v:gsub('"', '\\"') .. '"'
    elseif type(v) == "number"  then val = tostring(v)
    elseif type(v) == "boolean" then val = tostring(v)
    else                             val = '"' .. tostring(v) .. '"'
    end
    parts[#parts + 1] = key .. ":" .. val
  end
  return "{" .. table.concat(parts, ",") .. "}"
end

-- ---------------------------------------------------------------------------
-- Public API
-- ---------------------------------------------------------------------------

--- Bind a transport function.  send_fn receives a plain Lua table.
--- In production this wraps host_comm.send(); in tests it can be any fn.
function telemetry.bind(send_fn)
  _send_fn = send_fn
end

--- Emit a telemetry event.
--- event   : one of the telemetry.* constants
--- payload : optional flat table of extra fields
function telemetry.emit(event, payload)
  local ts  = _now_ms()
  local msg = { t = "TEL", event = event, ts = ts }
  if payload then
    for k, v in pairs(payload) do msg[k] = v end
  end

  _last = { event = event, ts = ts, payload = payload }

  if _send_fn then
    local ok, err = pcall(_send_fn, msg)
    if not ok then
      -- Never let telemetry crash the main loop
      print("[telemetry] send error: " .. tostring(err))
    end
  end
end

--- Returns the last emitted record, or nil.
function telemetry.last()
  return _last
end

return telemetry
