/**
 * DreamLayer plugin store — social API (Cloudflare Worker).
 *
 * The hosted half of the marketplace (docs/MARKETPLACE.md, phase 2): ratings,
 * comments, and download counts. Plugin *code* stays in the git-backed registry
 * and passes the validation gate; this only serves the numbers. It mirrors the
 * Python reference contract in host-python/.../plugins/social.py exactly.
 *
 *   GET  /api/plugins                 -> {plugins:[{name, ...stats}]}  (index + live stats)
 *   GET  /api/plugins/search?q=…      -> {query, tokens, count, results:[…]}  (ranked search)
 *   GET  /api/plugins/:name           -> {name, ...stats, comments:[…]}
 *   POST /api/plugins/:name/rate      {stars, user} -> stats           (one vote/user)
 *   POST /api/plugins/:name/comment   {text, user}  -> comment
 *   POST /api/plugins/:name/download                 -> {downloads}
 *
 * Binding: a KV namespace `SOCIAL`. Optional var `INDEX_URL` (the raw
 * registry/index.json) so GET /api/plugins can fold stats into the catalogue
 * and /search has a catalogue to rank.
 */

// The lens engine — the SAME module the browser builder runs on. Importing it
// here lets the Worker *re-verify* every Figment Golf submission with the exact
// interpreter the client used (LensKit.runChallenge), so the leaderboard ranks
// proven solutions, and recompute the byte score server-side so it can't be
// gamed. Wrangler bundles it at deploy; Node resolves it in the test harness.
import LensKit from "../landing/assets/lens/figment.js";

// The store's search brain — the SAME module the store page and phone app rank
// their local catalogue with (concept expansion, fielded weights, typo
// tolerance). Importing it here gives headless callers (CLI, Mac panel,
// third-party tooling) the identical ranking over the public index — one
// scorer, three surfaces, zero search servers.
import StoreSearch from "../landing/assets/store/search.js";

const INDEX_URL_DEFAULT =
  "https://raw.githubusercontent.com/LetsGetToWorkBro/dreamlayer/main/registry/index.json";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}

const clampStars = (v) => {
  const n = Math.round(Number(v));
  return Number.isFinite(n) ? Math.max(1, Math.min(5, n)) : 0;
};

async function readJSON(kv, key, fallback) {
  const raw = await kv.get(key);
  if (!raw) return fallback;
  try { return JSON.parse(raw); } catch { return fallback; }
}

// Per-IP fixed-window rate limit over KV. The `user` field on votes is
// client-supplied and trivially spoofable — until votes are account-bound
// (Cloud P1), this is the floor that keeps a loop from minting a thousand
// five-star ratings in an afternoon. Fails OPEN on KV errors: the numbers
// are decoration, availability wins.
async function allowed(env, request, action, max, windowS = 3600) {
  try {
    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    const win = Math.floor(Date.now() / (windowS * 1000));
    const key = `rl:${action}:${ip}:${win}`;
    const n = (Number(await env.SOCIAL.get(key)) || 0) + 1;
    await env.SOCIAL.put(key, String(n), { expirationTtl: windowS * 2 });
    return n <= max;
  } catch {
    return true;
  }
}

const rateLimited = () => json({ error: "rate limited — try later" }, 429);

// A plugin name is a KV key AND is echoed back in GET /api/plugins, so it must
// be a safe, bounded slug — the real registry names are all lowercase
// alphanumerics + hyphens ("open-food-facts"). Rejecting anything else stops
// index pollution and oversized/hostile KV keys from an unauthenticated caller.
function validName(name) {
  return typeof name === "string" && /^[a-z0-9][a-z0-9-]{0,63}$/.test(name);
}

