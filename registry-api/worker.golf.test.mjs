/* worker.golf.test.mjs — Figment Golf leaderboard + Lens Jams routes.
 * The point of these: the board only ranks *verified* solutions (re-run through
 * the real interpreter server-side) and the byte score is authoritative. Runs
 * the Worker against a fake KV; exit 0 = pass. Driven by test_lens_builder.py. */
import worker from "./worker.js";
const K = (await import("../landing/assets/lens/figment.js")).default;

const fails = [];
const ok = (c, m) => { if (!c) fails.push(m); };

function fakeEnv() {
  const store = new Map();
  return { SOCIAL: {
    get: async (k) => (store.has(k) ? store.get(k) : null),
    put: async (k, v) => { store.set(k, v); },
  }, _store: store };
}
const req = (method, path, body, headers) => new Request("https://api.dreamlayer.app" + path, {
  method, headers: Object.assign({ "CF-Connecting-IP": "9.9.9.9", "Content-Type": "application/json" }, headers || {}),
  body: body ? JSON.stringify(body) : undefined,
});
const call = async (env, ...a) => { const r = await worker.fetch(req(...a), env); return { r, d: await r.json() }; };

// -- reference solutions (built with the same LensKit the builder ships) ------
function pocketTimer(name) {           // solves "pocket-timer"
  const f = K.figment(name || "Timer", "a");
  K.addScene(f, K.scene("a", { duration_sec: 180, tick: "countdown",
    lines: [K.line("{remaining}")], on_timeout: [{ target: K.END }] }));
  return f;
}
function tooShort() {                   // a valid lens that does NOT solve it
  const f = K.figment("Nope", "a");
  K.addScene(f, K.scene("a", { duration_sec: 60, tick: "countdown",
    lines: [K.line("{remaining}")], on_timeout: [{ target: K.END }] }));
  return f;
}
const codeFor = (fig, author) => K.encodeShare(fig, { author });

const env = fakeEnv();

// the challenge list is public — brief + par, and never the acceptance answer
let { d } = await call(env, "GET", "/api/golf");
ok(d.challenges.length >= 4 && d.challenges[0].brief && d.challenges[0].par > 0, "golf lists challenges with briefs");
ok(!("checks" in d.challenges[0]), "the challenge list does not leak the acceptance checks");

// a solving lens is accepted, ranked #1, and its byte score is server-computed
let res = await call(env, "POST", "/api/golf/pocket-timer/submit", { code: codeFor(pocketTimer(), "ada"), author: "ada" });
ok(res.r.status === 200 && res.d.status === "accepted" && res.d.rank === 1, "a solving lens is accepted at rank 1: " + JSON.stringify(res.d));
ok(res.d.bytes === K.golfScore(pocketTimer()).bytes, "the byte score is recomputed server-side (authoritative)");
ok(res.d.underPar === res.d.par - res.d.bytes, "under-par is reported");

// a valid but wrong lens is rejected with the failing checks (not ranked)
res = await call(env, "POST", "/api/golf/pocket-timer/submit", { code: codeFor(tooShort(), "eve"), author: "eve" });
ok(res.r.status === 422 && res.d.solved === false && res.d.checks.length, "a non-solving lens is refused with reasons: " + JSON.stringify(res.d));

// a byte-cheaper STATIC label that never counts down must NOT be accepted
// (the whole point of "verified" — it defeats the brief even though it's smaller)
function staticLabel() {
  const f = K.figment("Timer", "a");
  K.addScene(f, K.scene("a", { duration_sec: 180, tick: "countdown",
    lines: [K.line("3:00")], on_timeout: [{ target: K.END }] }));
  return f;
}
ok(K.golfScore(staticLabel()).bytes < K.golfScore(pocketTimer()).bytes, "the static-label lens really is byte-cheaper");
res = await call(env, "POST", "/api/golf/pocket-timer/submit", { code: codeFor(staticLabel(), "cheat"), author: "cheat" });
ok(res.r.status === 422 && res.d.solved === false, "a static (non-counting) timer is refused despite fewer bytes");

