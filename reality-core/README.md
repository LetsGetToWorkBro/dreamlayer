# reality-core

A **proof of concept** for [ADR 0003](../docs/adr/0003-single-rust-core.md): the
on-glass Figment safety caps implemented once, in Rust, so Python / JS (wasm) /
Lua (mlua) can become *bindings* over one core instead of three hand-written
interpreters that drift.

Scope is deliberately the smallest safety-critical slice — the exact caps M1
proved with CrossHair and M4 mutation-hardened (`reality_compiler/v2/contracts.py`):

| C ABI symbol       | mirrors `contracts.` | guarantee |
|--------------------|----------------------|-----------|
| `rc_saturate`      | `saturate`           | a counter never leaves `[lo, hi]` |
| `rc_refill_tokens` | `refill_tokens`      | the emit bucket never exceeds burst |
| `rc_spend_token`   | `spend_token`        | …and never goes negative (no BLE flood) |
| `rc_clamp_len`     | `clamp_text` (length)| no display line overruns the budget |
| `rc_accept_slot`   | `accept_slot`        | named slots never exceed `MAX_SLOTS` |

…plus the first slice of the *control-flow* decision (ADR 0003's next step):

| C ABI symbol    | mirrors               | role |
|-----------------|-----------------------|------|
| `rc_guard_eval` | `interpreter._guard`  | does `counter <cmp> threshold` hold? — the guarded-timeout decision that ends a bounded loop |

Pure integer/float math: no allocation, no deps, `no_std`-ready as written.

## Build & test

```sh
cargo build --release      # produces target/release/libreality_core.{so,dylib}
cargo test                 # the Rust-side boundary unit tests
```

## Two targets, two proven parities

**Python (native cdylib).** Drives this compiled library against
`contracts.py` over a swept input space, bit-for-bit:

```sh
cd ../host-python && python -m pytest src/dreamlayer/tests/test_reality_core_parity.py
```

**JS (wasm).** The *same crate* compiled to `wasm32-unknown-unknown`, checked in
Node against figment.js — (A) bit-for-bit vs its transcribed cap expressions and
(B) against the real shipped figment.js `Stage`:

```sh
rustup target add wasm32-unknown-unknown
cargo build --release --target wasm32-unknown-unknown
node parity/wasm_parity.mjs        # or: pytest test_reality_core_wasm_parity.py
```

Both build on demand and skip cleanly where the toolchain is absent.

## One source, four targets

The same crate that loads from Python via `ctypes` and compiles to wasm for JS
(both proven above) also links via `mlua` for Lua and cross-compiles to
`thumbv7em-none-eabi` (`#![no_std]`) for the glasses. Two of the four targets
are now demonstrated end-to-end; the device targets are the ADR's remaining
staged work.

Not on the release path yet — see [ADR 0003](../docs/adr/0003-single-rust-core.md)
for the staged-migration plan and the explicit costs.
