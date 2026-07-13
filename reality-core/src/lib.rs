//! reality-core — the on-glass Figment safety caps, in one place.
//!
//! Today DreamLayer ships THREE hand-written interpreters that must stay
//! bit-identical: the Python reference (`reality_compiler/v2/interpreter.py`),
//! the JS preview (`figment.js`), and the on-glass Lua stage
//! (`halo-lua/app/figment_stage.lua`). Every semantic change is written three
//! times, and they drift — differential testing (N3) exists precisely because
//! they do, and it has caught real parity bugs.
//!
//! This crate is a proof of concept for the fix: implement the safety-critical
//! core ONCE in Rust and let each language be a thin *binding* over it. Parity
//! stops being something we test for and becomes something the architecture
//! guarantees. The functions here are exactly the caps M1 proved with CrossHair
//! and M4 hardened with mutmut (`reality_compiler/v2/contracts.py`); the Python
//! parity test drives this compiled core against that reference and asserts they
//! agree bit-for-bit across a swept input space.
//!
//! Everything is `#[no_mangle] extern "C"`, so a cdylib loads from Python via
//! ctypes today, the same source compiles to `wasm32-unknown-unknown` for JS,
//! and links via `mlua` for the device — one implementation, three targets.
//! The logic is pure integer/float math: no allocation, no panics, no deps —
//! so it is `no_std`-ready as written (no `std` type appears below). The host
//! PoC builds with `std` because a host `cdylib` links against it; the device
//! build flips on `#![no_std]` + a panic handler and cross-compiles to
//! `thumbv7em-none-eabi` unchanged. Kept as std here so the crate builds and
//! the parity harness runs in this environment.

mod stage;
pub use stage::*;

/// Counter op codes (the string op is encoded to an int across the C ABI).
pub const OP_INC: u8 = 0;
pub const OP_DEC: u8 = 1;
pub const OP_SET: u8 = 2;

/// Apply a counter op and clamp to `[lo, hi]`. A counter can never leave its
/// declared bounds, whatever the op or amount. Mirrors `contracts.saturate`.
#[no_mangle]
pub extern "C" fn rc_saturate(cur: i64, op: u8, amount: i64, lo: i64, hi: i64) -> i64 {
    let next = match op {
        OP_INC => cur.saturating_add(amount),
        OP_DEC => cur.saturating_sub(amount),
        _ => amount, // OP_SET (and, defensively, any unknown op)
    };
    // clamp to [lo, hi]; assumes lo <= hi (the caller's precondition)
    if next < lo {
        lo
    } else if next > hi {
        hi
    } else {
        next
    }
}

/// Guard comparators (the string cmp is encoded to an int across the C ABI).
pub const CMP_GE: u8 = 0;
pub const CMP_LE: u8 = 1;
pub const CMP_EQ: u8 = 2;

/// Evaluate a transition guard: does `counter_value <cmp> threshold` hold?
/// This is the decision at the heart of every guarded timeout branch — the one
/// that decides whether a bounded loop takes another lap or ends. It is the
/// first step of the interpreter's *control flow* moving into the core (ADR
/// 0003): a scene's `_timeout` becomes "take the first branch that is unguarded
/// or whose `rc_guard_eval` is 1". Mirrors `interpreter._guard` /
/// `figment.js` `_guard` exactly (ge → `>=`, le → `<=`, eq → `==`; an absent
/// counter reads as 0, which the caller passes as `counter_value`).
#[no_mangle]
pub extern "C" fn rc_guard_eval(counter_value: i64, cmp: u8, threshold: i64) -> i32 {
    let pass = match cmp {
        CMP_GE => counter_value >= threshold,
        CMP_LE => counter_value <= threshold,
        _ => counter_value == threshold, // CMP_EQ (and, defensively, unknown)
    };
    pass as i32
}

/// Refill the emit token bucket over `dt` seconds. Never exceeds `burst`, never
/// loses tokens over time — the ceiling of the "no BLE flood" guarantee.
/// Mirrors `contracts.refill_tokens`.
#[no_mangle]
pub extern "C" fn rc_refill_tokens(tokens: f64, dt: f64, refill_per_s: f64, burst: f64) -> f64 {
    let filled = tokens + dt * refill_per_s;
    if filled < burst {
        filled
    } else {
        burst
    }
}

/// The one definition of a token spend, shared by every export below so the
/// pointer form and the pure wasm-friendly forms can never disagree.
#[inline]
pub(crate) fn spend(tokens: f64) -> (i32, f64) {
    if tokens >= 1.0 {
        (1, tokens - 1.0)
    } else {
        (0, tokens)
    }
}

