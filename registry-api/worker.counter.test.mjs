/* worker.counter.test.mjs — the download counter is atomic (audit 2026-07-14).
 * A plain KV read-modify-write loses increments under concurrency; the Durable
 * Object counter serialises read-add-write so N concurrent downloads == N.
 * Runs against a fake KV + a fake Durable Object namespace; exit 0 = pass. */
import worker, { Counter } from "./worker.js";

const fails = [];
const ok = (c, m) => { if (!c) fails.push(m); };

const tick = () => new Promise((r) => setTimeout(r, 0));

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

// A fake Durable Object namespace: one persistent Counter per id-name, backed
// by an in-memory storage with a real async gap and a serialising
// blockConcurrencyWhile — so this exercises the actual serialisation contract.
function fakeCounterNS(CounterClass) {
  class FakeStorage {
    constructor() { this.m = new Map(); }
    async get(k) { await tick(); return this.m.get(k); }
    async put(k, v) { await tick(); this.m.set(k, v); }
  }
  class FakeState {
    constructor() { this.storage = new FakeStorage(); this._chain = Promise.resolve(); }
    blockConcurrencyWhile(fn) {
      const run = this._chain.then(() => fn());
      this._chain = run.then(() => {}, () => {});   // keep the chain alive on error
      return run;
    }
  }
  const instances = new Map();
  return {
    idFromName: (name) => name,
    get: (id) => {
      if (!instances.has(id)) instances.set(id, new CounterClass(new FakeState()));
      const inst = instances.get(id);
      // Cloudflare wraps a string arg into a Request; mirror that so the DO's
      // `new URL(request.url)` sees a real URL.
      return { fetch: (input) => inst.fetch(typeof input === "string" ? new Request(input) : input) };
    },
  };
}

const req = (method, path, body) => new Request("https://api.dreamlayer.app" + path, {
  method, headers: { "CF-Connecting-IP": "9.9.9.9", "Content-Type": "application/json" },
  body: body ? JSON.stringify(body) : undefined,
});

// -- sequential increments through the DO count correctly ---------------------
let env = fakeEnv();
env.COUNTER = fakeCounterNS(Counter);
for (let i = 1; i <= 3; i++) {
  const r = await worker.fetch(req("POST", "/api/plugins/seq-plug/download"), env);
  const d = await r.json();
  ok(d.downloads === i, `sequential download ${i} => ${d.downloads}`);
}
// stats reads the count back through the DO (not the stale KV key)
let r = await worker.fetch(req("GET", "/api/plugins/seq-plug"), env);
let d = await r.json();
ok(d.downloads === 3, "stats reads DO-backed download count: " + d.downloads);

// -- N CONCURRENT downloads are all counted (no lost updates) -----------------
// This is the property the DO exists for: with the old KV read-modify-write the
// concurrent isolates read the same value and clobber each other, losing counts.
env = fakeEnv();
env.COUNTER = fakeCounterNS(Counter);
const N = 25;
await Promise.all(Array.from({ length: N }, () =>
  worker.fetch(req("POST", "/api/plugins/atomic-plug/download"), env)));
r = await worker.fetch(req("GET", "/api/plugins/atomic-plug"), env);
d = await r.json();
ok(d.downloads === N, `atomic counter lost updates under concurrency: ${d.downloads} != ${N}`);

// -- KV fallback (no DO binding) still functions ------------------------------
env = fakeEnv();                                  // no COUNTER binding
r = await worker.fetch(req("POST", "/api/plugins/fallback-plug/download"), env);
d = await r.json();
ok(d.downloads === 1, "KV fallback still increments without a DO: " + d.downloads);

if (fails.length) { console.error("FAIL\n" + fails.join("\n")); process.exit(1); }
console.log("ok — download counter: DO-atomic under concurrency, KV fallback intact");
