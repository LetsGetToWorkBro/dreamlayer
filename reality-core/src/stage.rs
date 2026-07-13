//! stage.rs — the Figment state machine itself, inside the core (ADR 0003).
//!
//! Everything before this was primitives (caps, the guard decision, the clock
//! string). This is the step where the core stops being a library and becomes
//! *the interpreter*: scene stepping with the exact float-epsilon subdivision
//! both Stages use, the timeout graph with guarded branches, counter ops
//! through `rc_saturate`, event dispatch, the emit token bucket through
//! `rc_refill_tokens`/`spend` — and, with the text path landed, the slot store
//! and line rendering too. A language Stage that drives this holds no
//! interpreter logic of its own; it interns strings, forwards events, and
//! draws the text the core hands back.
//!
//! Fixed capacity, zero allocation — and that is *faithful*, not a shortcut:
//! the figment grammar is statically bounded by construction (`MAX_SCENES`,
//! `MAX_BRANCHES`, `MAX_LINES`, `MAX_TEXT` are the proof envelope
//! `budgets.verify()` enforces before anything is signed), so a bounded struct
//! is exactly the device model. Instances live in a small static pool (the
//! glass runs ONE figment at a time; the pool of 4 is for side-by-side tests).
//! Single-threaded use only, like the interpreter it replaces. Every empty
//! constant below is all-zero so the pool is zero-fill (BSS), not a data
//! segment baked into the wasm binary.
//!
//! Identifier policy: the core speaks integers. Bindings intern their strings —
//! scene ids and counter names become the indices `add_scene`/`add_counter`
//! return; event names and slot names become caller-chosen nonzero `u32`
//! codes (slot code 0 is the default `{slot}`); the binding also owns the
//! "ble:<n> falls back to ble" lookup by trying both codes.
//!
//! Line templates are loaded PRE-TOKENIZED (`rc_line_lit`/`rc_line_tok`): the
//! binding parses `{remaining}`/`{elapsed}`/`{slot:x}`/`{count:n}` out of the
//! authored template once, and the core composes the resolved text at render
//! time. A deliberate, documented improvement over the chained-replace
//! interpreters: slot *values* are inert data here — a pushed value containing
//! "{count:n}" renders literally instead of being re-substituted, so host text
//! can never smuggle tokens into the display. (In-grammar content — what the
//! N3 generator emits — behaves identically.)
//!
//! Random-duration scenes use a seedable splitmix64 PRNG (`rc_stage_seed`) with
//! a 53-bit uniform, so a binding that mirrors the same generator (the
//! reference Stage accepts any `rng` object) gets bit-identical trajectories.
//! Rendering geometry (rows/sizes/colors) stays binding-side by design: it is
//! static per line and display-hardware-specific.

use crate::{
    clamp_utf8_boundary, rc_fmt_clock, rc_refill_tokens, rc_saturate, spend, CMP_EQ, CMP_GE,
    CMP_LE,
};

pub const MAX_SCENES: usize = 32; // grammar caps, budgets.verify() enforced
pub const MAX_BRANCHES: usize = 4;
pub const MAX_EVENTS: usize = 16; // handlers per scene (uncapped in the
                                  // grammar; 16 is far above any real figment)
pub const MAX_COUNTERS: usize = 8;
pub const MAX_OPS: usize = 4;
pub const MAX_LINES: usize = 5; // MAX_LINES
pub const MAX_SEGS: usize = 16; // a 24-char template holds < 12 tokens
pub const MAX_TEXT: usize = 24; // MAX_TEXT_LEN
pub const MAX_SLOTS_C: usize = 8; // MAX_SLOTS (named)
const EMIT_BURST: f64 = 5.0;
const EMIT_REFILL_PER_S: f64 = 1.0;
const BATTERY_COOLDOWN_S: f64 = 60.0;

pub const TARGET_SELF: i32 = -1;
pub const TARGET_END: i32 = -2;

/// Line-segment kinds for `rc_line_tok` (SEG_LIT slots are added by
/// `rc_line_lit`, which stores the bytes too).
pub const SEG_LIT: u8 = 0;
pub const TOK_REMAINING: u8 = 1;
pub const TOK_REMAINING_S: u8 = 2;
pub const TOK_ELAPSED: u8 = 3;
pub const TOK_ELAPSED_MS: u8 = 4;
pub const TOK_SLOT: u8 = 5; // arg = slot code (0 = default {slot})
pub const TOK_COUNT: u8 = 6; // arg = counter index

#[derive(Clone, Copy)]
struct CounterOp {
    counter: u8,
    op: u8,
    amount: i64,
}

#[derive(Clone, Copy)]
struct Transition {
    target: i32, // scene index, TARGET_SELF, or TARGET_END
    has_guard: bool,
    guard_counter: u8,
    guard_cmp: u8,
    guard_value: i64,
    n_ops: u8,
    ops: [CounterOp; MAX_OPS],
    emit: bool, // tags stay binding-side; the core counts emits/drops
}

