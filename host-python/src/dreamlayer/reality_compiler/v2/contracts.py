"""v2/contracts.py — the on-glass safety invariants as *proven* functions.

The interpreter and the budget prover enforce a handful of hard safety caps:
counters saturate to their bounds, the emit token bucket never floods BLE or
goes negative, and every display line and named-slot set is bounded. Those are
the claims the whole "data, not code" safety argument rests on — and until now
they were only *unit-tested*.

This module lifts each invariant into a small pure function carrying a PEP-316
contract (``pre:`` / ``post:`` in the docstring). CrossHair symbolically
executes each one (via Z3) and **proves the postcondition holds for all inputs**
— or hands back a concrete counterexample. The interpreter calls these exact
functions (interpreter.py imports them), so the proof guards the *real* code
path, not a copy. The contracts are inert at runtime (no import-time or per-call
cost); they are checked by tests/test_contracts_crosshair.py.
"""
from __future__ import annotations


def saturate(cur: int, op: str, amount: int, lo: int, hi: int) -> int:
    """Apply a counter op and clamp to [lo, hi]. The proof: a counter can never
    leave its declared bounds, whatever the op or amount.

    pre: lo <= hi
    pre: op in ('inc', 'dec', 'set')
    post: lo <= __return__ <= hi
    """
    if op == "inc":
        cur = cur + amount
    elif op == "dec":
        cur = cur - amount
    else:
        cur = amount
    return max(lo, min(hi, cur))


def refill_tokens(tokens: float, dt: float, refill_per_s: float,
                  burst: float) -> float:
    """Refill the emit token bucket over dt seconds. The proof: the bucket never
    exceeds its burst capacity and never *loses* tokens over time — the ceiling
    half of the "no BLE flood" guarantee.

    pre: 0.0 <= tokens <= burst
    pre: dt >= 0.0
    pre: refill_per_s >= 0.0
    pre: burst >= 0.0
    pre: dt <= 1000000.0
    pre: refill_per_s <= 1000000.0
    post: tokens <= __return__ <= burst
    """
    return min(burst, tokens + dt * refill_per_s)


def spend_token(tokens: float):
    """Try to spend one token for an emit. The proof: the bucket never goes
    negative — the floor half of the "no BLE flood" guarantee — so a forged
    figment that skipped verification still cannot emit below the rate limit.
    Returns (spent, tokens_after).

    pre: tokens >= 0.0
    post: __return__[1] >= 0.0
    post: __return__[1] <= tokens
    post: __return__[0] == (tokens >= 1.0)
    """
    if tokens >= 1.0:
        return (True, tokens - 1.0)
    return (False, tokens)


def clamp_text(s: str, max_len: int) -> str:
    """Clamp a resolved display line to `max_len` **UTF-8 bytes**, never
    splitting a codepoint. This is the one canonical text-length unit shared by
    all four interpreters (Python here, JS figment.js, Lua figment_stage.lua,
    Rust reality-core): the embedded core stores slot values in fixed
    ``[u8; MAX_TEXT]`` buffers, so bytes — not code points or UTF-16 units — is
    the only unit that fits that memory and lets a byte-clamp never overflow.
    Truncating on a codepoint boundary is what keeps the four byte-identical on
    non-ASCII input (a mid-sequence cut would make the Rust core emit invalid
    UTF-8 and the parity harness raise instead of diff).

    pre: max_len >= 0
    post: len(__return__.encode("utf-8")) <= max_len
    """
    b = s.encode("utf-8")
    if len(b) <= max_len:
        return s
    n = max_len
    # back off out of the middle of a multi-byte sequence: a UTF-8 continuation
    # byte is 0b10xxxxxx (0x80..0xBF); the first non-continuation byte at or
    # below max_len is the start of the codepoint we must not split.
    while n > 0 and (b[n] & 0xC0) == 0x80:
        n -= 1
    return b[:n].decode("utf-8")


def accept_slot(is_default: bool, is_known: bool, named_count: int,
                max_slots: int) -> bool:
    """Decide whether to accept a host text push into a slot. The proof:
    accepting a *genuinely new* named slot implies there was room, so the number
    of distinct named slots can never exceed max_slots.

    pre: named_count >= 0
    pre: max_slots >= 0
    post: (not __return__) or is_default or is_known or (named_count < max_slots)
    """
    return is_default or is_known or (named_count < max_slots)
