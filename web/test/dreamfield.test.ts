// vnoise is the math core of the hero's living sky (initDreamField). The render
// loop is canvas/DOM-bound and hard to unit test, but the noise it rides on is
// pure — and if it loses determinism, its range bound, or its smooth
// interpolation, the whole field reads as dead or janky. These lock the three
// properties the animation depends on. Runs on the Node built-in test runner.
import { test } from "node:test";
import assert from "node:assert/strict";

const { vnoise } = await import("../src/lib/dreamfield.ts");

test("is deterministic (pure) — same input, same output", () => {
  for (const x of [0, 0.37, 5.1, 40.9, 123.456, -2.5]) {
    assert.equal(vnoise(x), vnoise(x));
  }
});

test("stays within the value-noise band [-1, 1)", () => {
  for (let x = -50; x <= 50; x += 0.13) {
    const v = vnoise(x);
    assert.ok(v >= -1 && v < 1, `vnoise(${x}) = ${v} escaped [-1, 1)`);
  }
});

test("interpolates smoothly: the lattice midpoint is the average of its ends", () => {
  // smoothstep weight u = f*f*(3-2f) is exactly 0.5 at f=0.5, so the value at
  // n+0.5 must equal the mean of the two integer lattice samples it bridges.
  for (const n of [0, 1, 7, 41, -3]) {
    const mid = vnoise(n + 0.5);
    const avg = (vnoise(n) + vnoise(n + 1)) / 2;
    assert.ok(Math.abs(mid - avg) < 1e-12, `midpoint ${mid} != avg ${avg} at n=${n}`);
  }
});

test("is continuous across an integer lattice boundary (no seam)", () => {
  // approaching an integer from just below should land near the integer sample
  const n = 12;
  const justBelow = vnoise(n - 1e-6);
  const atNode = vnoise(n);
  assert.ok(Math.abs(justBelow - atNode) < 1e-3, "value jumps at the lattice node");
});