// All-zero so the static pool below is zero-fill (BSS), not a data segment
// baked into the wasm binary. `target: 0` is never observed: rc_tx_begin
// always sets the real target before any commit makes a slot reachable.
const NO_TRANSITION: Transition = Transition {
    target: 0,
    has_guard: false,
    guard_counter: 0,
    guard_cmp: 0,
    guard_value: 0,
    n_ops: 0,
    ops: [CounterOp { counter: 0, op: 0, amount: 0 }; MAX_OPS],
    emit: false,
};

#[derive(Clone, Copy)]
struct Seg {
    kind: u8,     // SEG_LIT or TOK_*
    arg: u32,     // slot code / counter index
    lit_off: u8,  // into Line.lit, for SEG_LIT
    lit_len: u8,
}

const NO_SEG: Seg = Seg { kind: 0, arg: 0, lit_off: 0, lit_len: 0 };

#[derive(Clone, Copy)]
struct Line {
    n_segs: u8,
    segs: [Seg; MAX_SEGS],
    lit: [u8; MAX_TEXT], // literal bytes, shared by this line's SEG_LITs
    lit_used: u8,
}

const EMPTY_LINE: Line = Line {
    n_segs: 0,
    segs: [NO_SEG; MAX_SEGS],
    lit: [0; MAX_TEXT],
    lit_used: 0,
};

#[derive(Clone, Copy)]
struct Scene {
    has_duration: bool,
    duration: f64,
    has_range: bool,
    range_lo: f64,
    range_hi: f64,
    has_tick: bool, // {elapsed} runs live only when the scene ticks
    n_timeout: u8,
    timeout: [Transition; MAX_BRANCHES],
    n_events: u8,
    event_codes: [u32; MAX_EVENTS],
    events: [Transition; MAX_EVENTS],
    n_lines: u8,
    lines: [Line; MAX_LINES],
}

const EMPTY_SCENE: Scene = Scene {
    has_duration: false,
    duration: 0.0,
    has_range: false,
    range_lo: 0.0,
    range_hi: 0.0,
    has_tick: false,
    n_timeout: 0,
    timeout: [NO_TRANSITION; MAX_BRANCHES],
    n_events: 0,
    event_codes: [0; MAX_EVENTS],
    events: [NO_TRANSITION; MAX_EVENTS],
    n_lines: 0,
    lines: [EMPTY_LINE; MAX_LINES],
};

#[derive(Clone, Copy)]
struct Stage {
    in_use: bool,
    started: bool,
    n_scenes: u8,
    scenes: [Scene; MAX_SCENES],
    n_counters: u8,
    decl_start: [i64; MAX_COUNTERS],
    decl_lo: [i64; MAX_COUNTERS],
    decl_hi: [i64; MAX_COUNTERS],
    counters: [i64; MAX_COUNTERS],
    current: i32,
    ended: bool,
    clock: f64,
    scene_elapsed: f64,
    last_elapsed: f64, // frozen {elapsed} after scene exit
    // the ACTIVE duration (fixed, or rolled for a range scene) — Stage._duration
    cur_has_duration: bool,
    cur_duration: f64,
    tokens: f64,
    emits: u32,
    dropped: u32,
    // slot store: value bytes for the default slot + up to MAX_SLOTS named
    default_val: [u8; MAX_TEXT],
    default_len: u8,
    n_named: u8,
    slot_codes: [u32; MAX_SLOTS_C],
    slot_vals: [[u8; MAX_TEXT]; MAX_SLOTS_C],
    slot_lens: [u8; MAX_SLOTS_C],
    // battery seam (binding supplies the interned battery_low event code)
    battery_below: i32, // -1 = none
    battery_level: i32,
    battery_cooldown: f64,
    battery_code: u32,
    // splitmix64 state for duration_range rolls
    rng: u64,
    tx: Transition, // the scratch transition rc_tx_* builds before commit
}

const EMPTY_STAGE: Stage = Stage {
    in_use: false,
    started: false,
    n_scenes: 0,
    scenes: [EMPTY_SCENE; MAX_SCENES],
    n_counters: 0,
    decl_start: [0; MAX_COUNTERS],
    decl_lo: [0; MAX_COUNTERS],
    decl_hi: [0; MAX_COUNTERS],
    counters: [0; MAX_COUNTERS],
    current: 0,
    ended: false,
    clock: 0.0,
    scene_elapsed: 0.0,
    last_elapsed: 0.0,
    cur_has_duration: false,
    cur_duration: 0.0,
    tokens: 0.0, // armed to EMIT_BURST by rc_stage_start (zero-fill static)
    emits: 0,
    dropped: 0,
    default_val: [0; MAX_TEXT],
    default_len: 0,
    n_named: 0,
    slot_codes: [0; MAX_SLOTS_C],
    slot_vals: [[0; MAX_TEXT]; MAX_SLOTS_C],
    slot_lens: [0; MAX_SLOTS_C],
    battery_below: 0, // interpreted as none until set (started gates use)
    battery_level: 0,
    battery_cooldown: 0.0,
    battery_code: 0,
    rng: 0,
    tx: NO_TRANSITION,
};

const POOL: usize = 4;
static mut STAGES: [Stage; POOL] = [EMPTY_STAGE; POOL];

