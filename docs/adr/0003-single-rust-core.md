# ADR 0003 — A single Rust core for the Figment interpreter, bindings for each language

**Status:** Proposed (PoC landed, not yet on the release path) · **Date:** 2026-07 · **Scope:** the Reality Compiler v2 interpreter/safety core across Python, JS, and on-glass Lua

## Context

A Figment is *data, not code* — a declarative scene-machine executed by a fixed,
reviewed stage. That safety story is only as strong as the guarantee that every
place a Figment runs executes **exactly** the same semantics. Today those places
are three hand-written interpreters:

- `host-python/…/reality_compiler/v2/interpreter.py` — the reference, and the
  engine behind playback/preview and the demo renderer.
- `phone-app/…/figment.js` — the phone/web preview twin.
- `halo-lua/app/figment_stage.lua` — the on-glass stage, the real thing, on an
  nRF52840-class MCU.

Every semantic change is written **three times**, and they drift. This is not
hypothetical:

- **N3 (differential testing)** exists precisely because they drift. It runs one
  generator through all three and hash-compares the frames — and it *caught a
  real bug*: a self-looping timed scene froze `{elapsed}` at `duration+overshoot`
  on the Lua stage but at exactly `duration` in Python (fixed in #261).
- **M1–M5** proved and mutation-hardened the safety caps — **but only in
  Python.** `contracts.py` is the proven core; `figment.js` and
  `figment_stage.lua` re-implement the same clamps by hand, unproven, trusted to
  match by tests we have to remember to write.

So the current architecture spends real, recurring effort (write-thrice) to buy
a guarantee (parity) that it then can only *approximate* (differential testing
finds drift after the fact; it cannot prevent it). The highest-stakes copy — the
device — is the one furthest from the proofs.

## Decision (proposed)

Implement the safety-critical interpreter core **once, in Rust**, and make each
language a thin **binding** over it:

- **Python** ← the Rust `cdylib` via `ctypes`/PyO3.
- **JS** ← the same crate compiled to `wasm32-unknown-unknown`.
- **Lua / device** ← the same crate linked via `mlua`, and cross-compiled to
  `thumbv7em-none-eabi` (`#![no_std]`) for the glasses.

Parity stops being something we test for and becomes something the build
**guarantees**: there is one implementation, so there is nothing to drift. N3
changes role from "catch drift between three interpreters" to "confirm the three
*bindings* are wired to the one core correctly" — a much smaller, structural
check. The M1 proofs and M4/M5 mutation gates then guard the *actual shipped*
caps on every target, not a Python reference the other two are supposed to
mirror.

Rust specifically (over C or a shared Lua blob) because the device path is the
highest-stakes, lowest-resource surface: Rust gives no-GC, no-UB, bounded-
allocation guarantees on bare metal that hand-written embedded Lua/C cannot, and
the safety caps are pure integer/float math that compiles to `no_std` with zero
dependencies.

## Evidence: a compiled, bit-parity PoC (this change)

This ADR ships with a working proof of concept — not a sketch — de-risking the
central claim:

- **`reality-core/`** — a Rust crate implementing the exact M1 safety caps
  (`rc_saturate`, `rc_refill_tokens`, `rc_spend_token`, `rc_clamp_len`,
  `rc_accept_slot`) behind a C ABI. Pure math, no deps, `no_std`-ready as
  written; builds as a `cdylib` today and cross-compiles to wasm/Cortex-M
  unchanged. Carries its own Rust unit tests (the boundary cases M4 pins).
- **`test_reality_core_parity.py`** — loads the **compiled** cdylib via `ctypes`
  and drives it against `contracts.py` over a swept input space, asserting the
  two agree **bit-for-bit** (ints exactly, floats to the last ULP), including a
  200-step token-bucket hot-path loop — the exact sequence the interpreter runs
  on every emit. Green: the Rust core *is* the Python reference, numerically.

That closes the risk that mattered: "can one core actually be identical to the
reference the proofs are written against?" Yes, demonstrably.

**Second target — wasm, checked against JS.** The same crate now also compiles
to `wasm32-unknown-unknown`, and `reality-core/parity/wasm_parity.mjs` loads that
wasm in Node and checks it two ways: (A) bit-for-bit against `figment.js`'s cap
expressions transcribed with line citations, and (B) against the **real shipped
`figment.js` Stage** driven through counter saturation and a token-bucket flood.
Green (4,852 swept checks + 2 real-Stage scenarios). This is the load-bearing
step: it proves "one source, many targets" across a language boundary that
actually ships — the same Rust source is simultaneously the Python reference
*and* the JS semantics, so the phone/web `figment.js` caps could become a binding
over this core rather than a hand-written copy. Two of the four targets
(Python cdylib, JS wasm) are now demonstrated end to end; the two device targets
(mlua, Cortex-M) are the remaining staged work.

**First step past the leaf caps — the control-flow decision.** Growing the core
toward a full scene *step* begins with the piece that governs a bounded loop's
termination: `rc_guard_eval` (does `counter <cmp> threshold` hold?), the exact
comparison `interpreter._guard` / `figment.js._guard` make. With it, a scene's
`_timeout` is "take the first branch that is unguarded or whose `rc_guard_eval`
is 1", and the counter update is the existing `rc_saturate`. Both parity
harnesses now run a **real "3 rounds then END" figment** through the *actual*
Python and JS Stages and match the counter trajectory and termination
**step-for-step** against the core's `guard_eval` + `saturate` — so the decision
that makes a bounded loop end (the thing the livelock/BLE-budget analysis and N3
care about) is now backed by the one Rust core, on both shipping targets, not
just leaf arithmetic. This is the first increment of the "timeout graph, guards"
work, done the same verified way as the caps.

**The first string across the ABI — the clock formatter.** `_resolve`'s string
templating splits into two very different pieces. The *value formatting* —
`_fmt_clock`, the formatter under `{remaining}`/`{elapsed}` — is now in the core
as `rc_fmt_clock`, using the canonical C string protocol (caller buffer + length
return, plus an in-module scratch buffer so the wasm binding has a safe write
target without an allocator). Both parity harnesses check it swept *and through
the real render path*: the Python Stage's `frame().lines` text and the JS
Stage's own `_resolve("{remaining}")` on a live countdown, stepped across the
minute boundary, equal the core's output byte-for-byte. So the buffer protocol
the whole string story depends on is proven on both targets.

**The state machine itself — the core becomes the interpreter.** The stateful
`Stage` now lives inside the core (`reality-core/src/stage.rs`): scene stepping
with the exact float-epsilon subdivision both Stages use, the timeout graph
with guarded branches, counter ops through `rc_saturate`, event dispatch, and
the emit token bucket — behind a builder ABI (`rc_stage_*`/`rc_tx_*`). Fixed
capacity, zero allocation, and that is *faithful*: the figment grammar is
statically bounded by construction (the `budgets.verify()` proof envelope), so
a bounded struct is exactly the device model. The core speaks integers only —
bindings intern their strings (scene ids/counter names → indices, event names →
codes), which is a legitimate binding-layer job and keeps the ABI clean on
native and wasm alike. Both parity harnesses now run **identical schedules on
the real Python/JS Stages and the core Stage side-by-side** — ragged fractional
steps across timeout boundaries, guarded bounded loops to termination, tap
floods with refills between — comparing every observable (clock, elapsed,
ended, counters, emits, drops, tokens) **bit-for-bit at every step**, including
the shipped `native` timer and interval figments on the Python side. A language
Stage that drives this holds no state-machine logic of its own.

**The text path — slots, templates, rendering.** The remaining string-heavy
half of `_resolve` is now in the core: the slot store (default + up to
`MAX_SLOTS` named values, accepted by exactly the `accept_slot` rule, clamped
to `MAX_TEXT_LEN`), line templates loaded **pre-tokenized** by the binding
(`rc_line_lit`/`rc_line_tok` — the parse the interpreters redo per frame
happens once at load), and `rc_stage_render_line`, which composes
literals + `{remaining}`/`{elapsed}`/`{slot:x}`/`{count:n}` from the core's own
state and clamps like the interpreter does. One deliberate, documented
improvement over the chained-replace interpreters: slot *values* are inert
data — a pushed value containing `{count:n}` renders literally instead of
being re-substituted, so host text can never smuggle tokens into the display
(in-grammar content, which is all the N3 generator emits, behaves
identically). Inbound strings ride the same scratch-buffer protocol as
outbound on wasm.

**The periphery.** `battery_below` dispatch (level-below-threshold with the
60 s cooldown, mid-`_advance_clock`, exactly as the reference) and
random-duration scenes (`duration_range`) are in the core too. Randomness is a
seedable splitmix64 → 53-bit-uniform stream (`rc_stage_seed`); the reference
Stage accepts any `rng` object, so a binding that mirrors the stream gets
**bit-identical trajectories** — the Python parity suite does exactly that.

**Code-reachable migration: complete.** Every part of the interpreter that can
be proven from this repo now lives in the core and is parity-locked on both
shipping targets — the Python suite compares full state *and rendered frames*
per step (including the shipped Rosetta and timer figments; render parity runs
frame-for-frame against `Stage.frame()`), the wasm harness does the same
against the real `figment.js` including its own `_resolve`. What stays
binding-side is presentation policy, by design: frame assembly (the empty
ended-frame, pulse phase, cadence envelope, rows/sizes/colors) and string
interning. What remains for the ADR is the device work: the `mlua` binding,
the `thumbv7em-none-eabi` build, and firmware integration.

## Options considered

1. **Status quo — three interpreters + N3 differential testing.** Cheap to keep,
   zero migration risk. But it institutionalizes write-thrice and detects drift
   only after it ships to one target; the device caps stay unproven. This is the
   baseline the ADR argues to move off of.
2. **Single Rust core + per-language bindings (this proposal).** Highest upside
   (parity by construction, proofs guard the real device path, one place to
   change). Highest cost: a Rust toolchain in CI, a wasm build for the phone, an
   `mlua`/embedded integration and Cortex-M cross-compile, and a staged
   migration of the full interpreter surface (not just the caps) with N3 held
   green at every step.
3. **Port the core to C instead of Rust.** Smaller toolchain, trivially embedded.
   Rejected: loses exactly the memory-safety guarantees that make a single
   *device* core worth doing, and C has no equivalent to the `cdylib`/wasm/
   `no_std` triple-target story from one source.
4. **Generate the three interpreters from one spec (codegen).** Keeps native
   code per target. Rejected: a code generator is itself a fourth thing that can
   drift from the runtime, and it does not give the device the safety properties.

## Consequences

**If accepted:**
- CI gains a Rust job (build + `cargo test` + the parity test) and a wasm build
  step for the phone bundle. The parity test moves from skip-by-default to
  enforced once the toolchain is standard in CI.
- The migration is **staged and interpreter-surface-wide**, not just the caps:
  scene stepping, the timeout graph, slot resolution, rendering primitives.
  Each stage lands behind the binding with N3 kept green, so the three languages
  can be retired to bindings one subsystem at a time — never a big-bang rewrite.
- The proofs (M1) and mutation gates (M4/M5) get pointed at the Rust core, so
  the guarantee finally covers the shipped device code.

**Costs / risks (explicit):**
- Real toolchain surface: Rust in CI, wasm-pack for JS, `mlua` + a
  `thumbv7em-none-eabi` cross-compile and the Brilliant Labs firmware
  integration (the last is owner/hardware work, out of this repo's reach).
- Float determinism across targets must be verified, not assumed — wasm and
  Cortex-M FPU behavior vs host x86. The parity harness is the mechanism; it
  must run per-target, not just host-vs-host.
- Until the migration completes, the Rust core and the three interpreters
  coexist; that is *more* surface, not less, during the transition.

## Non-goals (for this ADR / PoC)

- Migrating the full interpreter. This PoC is the safety caps only — enough to
  prove the seam, not to replace `interpreter.py`/`figment.js`/`figment_stage.lua`.
- The device firmware integration and the Cortex-M build (owner/hardware work).
- Flipping the parity test to enforced-in-CI (needs Rust standard in the CI image
  first). It runs on demand and skips cleanly where cargo is absent.

## Recommendation

Adopt the direction, funded as a **staged migration** behind the binding seam,
starting from this proven core. Do **not** treat it as a big-bang rewrite. The
first validation — a second binding target (wasm, checked against the shipped
`figment.js`) — is **done** (above): "one source, many targets" holds across a
real language boundary. The next concrete steps, in order of decreasing
certainty and increasing cost:

1. **Grow the core past the caps** to a full scene *step*. **Done** — the
   stateful `Stage` (stepping, timeout graph, guards, counter ops, event
   dispatch, token bucket), the text path (slot store, tokenized templates,
   line rendering), and the periphery (battery dispatch, seeded
   `duration_range`) are all in the core, trajectory- and frame-proven
   bit-for-bit against both real Stages on real figments. A semantic change to
   the interpreter now has ONE home; the language Stages are reducible to
   bindings (interning, transport, presentation).
2. **The Lua/device binding** (`mlua` + a `thumbv7em-none-eabi` build), which is
   where the memory-safety payoff lives but also the firmware-integration cost
   (owner/hardware work).
3. **Per-target float determinism** re-checked on the wasm and Cortex-M FPUs, not
   assumed from host-vs-host.

Only after (1) is comfortable should the interpreter-wide migration be
committed to.