/// Try to spend one token for an emit. The bucket never goes negative — the
/// floor of the "no BLE flood" guarantee. Writes the post-spend balance to
/// `out_tokens` and returns 1 if a token was spent, else 0. Mirrors
/// `contracts.spend_token`. (Pointer form, for the Python cdylib.)
///
/// # Safety
/// `out_tokens` must be a valid, non-null pointer to a writable `f64`.
#[no_mangle]
pub extern "C" fn rc_spend_token(tokens: f64, out_tokens: *mut f64) -> i32 {
    let (spent, after) = spend(tokens);
    if !out_tokens.is_null() {
        unsafe { *out_tokens = after };
    }
    spent
}

/// Whether a token can be spent (1/0). Pure, pointer-free — the form the wasm
/// binding calls, since wasm has no natural out-parameter. Composes with
/// `rc_spend_after` to the same result as `rc_spend_token`.
#[no_mangle]
pub extern "C" fn rc_spend_ok(tokens: f64) -> i32 {
    spend(tokens).0
}

/// The token balance after a spend attempt. Pure, pointer-free companion to
/// `rc_spend_ok`.
#[no_mangle]
pub extern "C" fn rc_spend_after(tokens: f64) -> f64 {
    spend(tokens).1
}

/// Clamp a resolved display line to `max_len` *bytes*. Returns the clamped byte
/// length (the caller already holds the buffer; the cap is on the length). No
/// line ever exceeds the display's character budget. Mirrors
/// `contracts.clamp_text` at the length level — exact for ASCII HUD text. The
/// non-ASCII, codepoint-boundary-aware clamp is `rc_clamp_text_len`, which needs
/// the bytes; this length-only form is the fast path when the caller knows the
/// text is ASCII (one byte per code point, so no sequence can be split).
#[no_mangle]
pub extern "C" fn rc_clamp_len(len: u64, max_len: u64) -> u64 {
    if len < max_len {
        len
    } else {
        max_len
    }
}

/// How many leading bytes of `s` to keep so the result is `<= max` bytes and
/// never splits a UTF-8 codepoint. This is the one canonical text-length rule
/// shared by all four interpreters — Python `contracts.clamp_text`, JS
/// `figment.js`, Lua `figment_stage.lua`, and this core: the unit is UTF-8
/// bytes, truncated on a codepoint boundary. Backs out of any trailing
/// continuation byte (`0b10xx_xxxx`, `0x80..=0xBF`) so a multi-byte sequence is
/// kept whole or dropped whole — never half-emitted (which would make this core
/// produce invalid UTF-8 and the parity harness raise instead of diff).
pub(crate) fn clamp_utf8_boundary(s: &[u8], max: usize) -> usize {
    if s.len() <= max {
        return s.len();
    }
    let mut n = max;
    while n > 0 && (s[n] & 0xC0) == 0x80 {
        n -= 1;
    }
    n
}

/// Codepoint-safe byte clamp over an actual UTF-8 payload: how many leading
/// bytes fit in `max_len` without splitting a codepoint. This is the non-ASCII
/// companion to `rc_clamp_len` and the one the non-ASCII parity sweep drives.
///
/// # Safety
/// `ptr` must be valid for reads of `len` bytes.
#[no_mangle]
pub unsafe extern "C" fn rc_clamp_text_len(ptr: *const u8, len: u64, max_len: u64) -> u64 {
    if ptr.is_null() {
        return 0;
    }
    let s = core::slice::from_raw_parts(ptr, len as usize);
    clamp_utf8_boundary(s, max_len as usize) as u64
}

/// Decide whether to accept a host text push into a slot. Accepting a genuinely
/// new named slot implies there was room, so the number of distinct named slots
/// can never exceed `max_slots`. Booleans are passed as 0/1 across the ABI.
/// Mirrors `contracts.accept_slot`.
#[no_mangle]
pub extern "C" fn rc_accept_slot(
    is_default: i32,
    is_known: i32,
    named_count: i64,
    max_slots: i64,
) -> i32 {
    let accept = is_default != 0 || is_known != 0 || named_count < max_slots;
    accept as i32
}

// ---------------------------------------------------------------------------
// The first STRING across the ABI: the clock formatter under {remaining} and
// {elapsed}. String output uses the canonical C protocol — the caller passes a
// buffer, we write ASCII into it and return the length — which works unchanged
// over ctypes (native) and wasm linear memory. No allocation: the digits are
// composed in a stack array. (Trivia: this is the formatter whose "2:48"
// output once became a colon filename that broke Windows clones — see #210.)
// ---------------------------------------------------------------------------