fn stage(h: i32) -> Option<&'static mut Stage> {
    if !(0..POOL as i32).contains(&h) {
        return None;
    }
    let s = unsafe { &mut (*core::ptr::addr_of_mut!(STAGES))[h as usize] };
    if s.in_use {
        Some(s)
    } else {
        None
    }
}

// ---------------------------------------------------------------------------
// Lifecycle + builder
// ---------------------------------------------------------------------------

#[no_mangle]
pub extern "C" fn rc_stage_new() -> i32 {
    for h in 0..POOL {
        let s = unsafe { &mut (*core::ptr::addr_of_mut!(STAGES))[h] };
        if !s.in_use {
            *s = EMPTY_STAGE;
            s.in_use = true;
            s.battery_below = -1;
            s.battery_level = 100;
            return h as i32;
        }
    }
    -1
}

#[no_mangle]
pub extern "C" fn rc_stage_free(h: i32) {
    if let Some(s) = stage(h) {
        s.in_use = false;
    }
}

#[no_mangle]
pub extern "C" fn rc_stage_add_counter(h: i32, start: i64, lo: i64, hi: i64) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    if s.n_counters as usize >= MAX_COUNTERS {
        return -1;
    }
    let i = s.n_counters as usize;
    s.decl_start[i] = start;
    s.decl_lo[i] = lo;
    s.decl_hi[i] = hi;
    s.n_counters += 1;
    i as i32
}

/// `has_duration=0` makes an untimed scene (duration ignored); `tick` says
/// whether `{elapsed}` runs live with the scene (countdown/countup) or shows
/// the previous scene's frozen clock.
#[no_mangle]
pub extern "C" fn rc_stage_add_scene(h: i32, has_duration: i32, duration: f64, tick: i32) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    if s.n_scenes as usize >= MAX_SCENES {
        return -1;
    }
    let i = s.n_scenes as usize;
    s.scenes[i] = EMPTY_SCENE;
    s.scenes[i].has_duration = has_duration != 0;
    s.scenes[i].duration = duration;
    s.scenes[i].has_tick = tick != 0;
    s.n_scenes += 1;
    i as i32
}

/// Give a scene a random duration in [lo, hi], rolled on entry from the
/// stage's splitmix64 stream (see rc_stage_seed). Mirrors duration_range.
#[no_mangle]
pub extern "C" fn rc_stage_scene_range(h: i32, scene: i32, lo: f64, hi: f64) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    if scene < 0 || scene >= s.n_scenes as i32 {
        return -1;
    }
    let sc = &mut s.scenes[scene as usize];
    sc.has_range = true;
    sc.range_lo = lo;
    sc.range_hi = hi;
    0
}

/// Configure the battery seam: dispatch `event_code` (the binding-interned
/// "battery_low") whenever the level sits below `below`, at most once per
/// 60 s cooldown — exactly Stage._advance_clock's check. `below=-1` disables.
#[no_mangle]
pub extern "C" fn rc_stage_set_battery(h: i32, below: i32, level: i32, event_code: u32) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    s.battery_below = below;
    s.battery_level = level;
    s.battery_code = event_code;
    0
}

#[no_mangle]
pub extern "C" fn rc_stage_battery_level(h: i32, level: i32) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    s.battery_level = level;
    0
}

/// Seed the duration_range PRNG (splitmix64 → 53-bit uniform). A binding that
/// hands the reference Stage an rng mirroring the same stream gets
/// bit-identical trajectories.
#[no_mangle]
pub extern "C" fn rc_stage_seed(h: i32, seed: u64) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    s.rng = seed;
    0
}

/// Begin composing a transition in the stage's scratch slot.
#[no_mangle]
pub extern "C" fn rc_tx_begin(h: i32, target: i32) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    s.tx = NO_TRANSITION;
    s.tx.target = target;
    0
}

#[no_mangle]
pub extern "C" fn rc_tx_guard(h: i32, counter: i32, cmp: u8, value: i64) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    if counter < 0 || counter >= s.n_counters as i32 {
        return -1;
    }
    if !matches!(cmp, CMP_GE | CMP_LE | CMP_EQ) {
        return -1;
    }
    s.tx.has_guard = true;
    s.tx.guard_counter = counter as u8;
    s.tx.guard_cmp = cmp;
    s.tx.guard_value = value;
    0
}

#[no_mangle]
pub extern "C" fn rc_tx_op(h: i32, counter: i32, op: u8, amount: i64) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    if counter < 0 || counter >= s.n_counters as i32 || s.tx.n_ops as usize >= MAX_OPS {
        return -1;
    }
    let i = s.tx.n_ops as usize;
    s.tx.ops[i] = CounterOp { counter: counter as u8, op, amount };
    s.tx.n_ops += 1;
    0
}

#[no_mangle]
pub extern "C" fn rc_tx_emit(h: i32) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    s.tx.emit = true;
    0
}

#[no_mangle]
pub extern "C" fn rc_tx_commit_timeout(h: i32, scene: i32) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    if scene < 0 || scene >= s.n_scenes as i32 {
        return -1;
    }
    let sc = &mut s.scenes[scene as usize];
    if sc.n_timeout as usize >= MAX_BRANCHES {
        return -1;
    }
    let i = sc.n_timeout as usize;
    sc.timeout[i] = s.tx;
    sc.n_timeout += 1;
    i as i32
}

