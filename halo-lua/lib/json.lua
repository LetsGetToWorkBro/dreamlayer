-- lib/json.lua
-- Minimal but complete pure-Lua JSON decoder and encoder.
-- Compatible with Lua 5.1+ (no utf8 lib required).
-- Used by host_comm when halo.json is not available (emulator, CI).
--
-- API:
--   local json = require("lib.json")
--   local tbl  = json.decode(str)   -- string -> table/value, errors on bad input
--   local str  = json.encode(tbl)   -- table/value -> string

local M = {}

-- ---------------------------------------------------------------------------
-- DECODE
-- ---------------------------------------------------------------------------
local function decode_value(s, i)
  -- skip whitespace
  i = s:match('^%s*()', i)
  local c = s:sub(i, i)

  if c == '{' then
    return M._decode_object(s, i)
  elseif c == '[' then
    return M._decode_array(s, i)
  elseif c == '"' then
    return M._decode_string(s, i)
  elseif c == 't' then
    assert(s:sub(i, i+3) == 'true', 'invalid token at ' .. i)
    return true, i + 4
  elseif c == 'f' then
    assert(s:sub(i, i+4) == 'false', 'invalid token at ' .. i)
    return false, i + 5
  elseif c == 'n' then
    assert(s:sub(i, i+3) == 'null', 'invalid token at ' .. i)
    return nil, i + 4  -- returns nil; callers handle missing keys
  elseif c == '-' or c:match('%d') then
    return M._decode_number(s, i)
  else
    error('unexpected character ' .. c .. ' at position ' .. i)
  end
end

function M._decode_object(s, i)
  local obj = {}
  i = i + 1  -- skip '{'
  i = s:match('^%s*()', i)
  if s:sub(i, i) == '}' then return obj, i + 1 end
  while true do
    i = s:match('^%s*()', i)
    assert(s:sub(i, i) == '"', 'expected string key at ' .. i)
    local key, ni = M._decode_string(s, i)
    i = s:match('^%s*()', ni)
    assert(s:sub(i, i) == ':', 'expected ":" at ' .. i)
    i = s:match('^%s*()', i + 1)
    local val, vi = decode_value(s, i)
    obj[key] = val
    i = s:match('^%s*()', vi)
    local ch = s:sub(i, i)
    if ch == '}' then return obj, i + 1 end
    assert(ch == ',', 'expected "," or "}" at ' .. i)
    i = i + 1
  end
end

function M._decode_array(s, i)
  local arr = {}
  i = i + 1  -- skip '['
  i = s:match('^%s*()', i)
  if s:sub(i, i) == ']' then return arr, i + 1 end
  while true do
    local val, ni = decode_value(s, i)
    arr[#arr + 1] = val
    i = s:match('^%s*()', ni)
    local ch = s:sub(i, i)
    if ch == ']' then return arr, i + 1 end
    assert(ch == ',', 'expected "," or "]" at ' .. i)
    i = s:match('^%s*()', i + 1)
  end
end

function M._decode_string(s, i)
  i = i + 1  -- skip opening '"'
  local parts = {}
  while true do
    local j = s:find('["\\]', i)
    if not j then error('unterminated string') end
    if j > i then parts[#parts + 1] = s:sub(i, j - 1) end
    local ch = s:sub(j, j)
    if ch == '"' then
      return table.concat(parts), j + 1
    end
    -- escape sequence
    local esc = s:sub(j + 1, j + 1)
    local esc_map = {
      ['"'] = '"', ['\\'] = '\\', ['/'] = '/',
      ['b']  = '\b', ['f'] = '\f', ['n'] = '\n',
      ['r']  = '\r', ['t'] = '\t',
    }
    if esc_map[esc] then
      parts[#parts + 1] = esc_map[esc]
      i = j + 2
    elseif esc == 'u' then
      -- \uXXXX: decode codepoint; for BMP just store as-is (ASCII range only needed)
      local hex = s:sub(j + 2, j + 5)
      local cp  = tonumber(hex, 16) or 0
      if cp < 0x80 then
        parts[#parts + 1] = string.char(cp)
      elseif cp < 0x800 then
        parts[#parts + 1] = string.char(
          0xC0 + math.floor(cp / 64),
          0x80 + (cp % 64))
      else
        parts[#parts + 1] = string.char(
          0xE0 + math.floor(cp / 4096),
          0x80 + math.floor((cp % 4096) / 64),
          0x80 + (cp % 64))
      end
      i = j + 6
    else
      error('unknown escape \\' .. esc)
    end
  end
end

function M._decode_number(s, i)
  local num_str = s:match('^-?%d+%.?%d*[eE]?[+-]?%d*', i)
  assert(num_str, 'invalid number at ' .. i)
  return tonumber(num_str), i + #num_str
end

function M.decode(s)
  assert(type(s) == 'string', 'json.decode expects a string')
  local val, i = decode_value(s, 1)
  i = s:match('^%s*()', i)
  assert(i > #s, 'trailing garbage after JSON value')
  return val
end

-- ---------------------------------------------------------------------------
-- ENCODE
-- ---------------------------------------------------------------------------
local encode_value  -- forward declaration

local function encode_string(s)
  return '"' .. s:gsub('["\\\n\r\t]', function(c)
    local esc = { ['"']='\\"', ['\\']='\\\\',
                  ['\n']='\\n', ['\r']='\\r', ['\t']='\\t' }
    return esc[c] or c
  end) .. '"'
end

local function is_array(t)
  local n = 0
  for _ in pairs(t) do n = n + 1 end
  return n == #t
end

local function encode_table(t, depth)
  depth = depth or 0
  assert(depth < 50, 'json.encode: table too deeply nested')
  if is_array(t) then
    local parts = {}
    for _, v in ipairs(t) do
      parts[#parts + 1] = encode_value(v, depth + 1)
    end
    return '[' .. table.concat(parts, ',') .. ']'
  else
    local parts = {}
    for k, v in pairs(t) do
      assert(type(k) == 'string', 'json.encode: table keys must be strings')
      parts[#parts + 1] = encode_string(k) .. ':' .. encode_value(v, depth + 1)
    end
    table.sort(parts)  -- deterministic output
    return '{' .. table.concat(parts, ',') .. '}'
  end
end

encode_value = function(v, depth)
  local t = type(v)
  if t == 'nil'     then return 'null'
  elseif t == 'boolean' then return tostring(v)
  elseif t == 'number'  then
    if v ~= v then return 'null' end  -- NaN
    if v == math.huge or v == -math.huge then return 'null' end
    -- emit integer if possible
    if v == math.floor(v) and math.abs(v) < 1e15 then
      return string.format('%d', v)
    end
    return string.format('%.14g', v)
  elseif t == 'string' then return encode_string(v)
  elseif t == 'table'  then return encode_table(v, depth)
  else
    error('json.encode: unsupported type ' .. t)
  end
end

function M.encode(v)
  return encode_value(v, 0)
end

return M
