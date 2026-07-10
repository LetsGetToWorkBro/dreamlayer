/* worker.figments.test.mjs — the figment-submission route (INNOVATION 5.2).
 * Runs the Worker's default export against a fake KV; exit 0 = pass.
 * `node worker.figments.test.mjs` (also driven by tests/test_lens_builder.py). */
import worker from "./worker.js";

const fails = [];
const ok = (c, m) => { if (!c) fails.push(m); };

function fakeEnv() {
  const store = new Map();
  return {
    SOCIAL: {
      get: async (k) => (store.has(k) ? store.get(k) : null),
      put: async (k, v) => { store.set(k, v); },
    },
    _store: store,
  };
}
const req = (method, path, body) => new Request("https://api.dreamlayer.app" + path, {
  method, headers: { "CF-Connecting-IP": "1.2.3.4", "Content-Type": "application/json" },
  body: body ? JSON.stringify(body) : undefined,
});

const goodListing = {
  kind: "figment-listing", v: 1, name: "Focus", author: "ada",
  description: "25/5 timer",
  figment: { id: "", name: "Focus", initial: "a", version: 2,
             scenes: { a: { id: "a", duration_sec: 10, lines: [{ content: "GO", row: 0, size: "md", color: "text_primary" }], on_timeout: [{ target: "@end" }] } } },
  proof: { ok: true, scenes: 1, cannot: [] },
};

const env = fakeEnv();

// a well-formed listing queues
let r = await worker.fetch(req("POST", "/api/figments/submit", goodListing), env);
let d = await r.json();
ok(r.status === 200 && d.status === "queued" && d.id, "good listing queues: " + JSON.stringify(d));

// GET reports the queue depth
r = await worker.fetch(req("GET", "/api/figments"), env);
d = await r.json();
ok(d.pending === 1, "queue depth reported");

// junk is rejected
r = await worker.fetch(req("POST", "/api/figments/submit", { kind: "nope" }), env);
ok(r.status === 400, "non-listing rejected");

// missing author is rejected
r = await worker.fetch(req("POST", "/api/figments/submit", { ...goodListing, author: "" }), env);
ok(r.status === 400, "missing author rejected");

// a scene-less figment is rejected
r = await worker.fetch(req("POST", "/api/figments/submit",
  { ...goodListing, figment: { ...goodListing.figment, scenes: {} } }), env);
ok(r.status === 400, "scene-less figment rejected");

if (fails.length) { console.error("FAIL\n" + fails.join("\n")); process.exit(1); }
console.log("ok — figment submit route: queue, depth, and rejections");