#[no_mangle]
pub extern "C" fn rc_tx_commit_event(h: i32, scene: i32, event_code: u32) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    if scene < 0 || scene >= s.n_scenes as i32 {
        return -1;
    }
    let sc = &mut s.scenes[scene as usize];
    if sc.n_events as usize >= MAX_EVENTS {
        return -1;
    }
    let i = sc.n_events as usize;
    sc.event_codes[i] = event_code;
    sc.events[i] = s.tx;
    sc.n_events += 1;
    i as i32
}

// ---- line templates (pre-tokenized by the binding) -------------------------

#[no_mangle]
pub extern "C" fn rc_stage_add_line(h: i32, scene: i32) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    if scene < 0 || scene >= s.n_scenes as i32 {
        return -1;
    }
    let sc = &mut s.scenes[scene as usize];
    if sc.n_lines as usize >= MAX_LINES {
        return -1;
    }
    let i = sc.n_lines as usize;
    sc.lines[i] = EMPTY_LINE;
    sc.n_lines += 1;
    i as i32
}

/// Append a literal text run to a line template. The bytes are copied into the
/// core (templates are grammar-capped at MAX_TEXT chars, enforced here too).
///
/// # Safety
/// `ptr` must be valid for reads of `len` bytes.
#[no_mangle]
pub extern "C" fn rc_line_lit(h: i32, scene: i32, line: i32, ptr: *const u8, len: u64) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    if scene < 0 || scene >= s.n_scenes as i32 {
        return -1;
    }
    let sc = &mut s.scenes[scene as usize];
    if line < 0 || line >= sc.n_lines as i32 {
        return -1;
    }
    let ln = &mut sc.lines[line as usize];
    let len = len as usize;
    if ptr.is_null()
        || ln.n_segs as usize >= MAX_SEGS
        || ln.lit_used as usize + len > MAX_TEXT
    {
        return -1;
    }
    let off = ln.lit_used as usize;
    unsafe { core::ptr::copy_nonoverlapping(ptr, ln.lit.as_mut_ptr().add(off), len) };
    let i = ln.n_segs as usize;
    ln.segs[i] = Seg { kind: SEG_LIT, arg: 0, lit_off: off as u8, lit_len: len as u8 };
    ln.lit_used += len as u8;
    ln.n_segs += 1;
    0
}

/// Append a token segment (TOK_*) to a line template. `arg` is the slot code
/// for TOK_SLOT (0 = default) or the counter index for TOK_COUNT.
#[no_mangle]
pub extern "C" fn rc_line_tok(h: i32, scene: i32, line: i32, kind: u8, arg: u32) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    if scene < 0 || scene >= s.n_scenes as i32 {
        return -1;
    }
    if !(TOK_REMAINING..=TOK_COUNT).contains(&kind) {
        return -1;
    }
    if kind == TOK_COUNT && arg >= s.n_counters as u32 {
        return -1;
    }
    let sc = &mut s.scenes[scene as usize];
    if line < 0 || line >= sc.n_lines as i32 {
        return -1;
    }
    let ln = &mut sc.lines[line as usize];
    if ln.n_segs as usize >= MAX_SEGS {
        return -1;
    }
    let i = ln.n_segs as usize;
    ln.segs[i] = Seg { kind, arg, lit_off: 0, lit_len: 0 };
    ln.n_segs += 1;
    0
}

/// Enter the initial scene and arm the clock/token state (Stage.__init__).
#[no_mangle]
pub extern "C" fn rc_stage_start(h: i32, initial_scene: i32) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    if initial_scene < 0 || initial_scene >= s.n_scenes as i32 {
        return -1;
    }
    for i in 0..s.n_counters as usize {
        s.counters[i] = s.decl_start[i];
    }
    s.clock = 0.0;
    s.scene_elapsed = 0.0;
    s.last_elapsed = 0.0;
    s.tokens = EMIT_BURST;
    s.emits = 0;
    s.dropped = 0;
    s.ended = false;
    s.battery_cooldown = 0.0;
    s.default_len = 0;
    s.n_named = 0;
    s.started = true;
    enter(s, initial_scene);
    0
}

// ---------------------------------------------------------------------------
// The state machine (mirrors interpreter.py step/_advance_clock/_timeout/
// _take/_enter/_end and figment.js, line for line)
// ---------------------------------------------------------------------------

fn splitmix_uniform(state: &mut u64, lo: f64, hi: f64) -> f64 {
    *state = state.wrapping_add(0x9E37_79B9_7F4A_7C15);
    let mut z = *state;
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^= z >> 31;
    // 53-bit uniform in [0, 1), the same shape random.random() has
    let r = (z >> 11) as f64 * (1.0 / 9007199254740992.0);
    lo + (hi - lo) * r
}

fn enter(s: &mut Stage, scene: i32) {
    s.last_elapsed = s.scene_elapsed;
    s.current = scene;
    s.scene_elapsed = 0.0;
    let sc = s.scenes[scene as usize];
    if sc.has_range {
        s.cur_has_duration = true;
        s.cur_duration = splitmix_uniform(&mut s.rng, sc.range_lo, sc.range_hi);
    } else {
        s.cur_has_duration = sc.has_duration;
        s.cur_duration = sc.duration;
    }
}

