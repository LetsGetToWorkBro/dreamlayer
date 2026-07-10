/**
 * DreamLayer plugin store — social API (Cloudflare Worker).
 *
 * The hosted half of the marketplace (docs/MARKETPLACE.md, phase 2): ratings,
 * comments, and download counts. Plugin *code* stays in the git-backed registry
 * and passes the validation gate; this only serves the numbers. It mirrors the
 * Python reference contract in host-python/.../plugins/social.py exactly.
 *
 *   GET  /api/plugins                 -> {plugins:[{name, ...stats}]}  (index + live stats)
 *   GET  /api/plugins/:name           -> {name, ...stats, comments:[…]}
 *   POST /api/plugins/:name/rate      {stars, user} -> stats           (one vote/user)
 *   POST /api/plugins/:name/comment   {text, user}  -> comment
 *   POST /api/plugins/:name/download                 -> {downloads}
 *
 * Binding: a KV namespace `SOCIAL`. Optional var `INDEX_URL` (the raw
 * registry/index.json) so GET /api/plugins can fold stats into the catalogue.
 */

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
  if (!names.includes(name)) {
    names.push(name);
    await env.SOCIAL.put("index:names", JSON.stringify(names));
  }
}

async function stats(env, name) {
  const ratings = await readJSON(env.SOCIAL, `ratings:${name}`, {});
  const votes = Object.values(ratings);
  const rating = votes.length
    ? Math.round((votes.reduce((a, b) => a + b, 0) / votes.length) * 100) / 100
    : 0;
  const downloads = Number(await env.SOCIAL.get(`downloads:${name}`)) || 0;
  const comments = await readJSON(env.SOCIAL, `comments:${name}`, []);
  return { name, downloads, rating, ratings_count: votes.length, comments_count: comments.length };
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
          name: String(body.name || "Untitled").slice(0, 40),
          author: String(body.author || "").slice(0, 40),
          scenes: Object.keys(body.figment.scenes || {}).length,
          at: Date.now() / 1000,
        });
        await env.SOCIAL.put("figments:queue", JSON.stringify(queue));
        return json({ status: "queued", id, place: queue.length,
                      note: "queued for maintainer review — the proof is re-checked before it lists" });
      }
      if (request.method === "GET" && !parts[2]) {
        const queue = await readJSON(env.SOCIAL, "figments:queue", []);
        return json({ pending: queue.length });
      }
      return json({ error: "method not allowed" }, 405);
    }

    if (parts[0] !== "api" || parts[1] !== "plugins") {
      return json({ error: "not found", store: "https://dreamlayer.app/plugins" }, 404);
    }

    const name = parts[2] ? decodeURIComponent(parts[2]) : "";
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
        const user = String(body.user || "").slice(0, 64);
        if (s && user) {
          const ratings = await readJSON(env.SOCIAL, `ratings:${name}`, {});
          ratings[user] = s;                          // one vote per user, updatable
          await env.SOCIAL.put(`ratings:${name}`, JSON.stringify(ratings));
          await trackName(env, name);
        }
        return json(await stats(env, name));
      }
      if (action === "download") {
        const n = (Number(await env.SOCIAL.get(`downloads:${name}`)) || 0) + 1;
        await env.SOCIAL.put(`downloads:${name}`, String(n));
        await trackName(env, name);
        return json({ name, downloads: n });
      }
      if (action === "comment") {
        const text = String(body.text || "").trim().slice(0, 2000);
        if (!text) return json({ error: "empty comment" }, 400);
        const comments = await readJSON(env.SOCIAL, `comments:${name}`, []);
        const c = { id: comments.length + 1, user: String(body.user || "anon").slice(0, 40),
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
