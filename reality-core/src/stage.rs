//! stage.rs — the Figment state machine itself, inside the core (ADR 0003).
//!
//! Everything before this was primitives (caps, the guard decision, the clock
//! string). This is the step where the core stops being a library and becomes
//! *the interpreter*: scene stepping with the exact float-epsilon subdivision
//! both Stages use, the timeout graph with guarded branches, counter ops
//! through `rc_saturate`, event dispatch, and the emit token bucket through
//! `rc_refill_tokens`/`spend`. A language Stage that drives this holds no
//! state-machine logic of its own.
//!
//! Fixed capacity, zero allocation — and that is *faithful*, not a shortcut:
//! the figment grammar is statically bounded by construction (`MAX_SCENES`,
//! `MAX_BRANCHES`, `MAX_COUNTER_OPS` are the proof envelope `budgets.verify()`
//! enforces before anything is signed), so a bounded struct is exactly the
//! device model. Instances live in a small static pool (the glass runs ONE
//! figment at a time; the pool of 4 is for side-by-side tests). Single-
//! threaded use only, like the interpreter it replaces.
//!
//! Identifier policy: the core speaks integers. Bindings intern their strings —
//! scene ids and counter names become the indices `add_scene`/`add_counter`
//! return; event names become caller-chosen `u32` codes (the binding also owns
//! the "ble:<n> falls back to ble" lookup by trying both codes). This keeps
//! every signature ABI-clean on native and wasm alike.
//!
//! Deliberately NOT here yet (bindings keep them, ADR status is explicit):
//! battery_below dispatch, random-duration scenes (`duration_range`), the
//! text/slot events, and rendering/_resolve.

use crate::{rc_refill_tokens, rc_saturate, spend, CMP_EQ, CMP_GE, CMP_LE};

pub const MAX_SCENES: usize = 32; // grammar cap, budgets.verify() enforced
pub const MAX_BRANCHES: usize = 4; // timeout branches per scene
pub const MAX_EVENTS: usize = 16; // event handlers per scene (uncapped in the
                                  // grammar; 16 is far above any real figment)
pub const MAX_COUNTERS: usize = 8;
pub const MAX_OPS: usize = 4; // counter ops per transition
const EMIT_BURST: f64 = 5.0;
const EMIT_REFILL_PER_S: f64 = 1.0;

pub const TARGET_SELF: i32 = -1;
pub const TARGET_END: i32 = -2;

#[derive(Clone, Copy)]
struct CounterOp {
    counter: u8,
    op: u8, // OP_INC / OP_DEC / OP_SET
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
struct Scene {
    has_duration: bool,
    duration: f64,
    n_timeout: u8,
    timeout: [Transition; MAX_BRANCHES],
    n_events: u8,
    event_codes: [u32; MAX_EVENTS],
    events: [Transition; MAX_EVENTS],
}

const EMPTY_SCENE: Scene = Scene {
    has_duration: false,
    duration: 0.0,
    n_timeout: 0,
    timeout: [NO_TRANSITION; MAX_BRANCHES],
    n_events: 0,
    event_codes: [0; MAX_EVENTS],
    events: [NO_TRANSITION; MAX_EVENTS],
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
    tokens: f64,
    emits: u32,
    dropped: u32,
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
    tokens: 0.0, // armed to EMIT_BURST by rc_stage_start (zero-fill static)
    emits: 0,
    dropped: 0,
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

/// `has_duration=0` makes an untimed scene (duration ignored).
#[no_mangle]
pub extern "C" fn rc_stage_add_scene(h: i32, has_duration: i32, duration: f64) -> i32 {
    let Some(s) = stage(h) else { return -1 };
    if s.n_scenes as usize >= MAX_SCENES {
        return -1;
    }
    let i = s.n_scenes as usize;
    s.scenes[i] = EMPTY_SCENE;
    s.scenes[i].has_duration = has_duration != 0;
    s.scenes[i].duration = duration;
    s.n_scenes += 1;
    i as i32
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
    s.tokens = EMIT_BURST;
    s.emits = 0;
    s.dropped = 0;
    s.ended = false;
    s.started = true;
    enter(s, initial_scene);
    0
}

// ---------------------------------------------------------------------------
// The state machine (mirrors interpreter.py step/_advance_clock/_timeout/_take
// and figment.js step/_advance/_timeout/_take, line for line)
// ---------------------------------------------------------------------------

fn enter(s: &mut Stage, scene: i32) {
    s.current = scene;
    s.scene_elapsed = 0.0;
}

fn advance_clock(s: &mut Stage, dt: f64) {
    s.clock += dt;
    s.scene_elapsed += dt;
    s.tokens = rc_refill_tokens(s.tokens, dt, EMIT_REFILL_PER_S, EMIT_BURST);
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
        TARGET_END => s.ended = true,
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
    s.ended = true;
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
        let sc = s.scenes[s.current as usize];
        if !sc.has_duration {
            advance_clock(s, remaining_dt);
            break;
        }
        let left = sc.duration - s.scene_elapsed;
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
    let sc = s.scenes[s.current as usize];
    for i in 0..sc.n_events as usize {
        if sc.event_codes[i] == event_code {
            take(s, sc.events[i]);
            return 1;
        }
    }
    0
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

/// Seconds left in a timed scene, 0 for untimed (Stage.remaining()).
#[no_mangle]
pub extern "C" fn rc_stage_remaining(h: i32) -> f64 {
    let Some(s) = stage(h) else { return 0.0 };
    if !s.started {
        return 0.0;
    }
    let sc = s.scenes[s.current as usize];
    if !sc.has_duration {
        return 0.0;
    }
    let rem = sc.duration - s.scene_elapsed;
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

    /// The "3 rounds of 1 s work" figment, straight from the parity suites.
    fn rounds_stage() -> i32 {
        let h = rc_stage_new();
        let round = rc_stage_add_counter(h, 1, 1, 3);
        let work = rc_stage_add_scene(h, 1, 1.0);
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
        let a = rc_stage_add_scene(h, 0, 0.0); // untimed
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
        let a = rc_stage_add_scene(h, 0, 0.0);
        rc_stage_start(h, a);
        assert_eq!(rc_stage_inject(h, 999), 0);
        let hs: [i32; 3] = core::array::from_fn(|_| rc_stage_new());
        assert_eq!(rc_stage_new(), -1); // pool of 4 exhausted
        for x in hs {
            rc_stage_free(x);
        }
        rc_stage_free(h);
    }
}