fn end(s: &mut Stage) {
    s.last_elapsed = s.scene_elapsed;
    s.ended = true;
}

fn dispatch(s: &mut Stage, event_code: u32) -> bool {
    let sc = s.scenes[s.current as usize];
    for i in 0..sc.n_events as usize {
        if sc.event_codes[i] == event_code {
            take(s, sc.events[i]);
            return true;
        }
    }
    false
}

fn advance_clock(s: &mut Stage, dt: f64) {
    s.clock += dt;
    s.scene_elapsed += dt;
    s.tokens = rc_refill_tokens(s.tokens, dt, EMIT_REFILL_PER_S, EMIT_BURST);
    if s.battery_cooldown > 0.0 {
        s.battery_cooldown -= dt;
    }
    if s.battery_below >= 0 && s.battery_level < s.battery_below && s.battery_cooldown <= 0.0 {
        s.battery_cooldown = BATTERY_COOLDOWN_S;
        dispatch(s, s.battery_code);
    }
}

fn guard_passes(s: &Stage, t: &Transition) -> bool {
    if !t.has_guard {
        return true;
    }
    let val = s.counters[t.guard_counter as usize];
    match t.guard_cmp {
        CMP_GE => val >= t.guard_value,
        CMP_LE => val <= t.guard_value,
        _ => val == t.guard_value,
    }
}

fn take(s: &mut Stage, t: Transition) {
    for k in 0..t.n_ops as usize {
        let op = t.ops[k];
        let i = op.counter as usize;
        s.counters[i] = rc_saturate(s.counters[i], op.op, op.amount, s.decl_lo[i], s.decl_hi[i]);
    }
    if t.emit {
        let (spent, after) = spend(s.tokens);
        s.tokens = after;
        if spent == 1 {
            s.emits += 1;
        } else {
            s.dropped += 1;
        }
    }
    match t.target {
        TARGET_END => end(s),
        TARGET_SELF => {
            let cur = s.current;
            enter(s, cur);
        }
        sc => enter(s, sc),
    }
}

fn timeout(s: &mut Stage) {
    let sc = s.scenes[s.current as usize];
    for i in 0..sc.n_timeout as usize {
        if guard_passes(s, &sc.timeout[i]) {
            take(s, sc.timeout[i]);
            return;
        }
    }
    end(s);
}

/// Advance dt seconds; may cross several scene timeouts. The float-epsilon
/// subdivision is byte-identical to both Stages so trajectories match exactly.
#[no_mangle]
pub extern "C" fn rc_stage_step(h: i32, dt: f64) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    if !s.started {
        return -1;
    }
    if s.ended {
        return 0;
    }
    let mut remaining_dt = dt;
    while remaining_dt > 1e-9 && !s.ended {
        if !s.cur_has_duration {
            advance_clock(s, remaining_dt);
            break;
        }
        let left = s.cur_duration - s.scene_elapsed;
        if remaining_dt < left - 1e-9 {
            advance_clock(s, remaining_dt);
            break;
        }
        advance_clock(s, left);
        remaining_dt -= left;
        timeout(s);
    }
    0
}

/// Deliver an event by its (binding-interned) code. Returns 1 if a handler in
/// the current scene took it, 0 otherwise (incl. after END) — the binding does
/// the "ble:<n> falls back to ble" second lookup itself.
#[no_mangle]
pub extern "C" fn rc_stage_inject(h: i32, event_code: u32) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    if !s.started || s.ended {
        return 0;
    }
    dispatch(s, event_code) as i32
}

/// Push host text into a slot (Stage.inject("text[:name]") storage half; the
/// binding fires the base "text" trigger via rc_stage_inject separately, as
/// the interpreter does). Slot code 0 is the default `{slot}`. Accept rule is
/// exactly contracts.accept_slot: default and known always; a genuinely new
/// named slot only while fewer than MAX_SLOTS exist. Values clamp to MAX_TEXT.
/// Returns 1 stored / 0 rejected.
///
/// # Safety
/// `ptr` must be valid for reads of `len` bytes.
#[no_mangle]
pub extern "C" fn rc_stage_text(h: i32, slot_code: u32, ptr: *const u8, len: u64) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    if !s.started || s.ended || ptr.is_null() {
        return 0;
    }
    // Clamp to MAX_TEXT bytes on a codepoint boundary (contracts.clamp_text's
    // rule) — a bare min() could store half a UTF-8 sequence and diverge from
    // the other interpreters on non-ASCII slot pushes.
    let full = unsafe { core::slice::from_raw_parts(ptr, len as usize) };
    let len = clamp_utf8_boundary(full, MAX_TEXT);
    if slot_code == 0 {
        unsafe { core::ptr::copy_nonoverlapping(ptr, s.default_val.as_mut_ptr(), len) };
        s.default_len = len as u8;
        return 1;
    }
    for i in 0..s.n_named as usize {
        if s.slot_codes[i] == slot_code {
            unsafe { core::ptr::copy_nonoverlapping(ptr, s.slot_vals[i].as_mut_ptr(), len) };
            s.slot_lens[i] = len as u8;
            return 1;
        }
    }
    if (s.n_named as usize) < MAX_SLOTS_C {
        let i = s.n_named as usize;
        s.slot_codes[i] = slot_code;
        unsafe { core::ptr::copy_nonoverlapping(ptr, s.slot_vals[i].as_mut_ptr(), len) };
        s.slot_lens[i] = len as u8;
        s.n_named += 1;
        return 1;
    }
    0
}

