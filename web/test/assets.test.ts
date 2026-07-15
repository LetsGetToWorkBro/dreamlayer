// assetUrl is the single-file-artifact (scripts/build-artifact.mjs) critical
// path: it decides whether a request resolves to an embedded data: URI or falls
// back to the network path. If it misroutes, every image/manifest in the
// standalone artifact silently breaks — yet it had no coverage. Runs on the
// Node built-in test runner (no deps): `npm test`.
import { test } from "node:test";
import assert from "node:assert/strict";

// Restore whatever window looked like, so tests don't leak into each other.
const savedWindow = (globalThis as { window?: unknown }).window;
function setWindow(w: unknown): void {
  (globalThis as { window?: unknown }).window = w;
}

// Import AFTER the window shim helpers exist; assetUrl reads window lazily.
const { assetUrl } = await import("../src/lib/assets.ts");

test("returns the embedded data: URI when the asset map has the path", () => {
  setWindow({ __ASSET_MAP: { "assets/og.jpg": "data:image/jpeg;base64,AAAA" } });
  assert.equal(assetUrl("assets/og.jpg"), "data:image/jpeg;base64,AAAA");
});

test("falls back to the network path when the map lacks the key", () => {
  setWindow({ __ASSET_MAP: { "assets/other.png": "data:x" } });
  assert.equal(assetUrl("assets/og.jpg"), "assets/og.jpg");
});

test("falls back to the path when there is no asset map (normal build)", () => {
  setWindow({});
  assert.equal(assetUrl("assets/scenes/juno/manifest.json"), "assets/scenes/juno/manifest.json");
});

test("does not throw when window itself is undefined-ish", () => {
  // assetUrl uses optional chaining: window?.__ASSET_MAP — an empty object is
  // the safe shape a pre-hydration call would see.
  setWindow({ __ASSET_MAP: undefined });
  assert.equal(assetUrl("x"), "x");
});

test("cleanup", () => {
  setWindow(savedWindow);
});
