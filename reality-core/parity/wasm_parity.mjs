// wasm_parity.mjs — the JS half of ADR 0003's "one source, many targets" proof.
//
// Loads the reality-core crate COMPILED TO WASM and checks it two ways:
//   (A) bit-for-bit against a JS reference transcribed from figment.js's exact
//       cap expressions (cited by line) — the "wasm == the JS semantics" proof;
//   (B) against the REAL shipped figment.js Stage driven through counter
//       saturation and a token-bucket flood — proving the binding reproduces
//       the actual hand-written JS cap code it would replace.
//
// Exits non-zero on any mismatch. Invoked by test_reality_core_wasm_parity.py
// and .github/workflows/rust-core.yml.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { createRequire } from "node:module";

const __dirname = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

// ---- load the wasm core -----------------------------------------------------
const wasmPath = resolve(
  __dirname, "../target/wasm32-unknown-unknown/release/reality_core.wasm");
const { instance } = await WebAssembly.instantiate(readFileSync(wasmPath), {});
const rc = instance.exports;

// ---- the JS reference: figment.js's caps, transcribed with citations --------
// These mirror landing/assets/lens/figment.js EXACTLY; the line refs are the
// contract. If figment.js changes a cap, this reference must change with it —
// and (B) below drives the real Stage so a drift is caught either way.
const B = { MAX_SLOTS: 8 };
const EMIT_BURST = 5, EMIT_REFILL_PER_S = 1.0;               // figment.js:886
const ref = {
  saturate: (cur, op, amount, lo, hi) => {                   // figment.js:960-963
    if (op === "inc") cur += amount; else if (op === "dec") cur -= amount; else cur = amount;
    return Math.max(lo, Math.min(hi, cur));
  },
  refill: (tokens, dt) =>                                    // figment.js:923
    Math.min(EMIT_BURST, tokens + dt * EMIT_REFILL_PER_S),
  spendOk: (tokens) => tokens >= 1.0,                        // figment.js:966
  spendAfter: (tokens) => (tokens >= 1.0 ? tokens - 1.0 : tokens),
  clampLen: (len, max) => Math.min(len, max),                // figment.js:989 (.slice)
  acceptSlot: (isDefault, isKnown, named, max) =>            // figment.js:931
    isDefault || isKnown || named < max,
};

const OP = { inc: 0, dec: 1, set: 2 };
let checks = 0;
function eq(a, b, msg) {
  checks++;
  if (!Object.is(a, b)) { throw new Error(`MISMATCH ${msg}: wasm=${a} ref=${b}`); }
}

// ---- (A) swept bit-for-bit parity, wasm vs the transcribed JS reference ------
for (const [lo, hi] of [[0, 10], [-5, 5], [0, 3], [1, 3], [-100, 100]]) {
  for (const op of ["inc", "dec", "set"]) {
    for (let cur = lo - 2; cur <= hi + 2; cur++) {
      for (const amount of [0, 1, 2, 5, 100, -3]) {
        eq(Number(rc.rc_saturate(BigInt(cur), OP[op], BigInt(amount), BigInt(lo), BigInt(hi))),
           ref.saturate(cur, op, amount, lo, hi), `saturate(${cur},${op},${amount},${lo},${hi})`);
      }
    }
  }
}
for (const tokens of [0, 0.5, 1, 3, 5]) {
  for (const dt of [0, 0.1, 0.5, 1, 3.3, 1000]) {
    // the JS reference fixes refill/burst at figment.js's constants
    eq(rc.rc_refill_tokens(tokens, dt, EMIT_REFILL_PER_S, EMIT_BURST),
       ref.refill(tokens, dt), `refill(${tokens},${dt})`);
  }
}
for (const tokens of [0, 0.5, 0.999, 1, 1.0001, 2.5, 5]) {
  eq(rc.rc_spend_ok(tokens), ref.spendOk(tokens) ? 1 : 0, `spend_ok(${tokens})`);
  eq(rc.rc_spend_after(tokens), ref.spendAfter(tokens), `spend_after(${tokens})`);
}
for (let len = 0; len < 40; len++) {
  for (const max of [0, 1, 24, 39]) {
    eq(Number(rc.rc_clamp_len(BigInt(len), BigInt(max))), ref.clampLen(len, max), `clamp(${len},${max})`);
  }
}
for (const d of [0, 1]) for (const k of [0, 1]) for (let named = 0; named < 12; named++) for (const mx of [0, 1, 8]) {
  eq(rc.rc_accept_slot(d, k, BigInt(named), BigInt(mx)), (ref.acceptSlot(!!d, !!k, named, mx) ? 1 : 0),
     `accept(${d},${k},${named},${mx})`);
}

// ---- (B) the REAL figment.js Stage vs the wasm core -------------------------
const F = require("../../landing/assets/lens/figment.js");
const { END, SELF } = F;                       // "@end" / "@self" — the module's own sentinels

// counter saturation: 10 increments on a [0,3] counter must cap at 3 on the
// real Stage; the wasm core folded over the same 10 incs must agree.
(function counterSaturationParity() {
  const fig = {
    name: "sat", initial: "a",
    counters: { n: { start: 0, lo: 0, hi: 3 } },
    scenes: { a: { id: "a", lines: [], on: { single: { target: SELF, counter_ops: [{ counter: "n", op: "inc", amount: 1 }] } } } },
  };
  const st = new F.Stage(fig);
  let wasm = 0n;
  for (let i = 0; i < 10; i++) { st.inject("single"); wasm = rc.rc_saturate(wasm, OP.inc, 1n, 0n, 3n); }
  eq(Number(wasm), st.counters.n, "real-Stage counter saturation");
  eq(st.counters.n, 3, "real-Stage counter capped at hi");
})();

// token-bucket flood: many emits in ~zero time — the real Stage caps emits at
// EMIT_BURST and drops the rest; the wasm spend/refill loop must emit the same.
(function tokenBucketFloodParity() {
  const fig = {
    name: "flood", initial: "a",
    counters: {},
    scenes: { a: { id: "a", lines: [], on: { single: { target: SELF, emit: "tap" } } } },
  };
  const st = new F.Stage(fig);
  let tokens = EMIT_BURST, wasmEmits = 0;
  for (let i = 0; i < 20; i++) {
    st.inject("single");                       // real Stage: spend or drop
    if (rc.rc_spend_ok(tokens)) { wasmEmits++; tokens = rc.rc_spend_after(tokens); }  // no time passes → no refill
  }
  eq(st.emits.length, wasmEmits, "real-Stage flood emit count");
  eq(st.emits.length, EMIT_BURST, "real-Stage flood capped at burst");
})();

console.log(`OK — wasm/JS parity: ${checks} swept checks + 2 real-Stage scenarios agree`);