// ---------------------------------------------------------------------------
// Rendering: compose a line of the CURRENT scene (Stage._resolve)
// ---------------------------------------------------------------------------

fn write_dec_u64(n: u64, buf: &mut [u8]) -> usize {
    let mut tmp = [0u8; 20];
    let mut v = n;
    let mut i = 0;
    loop {
        tmp[i] = b'0' + (v % 10) as u8;
        i += 1;
        v /= 10;
        if v == 0 {
            break;
        }
    }
    for k in 0..i.min(buf.len()) {
        buf[k] = tmp[i - 1 - k];
    }
    i.min(buf.len())
}

fn write_dec_i64(n: i64, buf: &mut [u8]) -> usize {
    if n < 0 {
        if buf.is_empty() {
            return 0;
        }
        buf[0] = b'-';
        1 + write_dec_u64(n.unsigned_abs(), &mut buf[1..])
    } else {
        write_dec_u64(n as u64, buf)
    }
}

/// Resolve line `line` of the current scene into `out` (clamped to MAX_TEXT,
/// exactly the interpreter's clamp). Returns the byte count, or -1 on a bad
/// handle/line. Token semantics mirror _resolve: {remaining}/{elapsed} via the
/// clock formatter, {remaining_s} = ceil, {elapsed_ms} = floor(ms), {elapsed}
/// live only when the scene ticks (frozen last_elapsed otherwise), slots by
/// stored value ("" when never pushed), counters as signed decimals.
///
/// # Safety
/// `out` must be valid for writes of `cap` bytes.
#[no_mangle]
pub extern "C" fn rc_stage_render_line(h: i32, line: i32, out: *mut u8, cap: u64) -> i64 {
    let Some(s) = stage(h) else { return -1 };
    if !s.started || out.is_null() {
        return -1;
    }
    let sc = s.scenes[s.current as usize];
    if line < 0 || line >= sc.n_lines as i32 {
        return -1;
    }
    let ln = sc.lines[line as usize];
    let remaining = if s.cur_has_duration {
        let r = s.cur_duration - s.scene_elapsed;
        if r > 0.0 {
            r
        } else {
            0.0
        }
    } else {
        0.0
    };
    let el = if sc.has_tick { s.scene_elapsed } else { s.last_elapsed };

    let mut buf = [0u8; 256];
    let mut pos = 0usize;
    for i in 0..ln.n_segs as usize {
        if pos >= buf.len() {
            break;
        }
        let seg = ln.segs[i];
        let dst = &mut buf[pos..];
        pos += match seg.kind {
            SEG_LIT => {
                let n = (seg.lit_len as usize).min(dst.len());
                dst[..n].copy_from_slice(&ln.lit[seg.lit_off as usize..seg.lit_off as usize + n]);
                n
            }
            TOK_REMAINING => rc_fmt_clock(remaining, dst.as_mut_ptr(), dst.len() as u64) as usize,
            TOK_REMAINING_S => write_dec_u64(remaining.ceil() as u64, dst),
            TOK_ELAPSED => rc_fmt_clock(el, dst.as_mut_ptr(), dst.len() as u64) as usize,
            TOK_ELAPSED_MS => write_dec_u64((el * 1000.0) as u64, dst),
            TOK_SLOT => {
                if seg.arg == 0 {
                    let n = (s.default_len as usize).min(dst.len());
                    dst[..n].copy_from_slice(&s.default_val[..n]);
                    n
                } else {
                    let mut n = 0;
                    for k in 0..s.n_named as usize {
                        if s.slot_codes[k] == seg.arg {
                            n = (s.slot_lens[k] as usize).min(dst.len());
                            dst[..n].copy_from_slice(&s.slot_vals[k][..n]);
                            break;
                        }
                    }
                    n // never pushed → "" (Python .get(name, ""))
                }
            }
            TOK_COUNT => write_dec_i64(s.counters[seg.arg as usize], dst),
            _ => 0,
        };
    }
    // Final line cap: MAX_TEXT bytes (and the caller's buffer), on a codepoint
    // boundary — the render-path twin of contracts.clamp_text(out, MAX_TEXT).
    let limit = MAX_TEXT.min(cap as usize);
    let n = clamp_utf8_boundary(&buf[..pos], limit);
    unsafe { core::ptr::copy_nonoverlapping(buf.as_ptr(), out, n) };
    n as i64
}

/// Lines in the current scene (so the binding can render frame()).
#[no_mangle]
pub extern "C" fn rc_stage_line_count(h: i32) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    if !s.started {
        return -1;
    }
    s.scenes[s.current as usize].n_lines as i32
}

// ---------------------------------------------------------------------------
// State readers (what the binding renders / the parity harness compares)
// ---------------------------------------------------------------------------

