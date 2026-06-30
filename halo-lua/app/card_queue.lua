--- app/card_queue.lua
--- Priority card queue with timed auto-dismiss.
---
--- Priorities (lower number = higher urgency, shown first)
---   1  URGENT   — direct recall triggered by user button press
---   2  CONTEXT  — proactive memory surfaced by AI
---   3  AMBIENT  — low-priority background context
---
--- API
---   CardQueue.new()               → queue instance
---   q:push(card, priority?)       → enqueues card (default priority = CONTEXT)
---   q:tick(now_ms)                → drives auto-dismiss; returns card to show or nil
---   q:dismiss(now_ms)             → forcibly dismiss current card, advance queue
---   q:peek()                      → current card without side effects
---   q:clear()                     → flush entire queue
---   q:len()                       → total cards waiting (excluding active)
---
--- Auto-dismiss:
---   When a card becomes active, its dismiss_ms from animations.lua starts a
---   countdown.  q:tick(now_ms) checks the clock and pops to next when expired.
---   Cards with dismiss_ms == 0 are "sticky" — they never auto-dismiss.
---
--- Usage (in main.lua update loop):
---   local now = frame.time.utc()   -- or a ms counter from your BLE tick
---   local card = queue:tick(now)
---   if card then renderer.draw(card) end

local A = require("display.animations")

local CardQueue = {}
CardQueue.__index = CardQueue

-- Priority constants
CardQueue.URGENT  = 1
CardQueue.CONTEXT = 2
CardQueue.AMBIENT = 3


-- ---------------------------------------------------------------------------
-- Constructor
-- ---------------------------------------------------------------------------

function CardQueue.new()
  return setmetatable({
    _heap        = {},   -- min-heap: {priority, seq, card}
    _seq         = 0,    -- monotonic tie-breaker keeps FIFO within same priority
    _active      = nil,  -- card currently on display
    _active_at   = nil,  -- ms timestamp when active card was shown
    _dismiss_ms  = nil,  -- cached dismiss_ms for active card
  }, CardQueue)
end


-- ---------------------------------------------------------------------------
-- Heap helpers (min-heap on {priority, seq})
-- ---------------------------------------------------------------------------

local function _cmp(a, b)
  if a[1] ~= b[1] then return a[1] < b[1] end  -- priority
  return a[2] < b[2]                             -- seq (FIFO)
end

local function _sift_up(heap, i)
  while i > 1 do
    local parent = math.floor(i / 2)
    if _cmp(heap[i], heap[parent]) then
      heap[i], heap[parent] = heap[parent], heap[i]
      i = parent
    else
      break
    end
  end
end

local function _sift_down(heap, i)
  local n = #heap
  while true do
    local smallest = i
    local l, r = 2 * i, 2 * i + 1
    if l <= n and _cmp(heap[l], heap[smallest]) then smallest = l end
    if r <= n and _cmp(heap[r], heap[smallest]) then smallest = r end
    if smallest == i then break end
    heap[i], heap[smallest] = heap[smallest], heap[i]
    i = smallest
  end
end

local function _heap_push(heap, item)
  heap[#heap + 1] = item
  _sift_up(heap, #heap)
end

local function _heap_pop(heap)
  if #heap == 0 then return nil end
  local top = heap[1]
  heap[1] = heap[#heap]
  heap[#heap] = nil
  if #heap > 0 then _sift_down(heap, 1) end
  return top
end


-- ---------------------------------------------------------------------------
-- Internal: resolve dismiss_ms for a card
-- ---------------------------------------------------------------------------

local function _resolve_dismiss(card)
  -- Card may carry its own dismiss_ms (set by cards.lua constructors).
  -- Fall back to animations.lua table, then 0 (sticky).
  if card.dismiss_ms and card.dismiss_ms > 0 then
    return card.dismiss_ms
  end
  local from_anim = A.DISMISS_MS and A.DISMISS_MS[card.type]
  if from_anim and from_anim > 0 then return from_anim end
  return 0  -- sticky
end


-- ---------------------------------------------------------------------------
-- Internal: activate next queued card
-- ---------------------------------------------------------------------------

function CardQueue:_activate_next(now_ms)
  local item = _heap_pop(self._heap)
  if item then
    self._active     = item[3]
    self._active_at  = now_ms
    self._dismiss_ms = _resolve_dismiss(item[3])
  else
    self._active     = nil
    self._active_at  = nil
    self._dismiss_ms = nil
  end
end


-- ---------------------------------------------------------------------------
-- Public API
-- ---------------------------------------------------------------------------

--- Push a card onto the queue.
--- @param card      table    Card payload (must have .type field)
--- @param priority  number   CardQueue.URGENT | CONTEXT | AMBIENT  (default CONTEXT)
function CardQueue:push(card, priority)
  assert(card and card.type, "card_queue: card must have a .type field")
  priority = priority or CardQueue.CONTEXT
  self._seq = self._seq + 1
  _heap_push(self._heap, {priority, self._seq, card})

  -- URGENT cards pre-empt the active card immediately (bump current to queue)
  if priority == CardQueue.URGENT and self._active then
    -- Re-queue the current active card at CONTEXT priority so it shows after
    self._seq = self._seq + 1
    _heap_push(self._heap, {CardQueue.CONTEXT, self._seq, self._active})
    self._active    = nil
    self._active_at = nil
    self._dismiss_ms = nil
  end
end

--- Drive the queue forward. Call once per display frame / BLE tick.
--- Returns the card that should currently be on screen (or nil for blank).
--- @param  now_ms  number   Current time in milliseconds
--- @return card|nil
function CardQueue:tick(now_ms)
  -- If nothing active, try to pop next
  if not self._active then
    self:_activate_next(now_ms)
    return self._active
  end

  -- Check auto-dismiss
  if self._dismiss_ms and self._dismiss_ms > 0 then
    local elapsed = now_ms - self._active_at
    if elapsed >= self._dismiss_ms then
      self:_activate_next(now_ms)
    end
  end

  return self._active
end

--- Forcibly dismiss the active card now and advance the queue.
--- @param now_ms  number
function CardQueue:dismiss(now_ms)
  self:_activate_next(now_ms)
end

--- Peek at the currently active card without ticking.
--- @return card|nil
function CardQueue:peek()
  return self._active
end

--- Return the number of cards waiting (not counting the active card).
--- @return number
function CardQueue:len()
  return #self._heap
end

--- Flush all queued and active cards.
function CardQueue:clear()
  self._heap       = {}
  self._active     = nil
  self._active_at  = nil
  self._dismiss_ms = nil
end

return CardQueue
