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
| `rc_fmt_clock`  | `_fmt_clock` / `_fmtClock` | the `{remaining}`/`{elapsed}` clock string ("48", "2:48") — the first string across the ABI (caller buffer + `rc_scratch_ptr`/`rc_scratch_len` for wasm) |

…and, the big one, **the interpreter itself** (`src/stage.rs`): a stateful
`Stage` behind a builder ABI (`rc_stage_new/add_counter/add_scene`,
`rc_tx_begin/guard/op/emit/commit_*`, line templates via
`rc_stage_add_line`/`rc_line_lit`/`rc_line_tok`, then
`start/step/inject/text/render_line` + state readers). Scene stepping with the
exact float-epsilon subdivision, the guarded timeout graph, counter ops, event
dispatch, the emit token bucket, the slot store, per-frame line rendering,
battery-low dispatch with its 60 s cooldown, and seeded random-duration scenes
(splitmix64) — fixed capacity (the grammar's own proof envelope), zero
allocation, a static pool of 4 (the glass runs one figment at a time).
Bindings intern strings to indices/codes and keep presentation policy (frame
assembly, pulse phase, cadence, rows/colors); the ABI speaks integers plus the
scratch-buffer string protocol. Slot values are inert data by construction —
pushed text can't smuggle `{tokens}` back into a template.

No allocation, no deps, `no_std`-ready as written (strings compose in a stack
array and copy into a caller/scratch buffer). Both parity harnesses run
identical schedules on the real Python/JS Stages and the core Stage
side-by-side, comparing every observable bit-for-bit at every step.

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