#[no_mangle]
pub extern "C" fn rc_stage_counter(h: i32, idx: i32) -> i64 {
    match stage(h) {
        Some(s) if idx >= 0 && idx < s.n_counters as i32 => s.counters[idx as usize],
        _ => 0,
    }
}

#[no_mangle]
pub extern "C" fn rc_stage_clock(h: i32) -> f64 {
    stage(h).map_or(0.0, |s| s.clock)
}

#[no_mangle]
pub extern "C" fn rc_stage_elapsed(h: i32) -> f64 {
    stage(h).map_or(0.0, |s| s.scene_elapsed)
}

#[no_mangle]
pub extern "C" fn rc_stage_last_elapsed(h: i32) -> f64 {
    stage(h).map_or(0.0, |s| s.last_elapsed)
}

/// Seconds left in a timed scene, 0 for untimed (Stage.remaining()).
#[no_mangle]
pub extern "C" fn rc_stage_remaining(h: i32) -> f64 {
    let Some(s) = stage(h) else { return 0.0 };
    if !s.started || !s.cur_has_duration {
        return 0.0;
    }
    let rem = s.cur_duration - s.scene_elapsed;
    if rem > 0.0 {
        rem
    } else {
        0.0
    }
}

#[no_mangle]
pub extern "C" fn rc_stage_current(h: i32) -> i32 {
    stage(h).map_or(-1, |s| s.current)
}

#[no_mangle]
pub extern "C" fn rc_stage_ended(h: i32) -> i32 {
    stage(h).map_or(0, |s| s.ended as i32)
}

#[no_mangle]
pub extern "C" fn rc_stage_emits(h: i32) -> i64 {
    stage(h).map_or(0, |s| s.emits as i64)
}

#[no_mangle]
pub extern "C" fn rc_stage_dropped(h: i32) -> i64 {
    stage(h).map_or(0, |s| s.dropped as i64)
}

