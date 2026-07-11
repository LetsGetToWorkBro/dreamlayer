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

// -- gallery + approve ------------------------------------------------------
// approve is gated: no ADMIN_TOKEN configured -> forbidden
r = await worker.fetch(req("POST", "/api/figments/fig_x/approve"), env);
ok(r.status === 403, "approve forbidden without ADMIN_TOKEN");

// with a token, a wrong header is still forbidden
const adminEnv = fakeEnv(); adminEnv.ADMIN_TOKEN = "s3cret";
await worker.fetch(req("POST", "/api/figments/submit", goodListing), adminEnv);
const qid = JSON.parse(await (await worker.fetch(req("GET", "/api/figments"), adminEnv)).text());
ok(qid.pending === 1, "submission queued in admin env");
// find the submitted id from the queue
const queue = JSON.parse(adminEnv._store.get("figments:queue"));
const subId = queue[0].id;
r = await worker.fetch(new Request("https://api.dreamlayer.app/api/figments/" + subId + "/approve", {
  method: "POST", headers: { "CF-Connecting-IP": "1.2.3.4", "X-Admin-Token": "wrong" } }), adminEnv);
ok(r.status === 403, "approve forbidden with a wrong admin token");

// the right token approves it onto the gallery
r = await worker.fetch(new Request("https://api.dreamlayer.app/api/figments/" + subId + "/approve", {
  method: "POST", headers: { "CF-Connecting-IP": "1.2.3.4", "X-Admin-Token": "s3cret" } }), adminEnv);
d = await r.json();
ok(r.status === 200 && d.status === "approved" && d.gallery === 1, "approve moves it onto the gallery");

// the public gallery lists it, with a share code that decodes to the figment
r = await worker.fetch(req("GET", "/api/figments/gallery"), adminEnv);
d = await r.json();
ok(d.lenses.length === 1 && d.lenses[0].name === "Focus" && typeof d.lenses[0].code === "string",
   "gallery lists the approved lens with a share code");
const K = (await import("../landing/assets/lens/figment.js")).default;
const decoded = K.decodeShare(d.lenses[0].code);
ok(decoded && decoded.figment && K.validate(decoded.figment).ok,
   "the gallery's share code decodes to a valid, remixable lens");

// approving again is idempotent (no dupes)
await worker.fetch(new Request("https://api.dreamlayer.app/api/figments/" + subId + "/approve", {
  method: "POST", headers: { "CF-Connecting-IP": "1.2.3.4", "X-Admin-Token": "s3cret" } }), adminEnv);
r = await worker.fetch(req("GET", "/api/figments/gallery"), adminEnv);
ok((await r.json()).lenses.length === 1, "re-approve doesn't duplicate");

if (fails.length) { console.error("FAIL\n" + fails.join("\n")); process.exit(1); }
console.log("ok — figment submit + gallery/approve routes");
