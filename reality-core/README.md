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

Pure integer/float math: no allocation, no deps, `no_std`-ready as written.

## Build & test

```sh
cargo build --release      # produces target/release/libreality_core.{so,dylib}
cargo test                 # the Rust-side boundary unit tests
```

The **cross-language parity proof** lives on the Python side and drives this
compiled library against the reference over a swept input space, asserting
bit-for-bit agreement:

```sh
cd ../host-python && python -m pytest src/dreamlayer/tests/test_reality_core_parity.py
```

It builds the crate on demand and skips cleanly where `cargo` is absent.

## Why a cdylib

The same crate that loads from Python via `ctypes` today compiles to
`wasm32-unknown-unknown` for JS and links via `mlua` for Lua, and cross-compiles
to `thumbv7em-none-eabi` (`#![no_std]`) for the glasses — **one source, four
targets.** This PoC exercises the Python target; the next step (per the ADR) is
the wasm target with a JS-vs-core parity check.

Not on the release path yet — see the ADR for the staged-migration plan and the
explicit costs.