// Neutralise user-supplied text stored server-side (comments, handles). Strips
// control chars and removes angle brackets so no HTML tag can form even for a
// consumer that forgets to escape on render — defence in depth, and it doesn't
// double-encode the client's own escaping (the store page already esc()s).
function cleanText(s, max) {
  s = String(s == null ? "" : s);
  var out = "";
  for (var i = 0; i < s.length; i++) {
    var c = s.charCodeAt(i);
    if (c < 0x20 || c === 0x7f) out += " ";        // control chars -> space
    else if (c === 60 || c === 62) continue;        // drop < and > : no HTML tag can form
    else out += s[i];
  }
  return out.trim().slice(0, max);
}

const INDEX_CAP = 5000;   // bound index:names growth against slug spam

// The share code the gallery hands the client — identical format to the
// builder's LensKit.encodeShare (UTF-8 → base64url of {v,f,a}), so the same
// LensKit.decodeShare re-proves and remixes it.
function shareCode(figment, author) {
  const f = JSON.parse(JSON.stringify(figment));
  if (f.id === "") delete f.id;
  const payload = { v: 1, f };
  if (author) payload.a = String(author).slice(0, 40);
  const utf8 = new TextEncoder().encode(JSON.stringify(payload));
  let bin = "";
  for (let i = 0; i < utf8.length; i++) bin += String.fromCharCode(utf8[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// A public leaderboard row: no PII, just the maker's handle, the proven byte
// score, and the code so anyone can open the winning lens and learn from it.
function lbRow(author, fig, extra) {
  const g = LensKit.golfScore(fig);
  return Object.assign({ author: cleanText(author, 40) || "anon",
    bytes: g.bytes, moves: g.moves, scenes: g.scenes,
    code: shareCode(fig, author), at: Date.now() / 1000 }, extra || {});
}
// Fewest bytes wins; the earlier entry breaks a tie (first to find it).
const byBytes = (a, b) => (a.bytes - b.bytes) || (a.at - b.at);
const rankOf = (sorted, row) =>
  1 + sorted.findIndex((e) => e.author.toLowerCase() === row.author.toLowerCase() && e.bytes === row.bytes);

// A Jam's live state from its window. `opens`/`closes` are unix seconds.
function jamStatus(jam, now) {
  if (jam.opens && now < jam.opens) return "upcoming";
  if (jam.closes && now > jam.closes) return "closed";
  return "open";
}

// Shape-check a figment listing from the builder. Returns an error string, or
// null when it's well-formed. The heavy proof (budgets) is re-run at review by
// the Python gate; this just rejects junk before it queues.
function validateListing(b) {
  if (!b || b.kind !== "figment-listing") return "not a figment listing";
  if (!b.figment || typeof b.figment !== "object") return "missing figment";
  const scenes = b.figment.scenes;
  if (!scenes || typeof scenes !== "object" || Object.keys(scenes).length === 0) return "figment has no scenes";
  if (Object.keys(scenes).length > 32) return "too many scenes";
  if (!b.name || String(b.name).length > 40) return "name is required (≤40 chars)";
  if (!b.author || String(b.author).length > 40) return "author is required (≤40 chars)";
  if (b.description && String(b.description).length > 240) return "description too long";
  const size = JSON.stringify(b.figment).length;
  if (size > 64 * 1024) return "figment too large";
  return null;
}

// The registry can be private, so the *catalogue* lives with the clients — this
// service owns only the numbers. We remember every plugin name we've seen
// activity on, so GET /api/plugins can return their stats for the client to
// merge onto its own catalogue.
async function trackName(env, name) {
  const names = await readJSON(env.SOCIAL, "index:names", []);
  if (!names.includes(name) && names.length < INDEX_CAP) {   // bound growth
    names.push(name);
    await env.SOCIAL.put("index:names", JSON.stringify(names));
  }
}

// -- the catalogue, for /search ----------------------------------------------
// The clients own the catalogue (the registry may be private) and rank it
// locally; this cache exists so headless callers get the same ranking over
// the *public* index without hammering raw.githubusercontent.com. Fresh for
// INDEX_TTL_S; a stale copy is better than a 503 when the fetch flakes, and
// no copy at all degrades to an honest 503 that points at the local module.
const INDEX_TTL_S = 300;

async function catalogue(env) {
  const cached = await readJSON(env.SOCIAL, "cache:index", null);
  const now = Date.now() / 1000;
  if (cached && Array.isArray(cached.plugins) && now - cached.at < INDEX_TTL_S) {
    return { plugins: cached.plugins, stale: false };
  }
  try {
    const res = await fetch(env.INDEX_URL || INDEX_URL_DEFAULT,
      { headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error("index fetch: " + res.status);
    const idx = await res.json();
    const plugins = Array.isArray(idx.plugins) ? idx.plugins : [];
    await env.SOCIAL.put("cache:index", JSON.stringify({ at: now, plugins }),
      { expirationTtl: 86400 });   // stale-serve window, not the freshness TTL
    return { plugins, stale: false };
  } catch {
    if (cached && Array.isArray(cached.plugins)) return { plugins: cached.plugins, stale: true };
    return null;
  }
}

// A search result row: the catalogue fields a store list renders, the ranking
// signals (score + which words matched), and the live social numbers folded
// over the catalogue's placeholders — same merge contract as GET /api/plugins.
async function searchRow(env, r) {
  const p = r.plugin;
  const live = validName(p.name) ? await stats(env, p.name) : null;
  return {
    name: p.name, version: p.version, author: p.author, official: !!p.official,
    description: p.description, tags: p.tags || [], requires: p.requires || [],
    pricing: p.pricing || { model: "free" }, homepage: p.homepage,
    screenshot: p.screenshot, forwho: p.forwho,
    score: r.score, matched: r.matched,
    downloads: (live && live.downloads) || p.downloads || 0,
    rating: (live && live.ratings_count ? live.rating : p.rating) || 0,
    ratings_count: (live && live.ratings_count) || p.ratings_count || 0,
  };
}

async function stats(env, name) {
  const ratings = await readJSON(env.SOCIAL, `ratings:${name}`, {});
  const votes = Object.values(ratings);
  const rating = votes.length
    ? Math.round((votes.reduce((a, b) => a + b, 0) / votes.length) * 100) / 100
    : 0;
  const downloads = await readCounter(env, `downloads:${name}`);
  const comments = await readJSON(env.SOCIAL, `comments:${name}`, []);
  return { name, downloads, rating, ratings_count: votes.length, comments_count: comments.length };
}

// -- atomic counters ---------------------------------------------------------
// A plain KV read-modify-write (`get` then `put`) is NOT atomic: two Workers
// isolates handling concurrent downloads can both read N and both write N+1,
// silently losing a count (audit 2026-07-14). KV has no atomic increment, so
// when a Durable Object counter is bound we route increments through it — a DO
// is single-threaded per key, so its read-add-write is serialised and no
// increment is lost. Without the binding (local/dev/tests on KV only) we fall
// back to the best-effort KV RMW so the endpoint still works.
async function bumpCounter(env, key) {
  if (env.COUNTER) {
    const stub = env.COUNTER.get(env.COUNTER.idFromName(key));
    const res = await stub.fetch("https://counter/incr");
    return Number(await res.text()) || 0;
  }
  const n = (Number(await env.SOCIAL.get(key)) || 0) + 1;
  await env.SOCIAL.put(key, String(n));
  return n;
}

async function readCounter(env, key) {
  if (env.COUNTER) {
    const stub = env.COUNTER.get(env.COUNTER.idFromName(key));
    const res = await stub.fetch("https://counter/value");
    return Number(await res.text()) || 0;
  }
  return Number(await env.SOCIAL.get(key)) || 0;
}

// The Durable Object: one instance per counter key, so storage.get/put run
// serialised (strongly consistent) and concurrent increments can't interleave.
export class Counter {
  constructor(state) {
    this.state = state;
  }
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/incr") {
      // blockConcurrencyWhile serialises the read-add-write against any other
      // in-flight request to THIS object, closing the lost-update window.
      const n = await this.state.blockConcurrencyWhile(async () => {
        const cur = (await this.state.storage.get("n")) || 0;
        const next = cur + 1;
        await this.state.storage.put("n", next);
        return next;
      });
      return new Response(String(n));
    }
    return new Response(String((await this.state.storage.get("n")) || 0));
  }
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });

    const url = new URL(request.url);
    // This is the store's API, not the store. A human landing on the root
    // should go to the browsable store, not see a JSON error.
    if (url.pathname === "/" || url.pathname === "") {
      return Response.redirect("https://dreamlayer.app/plugins", 302);
    }
    const parts = url.pathname.split("/").filter(Boolean); // ["api","plugins",name?,action?]

    // DreamLayer Cloud waitlist (docs/CLOUD.md) — POST {email} joins, GET is
    // the count. Deduped by lowercased email in one KV list. Mirrors the
    // tested Python reference in host-python plugins/social.py.
    if (parts[0] === "api" && parts[1] === "waitlist" && parts.length === 2) {
      if (request.method === "POST") {
        if (!(await allowed(env, request, "waitlist", 5))) return rateLimited();
        const body = await request.json().catch(() => ({}));
        const e = String(body.email || "").trim().toLowerCase().slice(0, 254);
        if (e.length < 6 || e.includes(" ") || !e.slice(1, -1).includes("@")) {
          return json({ error: "invalid email" }, 400);
        }
        const list = await readJSON(env.SOCIAL, "waitlist:cloud", {});
        const already = e in list;
        if (!already) {
          list[e] = Date.now() / 1000;
          await env.SOCIAL.put("waitlist:cloud", JSON.stringify(list));
        }
        return json({ joined: true, already, count: Object.keys(list).length });
      }
      if (request.method === "GET") {
        const list = await readJSON(env.SOCIAL, "waitlist:cloud", {});
        return json({ count: Object.keys(list).length });
      }
      return json({ error: "method not allowed" }, 405);
    }

    // Figment listings from the no-code browser builder (INNOVATION 5.2).
    // POST a listing → it's shape-checked, rate-limited, and queued for a
    // maintainer to review + sign into the catalogue. GET → the queue depth.
    // The registry re-checks the budget proof at review time; a submission is
    // a request, never a publish.
    if (parts[0] === "api" && parts[1] === "figments") {
      if (request.method === "POST" && parts[2] === "submit") {
        if (!(await allowed(env, request, "figment_submit", 10))) return rateLimited();
        const body = await request.json().catch(() => ({}));
        const bad = validateListing(body);
        if (bad) return json({ error: bad }, 400);
        // Small index of pending submissions; the full (up to 64 KiB) listing
        // lives under its own key so the index can never exceed KV's per-value
        // limit, however long the queue grows.
        const queue = await readJSON(env.SOCIAL, "figments:queue", []);
        if (queue.length >= 500) return json({ error: "queue full — try later" }, 503);
        const id = "fig_" + Date.now() + "_" + Math.floor((queue.length + 1));
        await env.SOCIAL.put("figment:sub:" + id, JSON.stringify(body));
        queue.push({
          id,
          name: cleanText(body.name, 40) || "Untitled",
          author: cleanText(body.author, 40),
          scenes: Object.keys(body.figment.scenes || {}).length,
          at: Date.now() / 1000,
        });
        await env.SOCIAL.put("figments:queue", JSON.stringify(queue));
        return json({ status: "queued", id, place: queue.length,
                      note: "queued for maintainer review — the proof is re-checked before it lists" });
      }
      // GET /api/figments/gallery — the public wall of approved, remixable
      // lenses. Each entry carries a share `code` (the whole lens) so the
      // gallery previews and remixes in one request; the client re-proves it.
      if (request.method === "GET" && parts[2] === "gallery") {
        const gal = await readJSON(env.SOCIAL, "figments:gallery", []);
        return json({ lenses: gal });
      }
      // POST /api/figments/:id/approve — maintainer moves a queued submission
      // onto the gallery. Gated by ADMIN_TOKEN; a no-op if it isn't configured.
      if (request.method === "POST" && parts[2] && parts[3] === "approve") {
        if (!env.ADMIN_TOKEN || request.headers.get("X-Admin-Token") !== env.ADMIN_TOKEN)
          return json({ error: "forbidden" }, 403);
        const id = parts[2];
        const sub = await readJSON(env.SOCIAL, "figment:sub:" + id, null);
        if (!sub) return json({ error: "no such submission" }, 404);
        const gal = await readJSON(env.SOCIAL, "figments:gallery", []);
        if (!gal.some((e) => e.id === id)) {
          // carry a jam tag through only if it names a real jam
          let jam = "";
          if (sub.jam && validName(sub.jam)) {
            const jams = await readJSON(env.SOCIAL, "jams:index", []);
            if (jams.some((j) => j.id === sub.jam)) jam = sub.jam;
          }
          gal.unshift({
            id,
            name: cleanText(sub.name, 40) || "Untitled",
            author: cleanText(sub.author, 40),
            description: cleanText(sub.description, 240),
            scenes: Object.keys(sub.figment.scenes || {}).length,
            code: shareCode(sub.figment, sub.author),
            jam,
            at: Date.now() / 1000,
          });
          while (gal.length > 500) gal.pop();     // bound the wall
          await env.SOCIAL.put("figments:gallery", JSON.stringify(gal));
        }
        // drop it from the pending queue
        const queue = await readJSON(env.SOCIAL, "figments:queue", []);
        const nq = queue.filter((e) => e.id !== id);
        if (nq.length !== queue.length) await env.SOCIAL.put("figments:queue", JSON.stringify(nq));
        return json({ status: "approved", id, gallery: gal.length });
      }
      if (request.method === "GET" && !parts[2]) {
        const queue = await readJSON(env.SOCIAL, "figments:queue", []);
        const gal = await readJSON(env.SOCIAL, "figments:gallery", []);
        return json({ pending: queue.length, gallery: gal.length });
      }
      return json({ error: "method not allowed" }, 405);
    }

    // -- Figment Golf: verified byte-golf challenges --------------------------
    // The whole game: express the exact behavior in the fewest bytes. Every
    // submission is decoded, re-proven safe, and run through the challenge's
    // acceptance checks with the SAME interpreter the builder uses — then the
    // byte score is recomputed server-side, so the board can't be gamed.
    if (parts[0] === "api" && parts[1] === "golf") {
      const challenges = LensKit.GOLF;
      // GET /api/golf — the challenge list (brief + par, never the answer)
      if (request.method === "GET" && !parts[2]) {
        return json({ challenges: challenges.map((c) =>
          ({ id: c.id, title: c.title, icon: c.icon, brief: c.brief, par: c.par })) });
      }
      // GET /api/golf/:id/leaderboard — fewest bytes first, code included
      if (request.method === "GET" && parts[2] && parts[3] === "leaderboard") {
        const ch = challenges.find((c) => c.id === parts[2]);
        if (!ch) return json({ error: "no such challenge" }, 404);
        const lb = (await readJSON(env.SOCIAL, "golf:lb:" + parts[2], [])).slice().sort(byBytes);
        return json({ id: parts[2], par: ch.par,
          entries: lb.slice(0, 50).map((e, i) => Object.assign({ rank: i + 1 }, e)) });
      }
      // POST /api/golf/:id/submit {code, author} — verify + rank
      if (request.method === "POST" && parts[2] && parts[3] === "submit") {
        if (!(await allowed(env, request, "golf_submit", 40))) return rateLimited();
        const ch = challenges.find((c) => c.id === parts[2]);
        if (!ch) return json({ error: "no such challenge" }, 404);
        const body = await request.json().catch(() => ({}));
        const got = LensKit.decodeShare(String(body.code || ""));
        if (!got || !got.figment) return json({ error: "that isn't a valid, safe lens" }, 400);
        const res = LensKit.runChallenge(got.figment, ch);
        if (!res.solved) {
          return json({ error: "the lens doesn't solve this challenge yet", solved: false,
            checks: res.checks.filter((c) => !c.ok).map((c) => ({ label: c.label, why: c.why })) }, 422);
        }
        const row = lbRow(cleanText(body.author, 40) || got.author || "anon", got.figment);
        const lb = await readJSON(env.SOCIAL, "golf:lb:" + ch.id, []);
        const prev = lb.find((e) => e.author.toLowerCase() === row.author.toLowerCase());
        if (prev && prev.bytes <= row.bytes) {
          const sorted = lb.slice().sort(byBytes);
          return json({ status: "kept", note: "your best entry still stands",
            rank: rankOf(sorted, prev), bytes: prev.bytes, par: ch.par,
            entries: sorted.slice(0, 50).map((e, i) => Object.assign({ rank: i + 1 }, e)) });
        }
        const next = lb.filter((e) => e.author.toLowerCase() !== row.author.toLowerCase());
        next.push(row);
        next.sort(byBytes);
        while (next.length > 200) next.pop();
        await env.SOCIAL.put("golf:lb:" + ch.id, JSON.stringify(next));
        return json({ status: "accepted", rank: rankOf(next, row), bytes: row.bytes,
          par: ch.par, underPar: ch.par - row.bytes,
          entries: next.slice(0, 50).map((e, i) => Object.assign({ rank: i + 1 }, e)) });
      }
      return json({ error: "method not allowed" }, 405);
    }

    // -- Lens Jams: themed, time-boxed collections ---------------------------
    // A jam gives the community a reason to come back this week — a theme, a
    // window, and a filtered wall. Lenses tag their submission with a jam id;
    // approved ones show up under the jam. Admin defines jams; anyone reads.
    if (parts[0] === "api" && parts[1] === "jams") {
      const now = Date.now() / 1000;
      // GET /api/jams — every jam with its live status + entry count
      if (request.method === "GET" && !parts[2]) {
        const jams = await readJSON(env.SOCIAL, "jams:index", []);
        const gal = await readJSON(env.SOCIAL, "figments:gallery", []);
        return json({ jams: jams.map((j) => Object.assign({}, j, {
          status: jamStatus(j, now),
          entries: gal.filter((e) => e.jam === j.id).length })) });
      }
      // POST /api/jams — admin creates or updates a jam definition
      if (request.method === "POST" && !parts[2]) {
        if (!env.ADMIN_TOKEN || request.headers.get("X-Admin-Token") !== env.ADMIN_TOKEN)
          return json({ error: "forbidden" }, 403);
        const b = await request.json().catch(() => ({}));
        if (!validName(b.id)) return json({ error: "jam id must be a slug" }, 400);
        const jam = { id: b.id, title: cleanText(b.title, 60) || b.id,
          theme: cleanText(b.theme, 120), prompt: cleanText(b.prompt, 400),
          opens: Number(b.opens) || 0, closes: Number(b.closes) || 0, at: now };
        const jams = await readJSON(env.SOCIAL, "jams:index", []);
        const i = jams.findIndex((j) => j.id === jam.id);
        if (i >= 0) jams[i] = jam; else jams.unshift(jam);
        while (jams.length > 100) jams.pop();
        await env.SOCIAL.put("jams:index", JSON.stringify(jams));
        return json({ status: "saved", jam });
      }
      // GET /api/jams/:id — the jam + its approved, remixable lenses
      if (request.method === "GET" && parts[2]) {
        const jams = await readJSON(env.SOCIAL, "jams:index", []);
        const jam = jams.find((j) => j.id === parts[2]);
        if (!jam) return json({ error: "no such jam" }, 404);
        const gal = await readJSON(env.SOCIAL, "figments:gallery", []);
        return json({ jam: Object.assign({}, jam, { status: jamStatus(jam, now) }),
          lenses: gal.filter((e) => e.jam === jam.id) });
      }
      return json({ error: "method not allowed" }, 405);
    }

    if (parts[0] !== "api" || parts[1] !== "plugins") {
      return json({ error: "not found", store: "https://dreamlayer.app/plugins" }, 404);
    }

    // GET /api/plugins/search?q=crypto+prices&limit=10 — ranked catalogue
    // search. "search" is a reserved plugin name from here on (validName would
    // accept it, so this must run before the :name routes). The ranking is
    // StoreSearch.rank — identical to what the store page runs locally — over
    // the KV-cached public index, with live stats folded onto each row.
    if (parts[2] === "search") {
      if (request.method !== "GET" || parts.length !== 3) {
        return json({ error: "method not allowed" }, 405);
      }
      const q = (url.searchParams.get("q") || "").trim().slice(0, 200);
      if (!q) return json({ error: "missing query — try ?q=crypto+prices" }, 400);
      const limit = Math.max(1, Math.min(25, Number(url.searchParams.get("limit")) || 10));
      const cat = await catalogue(env);
      if (!cat) {
        return json({ error: "catalogue unreachable",
          note: "the registry may be private — clients own the catalogue and rank it locally with landing/assets/store/search.js" }, 503);
      }
      const ranked = StoreSearch.rank(cat.plugins, q).slice(0, limit);
      const results = await Promise.all(ranked.map((r) => searchRow(env, r)));
      const body = { query: q, tokens: StoreSearch.tokenize(q), count: results.length, results };
      if (cat.stale) body.note = "catalogue is a cached copy — the live index was unreachable";
      return json(body);
    }

    let name = "";
    if (parts[2]) {
      try { name = decodeURIComponent(parts[2]); } catch { name = parts[2]; }
      if (!validName(name)) return json({ error: "invalid plugin name" }, 400);
    }
    const action = parts[3] || "";

    // GET /api/plugins — stats for every plugin we've seen. The client owns the
    // catalogue (the registry may be private) and merges these by name.
    if (request.method === "GET" && !name) {
      const names = await readJSON(env.SOCIAL, "index:names", []);
      const plugins = await Promise.all(names.map((n) => stats(env, n)));
      return json({ plugins });
    }

    if (!name) return json({ error: "method not allowed" }, 405);

    // GET /api/plugins/:name — stats + comments
    if (request.method === "GET" && !action) {
      const s = await stats(env, name);
      const comments = await readJSON(env.SOCIAL, `comments:${name}`, []);
      return json({ ...s, comments: comments.slice(-50).reverse() });
    }

    if (request.method === "POST") {
      const limits = { rate: 10, comment: 10, download: 60 };
      if (limits[action] && !(await allowed(env, request, action, limits[action]))) {
        return rateLimited();
      }
      const body = await request.json().catch(() => ({}));
      if (action === "rate") {
        const s = clampStars(body.stars);
        const user = cleanText(body.user, 64);
        if (s && user) {
          const ratings = await readJSON(env.SOCIAL, `ratings:${name}`, {});
          ratings[user] = s;                          // one vote per user, updatable
          await env.SOCIAL.put(`ratings:${name}`, JSON.stringify(ratings));
          await trackName(env, name);
        }
        return json(await stats(env, name));
      }
      if (action === "download") {
        const n = await bumpCounter(env, `downloads:${name}`);   // atomic (DO)
        await trackName(env, name);
        return json({ name, downloads: n });
      }
      if (action === "comment") {
        const text = cleanText(body.text, 2000);
        if (!text) return json({ error: "empty comment" }, 400);
        const comments = await readJSON(env.SOCIAL, `comments:${name}`, []);
        if (comments.length >= 500) comments.shift();        // bound per-plugin thread growth
        const c = { id: comments.length + 1, user: cleanText(body.user, 40) || "anon",
                    text, ts: Date.now() / 1000 };
        comments.push(c);
        await env.SOCIAL.put(`comments:${name}`, JSON.stringify(comments));
        await trackName(env, name);
        return json(c);
      }
    }

    return json({ error: "not found" }, 404);
  },
};