// garbage is refused before it can touch the board
res = await call(env, "POST", "/api/golf/pocket-timer/submit", { code: "!!!not-a-lens!!!", author: "mallory" });
ok(res.r.status === 400, "garbage code is refused");

// an unknown challenge id 404s instead of returning an empty board
res = await call(env, "GET", "/api/golf/no-such-challenge/leaderboard");
ok(res.r.status === 404, "unknown challenge leaderboard 404s");

// the leaderboard shows only the verified entry
({ d } = await call(env, "GET", "/api/golf/pocket-timer/leaderboard"));
ok(d.entries.length === 1 && d.entries[0].author === "ada" && d.entries[0].code, "leaderboard lists the verified entry with its code");
ok(K.runChallenge(K.decodeShare(d.entries[0].code).figment, K.GOLF[0]).solved, "the board's code really solves the challenge");

// a tighter solution from a second maker takes #1; the byte order is honest
const tight = pocketTimer("T");        // 1-char name → fewer bytes
res = await call(env, "POST", "/api/golf/pocket-timer/submit", { code: codeFor(tight, "bo"), author: "bo" });
ok(res.d.rank === 1 && res.d.bytes < K.golfScore(pocketTimer()).bytes, "a smaller lens takes the top spot");

// a maker's worse resubmission is ignored — their best stands
res = await call(env, "POST", "/api/golf/pocket-timer/submit", { code: codeFor(pocketTimer("Timerrrr"), "bo"), author: "bo" });
ok(res.d.status === "kept", "a worse resubmission keeps the maker's best");
({ d } = await call(env, "GET", "/api/golf/pocket-timer/leaderboard"));
ok(d.entries.filter((e) => e.author === "bo").length === 1, "no duplicate entries per maker");

// -- Lens Jams --------------------------------------------------------------
// creating a jam is admin-gated
res = await call(env, "POST", "/api/jams", { id: "neon-week", title: "Neon Week" });
ok(res.r.status === 403, "jam create is forbidden without the admin token");

const adminEnv = fakeEnv(); adminEnv.ADMIN_TOKEN = "s3cret";
const admin = { "X-Admin-Token": "s3cret" };
res = await call(adminEnv, "POST", "/api/jams", { id: "neon-week", title: "Neon Week",
  theme: "glow", prompt: "Make the glass glow.", opens: 1, closes: 4102444800 }, admin);
ok(res.r.status === 200 && res.d.jam.id === "neon-week", "admin creates a jam");

({ d } = await call(adminEnv, "GET", "/api/jams"));
ok(d.jams.length === 1 && d.jams[0].status === "open" && d.jams[0].entries === 0, "jam lists open with a live status + count");

// a lens submitted with the jam tag lands under the jam once approved
const listing = K.listing(pocketTimer("Glow"), { author: "ada", description: "glow timer" });
listing.jam = "neon-week";
await call(adminEnv, "POST", "/api/figments/submit", listing);
const subId = JSON.parse(adminEnv._store.get("figments:queue"))[0].id;
await worker.fetch(new Request("https://api.dreamlayer.app/api/figments/" + subId + "/approve", {
  method: "POST", headers: { "CF-Connecting-IP": "9.9.9.9", "X-Admin-Token": "s3cret" } }), adminEnv);
({ d } = await call(adminEnv, "GET", "/api/jams/neon-week"));
ok(d.jam.id === "neon-week" && d.lenses.length === 1 && d.lenses[0].name === "Glow", "an approved jam-tagged lens shows under the jam: " + JSON.stringify(d.lenses.map((l) => l.name)));

if (fails.length) { console.error("FAIL\n" + fails.join("\n")); process.exit(1); }
console.log("ok — figment golf (verified) + lens jams routes");