/// Write the decimal digits of `n` into `buf`; returns how many were written.
#[inline]
fn write_dec(mut n: u64, buf: &mut [u8]) -> usize {
    let mut tmp = [0u8; 20];
    let mut i = 0;
    loop {
        tmp[i] = b'0' + (n % 10) as u8;
        i += 1;
        n /= 10;
        if n == 0 {
            break;
        }
    }
    for k in 0..i {
        buf[k] = tmp[i - 1 - k]; // digits were composed least-significant first
    }
    i
}

/// Format a clock the way both interpreters do: `secs = max(0, ceil(secs))`;
/// under a minute a plain seconds string ("48"), otherwise minutes:seconds
/// with zero-padded seconds ("2:48"; minutes are unpadded and never wrap to
/// hours). Mirrors `interpreter._fmt_clock` and `figment.js` `_fmtClock`.
///
/// Writes ASCII into `out` (up to `cap` bytes) and returns the number written
/// (the full formatted value is at most 23 bytes). A NaN reads as 0 — clock
/// inputs are non-negative by construction; this is defensive only.
///
/// # Safety
/// `out` must be valid for writes of `cap` bytes (or null, to just measure).
#[no_mangle]
pub extern "C" fn rc_fmt_clock(secs: f64, out: *mut u8, cap: u64) -> u64 {
    let s = if secs.is_nan() || secs <= 0.0 {
        0u64
    } else {
        secs.ceil() as u64
    };
    let mut tmp = [0u8; 24];
    let mut len = 0usize;
    if s >= 60 {
        len += write_dec(s / 60, &mut tmp[len..]);
        tmp[len] = b':';
        len += 1;
        let ss = s % 60;
        tmp[len] = b'0' + (ss / 10) as u8;
        len += 1;
        tmp[len] = b'0' + (ss % 10) as u8;
        len += 1;
    } else {
        len += write_dec(s, &mut tmp[len..]);
    }
    let n = core::cmp::min(len as u64, cap);
    if !out.is_null() {
        unsafe { core::ptr::copy_nonoverlapping(tmp.as_ptr(), out, n as usize) };
    }
    n
}

/// A small scratch buffer inside the module, so the wasm binding has a safe
/// place for string output without an allocator: call `rc_scratch_ptr()`,
/// pass it as `out` with `rc_scratch_len()` as `cap`, then read the returned
/// number of bytes back out of linear memory. Single-threaded use only (the
/// interpreter is), which is why the plain static is acceptable here.
const SCRATCH_LEN: usize = 64;
static mut SCRATCH: [u8; SCRATCH_LEN] = [0; SCRATCH_LEN];

#[no_mangle]
pub extern "C" fn rc_scratch_ptr() -> *mut u8 {
    core::ptr::addr_of_mut!(SCRATCH) as *mut u8
}

#[no_mangle]
pub extern "C" fn rc_scratch_len() -> u64 {
    SCRATCH_LEN as u64
}

