/* worker.search.test.mjs — the ranked catalogue search, module and route.
 * The module must understand store-speak ("find me a plugin for crypto prices
 * on my hud" → currency-converter), survive typos, and weight names over body
 * copy; the route must validate input, cache the index in KV, serve stale over
 * 503, and fold live stats onto rows. Fixture = the REAL registry/index.json,
 * so ranking stays in lockstep with the shipped catalogue. Exit 0 = pass. */
import worker from "./worker.js";
import StoreSearch from "../landing/assets/store/search.js";
import { readFileSync } from "node:fs";

const fails = [];
const ok = (c, m) => { if (!c) fails.push(m); };

const INDEX = JSON.parse(readFileSync(new URL("../registry/index.json", import.meta.url), "utf8"));
const PLUGINS = INDEX.plugins;

// -- the module: pure (catalogue, query) → ranked rows ------------------------

let r = StoreSearch.rank(PLUGINS, "crypto prices");
ok(r.length && r[0].plugin.name === "currency-converter",
  "concept expansion: 'crypto prices' → currency-converter, got " + (r[0] && r[0].plugin.name));
ok(r[0].matched.length > 0 && typeof r[0].score === "number", "results carry score + matched words");

r = StoreSearch.rank(PLUGINS, "find me a plugin for crypto prices on my hud");
ok(r.length && r[0].plugin.name === "currency-converter",
  "store-speak stopwords stripped: full sentence still → currency-converter");

r = StoreSearch.rank(PLUGINS, "curency converter");
ok(r.length && r[0].plugin.name === "currency-converter",
  "typo tolerance: 'curency' (one edit) still → currency-converter");

r = StoreSearch.rank(PLUGINS, "drums");
ok(r.length && r[0].plugin.name === "air-drums", "name hit outranks body copy: 'drums' → air-drums");

r = StoreSearch.rank(PLUGINS, "hud");
ok(r.length && r[0].plugin.name === "hud-reactions",
  "an all-stopword query falls back to literal matching: 'hud' → hud-reactions");

r = StoreSearch.rank(PLUGINS, "calories");
ok(r.length && r[0].plugin.name === "open-food-facts", "'calories' → open-food-facts");

r = StoreSearch.rank(PLUGINS, "presentation coach");
ok(r.length && r[0].plugin.name === "filler-word-counter", "'presentation coach' → filler-word-counter");

r = StoreSearch.rank(PLUGINS, "emoji");
ok(r.length && r[0].plugin.name === "hud-reactions", "'emoji' → hud-reactions");

ok(StoreSearch.rank(PLUGINS, "quantum zebra").length === 0, "no match → empty, never noise");
ok(StoreSearch.rank([], "music").length === 0, "empty catalogue → empty");
ok(StoreSearch.rank(PLUGINS, "").length === 0, "empty query → empty");

// every concept expands into lowercase single words (the tokenizer's alphabet)
for (const [k, exps] of Object.entries(StoreSearch.CONCEPTS)) {
  ok(exps.every((w) => /^[a-z0-9]+$/.test(w)), "concept '" + k + "' expands to plain tokens");
}

// -- the route: /api/plugins/search -------------------------------------------

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
  method, headers: { "CF-Connecting-IP": "9.9.9.9", "Content-Type": "application/json" },
  body: body ? JSON.stringify(body) : undefined,
});

// the Worker fetches INDEX_URL — serve the fixture, or fail on demand
let indexReachable = true;
globalThis.fetch = async () => {
  if (!indexReachable) throw new Error("network down");
  return new Response(JSON.stringify(INDEX), { headers: { "Content-Type": "application/json" } });
};

let env = fakeEnv();

// a missing/blank query is a 400, not an empty result set
let res = await worker.fetch(req("GET", "/api/plugins/search"), env);
ok(res.status === 400, "missing q → 400: " + res.status);
res = await worker.fetch(req("GET", "/api/plugins/search?q=%20%20"), env);
ok(res.status === 400, "blank q → 400");

// the happy path: ranked rows with scores, matched words, and stats fields
res = await worker.fetch(req("GET", "/api/plugins/search?q=crypto+prices"), env);
let d = await res.json();
ok(res.status === 200, "search → 200");
ok(d.results.length && d.results[0].name === "currency-converter",
  "route ranks like the module: crypto prices → currency-converter");
ok(Array.isArray(d.tokens) && d.tokens.includes("crypto"), "response echoes the tokens used");
ok(typeof d.results[0].score === "number" && Array.isArray(d.results[0].matched),
  "rows carry ranking signals");
ok("downloads" in d.results[0] && "rating" in d.results[0], "rows carry social stats");
ok(!("note" in d), "fresh catalogue → no staleness note");

// live stats are folded over the catalogue's placeholder numbers
await worker.fetch(req("POST", "/api/plugins/currency-converter/download"), env);
res = await worker.fetch(req("GET", "/api/plugins/search?q=crypto"), env);
d = await res.json();
ok(d.results[0].downloads === 1, "live download count folded onto the row: " + d.results[0].downloads);

// limit is clamped to something a client can actually want
res = await worker.fetch(req("GET", "/api/plugins/search?q=music&limit=1"), env);
d = await res.json();
ok(d.count === 1 && d.results.length === 1, "limit=1 respected");
res = await worker.fetch(req("GET", "/api/plugins/search?q=music&limit=99999"), env);
ok(res.status === 200, "hostile limit clamped, not fatal");

// the index is KV-cached: kill the network, search still answers from cache
indexReachable = false;
res = await worker.fetch(req("GET", "/api/plugins/search?q=drums"), env);
d = await res.json();
ok(res.status === 200 && d.results[0].name === "air-drums", "fresh KV cache answers with the network down");

// an EXPIRED cache + dead network serves stale with an honest note
const cached = JSON.parse(env._store.get("cache:index"));
cached.at = 1;                                  // long past the freshness TTL
env._store.set("cache:index", JSON.stringify(cached));
res = await worker.fetch(req("GET", "/api/plugins/search?q=drums"), env);
d = await res.json();
ok(res.status === 200 && d.note && d.results[0].name === "air-drums",
  "stale cache beats a 503, and says so: " + JSON.stringify(d.note));

// no cache at all + dead network is an honest 503 pointing at the local module
env = fakeEnv();
res = await worker.fetch(req("GET", "/api/plugins/search?q=drums"), env);
ok(res.status === 503, "no catalogue anywhere → 503: " + res.status);
indexReachable = true;

// "search" is a reserved name — the social POST routes must not shadow it
res = await worker.fetch(req("POST", "/api/plugins/search"), env);
ok(res.status === 405, "POST /api/plugins/search → 405, not a plugin named 'search'");
res = await worker.fetch(req("POST", "/api/plugins/search/download"), env);
ok(res.status === 405, "POST /api/plugins/search/download → 405");

// searching never pollutes the social index of seen names
res = await worker.fetch(req("GET", "/api/plugins/search?q=crypto"), env);
res = await worker.fetch(req("GET", "/api/plugins"), env);
d = await res.json();
ok((d.plugins || []).length === 0, "search is read-only on the social index");

if (fails.length) { console.error("FAIL\n" + fails.join("\n")); process.exit(1); }
console.log("ok — search: ranking (concepts, typos, weights, stopwords) + route (cache, stale, 503, clamps, reserved name)");