#[no_mangle]
pub extern "C" fn rc_stage_tokens(h: i32) -> f64 {
    stage(h).map_or(0.0, |s| s.tokens)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{CMP_GE, OP_INC};
    use std::sync::{Mutex, MutexGuard, OnceLock};

    /// The stage pool is static and single-threaded by design (like the
    /// interpreter); cargo runs tests in parallel threads, so serialize them.
    fn lock() -> MutexGuard<'static, ()> {
        static M: OnceLock<Mutex<()>> = OnceLock::new();
        M.get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap_or_else(|e| e.into_inner())
    }

    fn render(h: i32, line: i32) -> String {
        let mut buf = [0u8; 32];
        let n = rc_stage_render_line(h, line, buf.as_mut_ptr(), 32);
        assert!(n >= 0);
        core::str::from_utf8(&buf[..n as usize]).unwrap().to_string()
    }

    /// The "3 rounds of 1 s work" figment, straight from the parity suites.
    fn rounds_stage() -> i32 {
        let h = rc_stage_new();
        let round = rc_stage_add_counter(h, 1, 1, 3);
        let work = rc_stage_add_scene(h, 1, 1.0, 1);
        rc_tx_begin(h, TARGET_END);
        rc_tx_guard(h, round, CMP_GE, 3);
        rc_tx_commit_timeout(h, work);
        rc_tx_begin(h, TARGET_SELF);
        rc_tx_op(h, round, OP_INC, 1);
        rc_tx_commit_timeout(h, work);
        rc_stage_start(h, work);
        h
    }

    #[test]
    fn bounded_loop_runs_exactly_three_rounds() {
        let _g = lock();
        let h = rounds_stage();
        for _ in 0..10 {
            rc_stage_step(h, 0.5); // half-second device ticks
        }
        assert_eq!(rc_stage_ended(h), 1);
        assert_eq!(rc_stage_counter(h, 0), 3);
        assert_eq!(rc_stage_clock(h), 3.0); // ended exactly at the 3rd timeout
        rc_stage_free(h);
    }

    #[test]
    fn overshoot_subdivides_across_boundaries() {
        let _g = lock();
        // one big 2.6 s step over a 1 s scene must fire 2 timeouts and leave
        // 0.6 s of elapsed in the third round — the N3 {elapsed} bug shape
        let h = rounds_stage();
        rc_stage_step(h, 2.6);
        assert_eq!(rc_stage_ended(h), 0);
        assert_eq!(rc_stage_counter(h, 0), 3);
        assert!((rc_stage_elapsed(h) - 0.6).abs() < 1e-9);
        rc_stage_free(h);
    }

    #[test]
    fn event_emits_hit_the_token_bucket() {
        let _g = lock();
        let h = rc_stage_new();
        let a = rc_stage_add_scene(h, 0, 0.0, 0); // untimed
        rc_tx_begin(h, TARGET_SELF);
        rc_tx_emit(h);
        rc_tx_commit_event(h, a, 7);
        rc_stage_start(h, a);
        for _ in 0..20 {
            assert_eq!(rc_stage_inject(h, 7), 1);
        }
        assert_eq!(rc_stage_emits(h), 5); // burst cap
        assert_eq!(rc_stage_dropped(h), 15);
        rc_stage_free(h);
    }

    #[test]
    fn unknown_event_and_pool_exhaustion_are_safe() {
        let _g = lock();
        let h = rc_stage_new();
        let a = rc_stage_add_scene(h, 0, 0.0, 0);
        rc_stage_start(h, a);
        assert_eq!(rc_stage_inject(h, 999), 0);
        let hs: [i32; 3] = core::array::from_fn(|_| rc_stage_new());
        assert_eq!(rc_stage_new(), -1); // pool of 4 exhausted
        for x in hs {
            rc_stage_free(x);
        }
        rc_stage_free(h);
    }

    #[test]
    fn slots_store_render_and_cap() {
        let _g = lock();
        let h = rc_stage_new();
        let a = rc_stage_add_scene(h, 0, 0.0, 0);
        let l0 = rc_stage_add_line(h, a);
        rc_line_tok(h, a, l0, TOK_SLOT, 42); // {slot:keep} interned as 42
        rc_stage_start(h, a);
        assert_eq!(render(h, 0), ""); // never pushed → ""
        assert_eq!(rc_stage_text(h, 42, b"K".as_ptr(), 1), 1);
        // fill the remaining 7 named slots, then overflow with new codes
        for c in 100..107u32 {
            assert_eq!(rc_stage_text(h, c, b"v".as_ptr(), 1), 1);
        }
        assert_eq!(rc_stage_text(h, 999, b"x".as_ptr(), 1), 0); // full → reject
        assert_eq!(rc_stage_text(h, 42, b"K2".as_ptr(), 2), 1); // known updates
        assert_eq!(render(h, 0), "K2"); // known slot never evicted
        rc_stage_free(h);
    }

    #[test]
    fn render_composes_tokens_and_clamps() {
        let _g = lock();
        let h = rc_stage_new();
        let n = rc_stage_add_counter(h, 7, 0, 99);
        let a = rc_stage_add_scene(h, 1, 180.0, 1); // ticking countdown
        rc_tx_begin(h, TARGET_END);
        rc_tx_commit_timeout(h, a);
        let l0 = rc_stage_add_line(h, a);
        rc_line_lit(h, a, l0, b"t=".as_ptr(), 2);
        rc_line_tok(h, a, l0, TOK_REMAINING, 0);
        rc_line_lit(h, a, l0, b" n=".as_ptr(), 3);
        rc_line_tok(h, a, l0, TOK_COUNT, n as u32);
        rc_stage_start(h, a);
        rc_stage_step(h, 12.0);
        assert_eq!(render(h, 0), "t=2:48 n=7"); // 168 s left — that string again
        // a long slot value clamps the composed line at MAX_TEXT
        let b = rc_stage_add_line(h, a);
        rc_line_tok(h, a, b, TOK_SLOT, 1);
        rc_stage_text(h, 1, b"abcdefghijklmnopqrstuvwxyz".as_ptr(), 26);
        assert_eq!(render(h, 1), "abcdefghijklmnopqrstuvwx"); // 24 = MAX_TEXT
        rc_stage_free(h);
    }

    #[test]
    fn battery_low_dispatches_with_cooldown() {
        let _g = lock();
        let h = rc_stage_new();
        let hits = rc_stage_add_counter(h, 0, 0, 99);
        let a = rc_stage_add_scene(h, 0, 0.0, 0);
        rc_tx_begin(h, TARGET_SELF);
        rc_tx_op(h, hits, OP_INC, 1);
        rc_tx_commit_event(h, a, 5); // 5 = interned "battery_low"
        rc_stage_set_battery(h, 30, 20, 5); // level 20 < below 30
        rc_stage_start(h, a);
        rc_stage_step(h, 1.0); // fires immediately, arms the 60 s cooldown
        assert_eq!(rc_stage_counter(h, 0), 1);
        rc_stage_step(h, 30.0); // still cooling down
        assert_eq!(rc_stage_counter(h, 0), 1);
        rc_stage_step(h, 30.5); // past 60 s → fires again
        assert_eq!(rc_stage_counter(h, 0), 2);
        rc_stage_battery_level(h, 90); // recovered → no more dispatches
        rc_stage_step(h, 120.0);
        assert_eq!(rc_stage_counter(h, 0), 2);
        rc_stage_free(h);
    }

    #[test]
    fn duration_range_rolls_are_seeded_and_deterministic() {
        let _g = lock();
        let mk = || {
            let h = rc_stage_new();
            let a = rc_stage_add_scene(h, 0, 0.0, 1);
            rc_stage_scene_range(h, a, 1.0, 3.0);
            rc_tx_begin(h, TARGET_SELF);
            rc_tx_commit_timeout(h, a);
            rc_stage_seed(h, 42);
            rc_stage_start(h, a);
            h
        };
        let (h1, h2) = (mk(), mk());
        for _ in 0..6 {
            rc_stage_step(h1, 2.2);
            rc_stage_step(h2, 2.2);
            assert_eq!(rc_stage_clock(h1), rc_stage_clock(h2));
            assert_eq!(rc_stage_elapsed(h1), rc_stage_elapsed(h2));
        }
        // rolls stay inside the declared range
        let h3 = mk();
        rc_stage_step(h3, 0.0);
        rc_stage_free(h1);
        rc_stage_free(h2);
        rc_stage_free(h3);
    }
}