// ---------------------------------------------------------------------------
// Rust-side unit tests: the same boundary cases the Python suite pins, so the
// core is self-checking even before the cross-language parity harness runs.
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn saturate_clamps_and_dispatches() {
        assert_eq!(rc_saturate(0, OP_INC, 5, 0, 10), 5);
        assert_eq!(rc_saturate(8, OP_INC, 5, 0, 10), 10); // clamp hi
        assert_eq!(rc_saturate(1, OP_DEC, 5, 0, 10), 0); // clamp lo
        assert_eq!(rc_saturate(9, OP_SET, 4, 0, 10), 4); // set
        // the three ops are distinct on the same inputs
        assert_eq!(rc_saturate(5, OP_INC, 3, 0, 100), 8);
        assert_eq!(rc_saturate(5, OP_DEC, 3, 0, 100), 2);
        assert_eq!(rc_saturate(5, OP_SET, 3, 0, 100), 3);
    }

    #[test]
    fn guard_eval_matches_the_three_comparators() {
        // ge
        assert_eq!(rc_guard_eval(3, CMP_GE, 3), 1);
        assert_eq!(rc_guard_eval(4, CMP_GE, 3), 1);
        assert_eq!(rc_guard_eval(2, CMP_GE, 3), 0);
        // le
        assert_eq!(rc_guard_eval(3, CMP_LE, 3), 1);
        assert_eq!(rc_guard_eval(2, CMP_LE, 3), 1);
        assert_eq!(rc_guard_eval(4, CMP_LE, 3), 0);
        // eq
        assert_eq!(rc_guard_eval(3, CMP_EQ, 3), 1);
        assert_eq!(rc_guard_eval(2, CMP_EQ, 3), 0);
    }

    #[test]
    fn bounded_loop_terminates_via_guard_and_saturate() {
        // the "3 rounds then END" loop expressed with only the core primitives:
        // each lap, if round >= 3 stop, else inc (saturating at hi=3)
        let (lo, hi) = (1, 3);
        let mut round = 1;
        let mut laps = 0;
        loop {
            if rc_guard_eval(round, CMP_GE, 3) == 1 {
                break;
            }
            round = rc_saturate(round, OP_INC, 1, lo, hi);
            laps += 1;
        }
        assert_eq!(round, 3);
        assert_eq!(laps, 2); // 1 -> 2 -> 3, then the guard fires
    }

    #[test]
    fn refill_caps_at_burst_and_never_loses() {
        assert_eq!(rc_refill_tokens(0.0, 1.0, 1.0, 5.0), 1.0);
        assert_eq!(rc_refill_tokens(4.0, 10.0, 10.0, 5.0), 5.0); // capped
        assert_eq!(rc_refill_tokens(2.0, 0.0, 5.0, 5.0), 2.0); // dt=0 no-op
        assert!(rc_refill_tokens(3.0, 0.5, 1.0, 5.0) >= 3.0);
    }

    #[test]
    fn spend_never_goes_negative() {
        let mut out = 0.0;
        assert_eq!(rc_spend_token(1.0, &mut out), 1);
        assert_eq!(out, 0.0);
        assert_eq!(rc_spend_token(0.999, &mut out), 0);
        assert_eq!(out, 0.999);
        assert_eq!(rc_spend_token(0.0, &mut out), 0);
        assert_eq!(out, 0.0);
        assert_eq!(rc_spend_token(2.5, &mut out), 1);
        assert_eq!(out, 1.5);
    }

    #[test]
    fn pure_spend_wrappers_match_the_pointer_form() {
        let mut out = 0.0;
        for &t in &[0.0, 0.5, 0.999, 1.0, 1.0001, 2.5, 5.0] {
            let ptr_spent = rc_spend_token(t, &mut out);
            assert_eq!(rc_spend_ok(t), ptr_spent);
            assert_eq!(rc_spend_after(t), out);
        }
    }

    #[test]
    fn fmt_clock_matches_both_interpreters() {
        fn fmt(secs: f64) -> String {
            let mut buf = [0u8; 24];
            let n = rc_fmt_clock(secs, buf.as_mut_ptr(), 24) as usize;
            core::str::from_utf8(&buf[..n]).unwrap().to_string()
        }
        assert_eq!(fmt(0.0), "0");
        assert_eq!(fmt(0.1), "1"); // ceil
        assert_eq!(fmt(48.0), "48");
        assert_eq!(fmt(59.0), "59");
        assert_eq!(fmt(59.2), "1:00"); // ceil crosses the minute
        assert_eq!(fmt(60.0), "1:00");
        assert_eq!(fmt(61.0), "1:01");
        assert_eq!(fmt(90.0), "1:30");
        assert_eq!(fmt(168.0), "2:48"); // the #210 filename, alive and well
        assert_eq!(fmt(3599.0), "59:59");
        assert_eq!(fmt(3600.0), "60:00"); // minutes never wrap to hours
        assert_eq!(fmt(-5.0), "0"); // clamped at zero
    }

    #[test]
    fn fmt_clock_respects_the_cap_and_scratch_fits() {
        let mut buf = [0u8; 2];
        assert_eq!(rc_fmt_clock(168.0, buf.as_mut_ptr(), 2), 2); // truncated
        assert_eq!(&buf, b"2:");
        assert_eq!(rc_fmt_clock(168.0, core::ptr::null_mut(), 0), 0); // measure-only
        assert!(rc_scratch_len() >= 24);
    }

    #[test]
    fn clamp_len_bounds() {
        assert_eq!(rc_clamp_len(6, 3), 3);
        assert_eq!(rc_clamp_len(2, 10), 2);
        assert_eq!(rc_clamp_len(3, 3), 3);
    }

    #[test]
    fn accept_slot_truth_table() {
        assert_eq!(rc_accept_slot(1, 0, 99, 4), 1); // default always
        assert_eq!(rc_accept_slot(0, 1, 99, 4), 1); // known always
        assert_eq!(rc_accept_slot(0, 0, 3, 4), 1); // room
        assert_eq!(rc_accept_slot(0, 0, 4, 4), 0); // full
    }
}
