# DreamLayer plugin store — social API

The hosted half of the marketplace (`docs/MARKETPLACE.md`, phase 2): **ratings,
comments, and download counts**. Plugin *code* stays in the git-backed
`registry/` and passes the validation gate — this service only serves the
numbers, so a compromise here can't ship code to anyone.

It's a Cloudflare Worker over a KV namespace. The behaviour is pinned by a
tested Python reference implementation and contract in
`host-python/src/dreamlayer/plugins/social.py` (`SocialStore` + `route`); the
Worker mirrors it exactly.

## Contract

```
GET  /api/plugins                 → {plugins:[{name, ...stats}]}   index + live stats
GET  /api/plugins/search?q=…      → {query, tokens, count, results:[…]}   ranked search
GET  /api/plugins/<name>          → {name, ...stats, comments:[…]}
POST /api/plugins/<name>/rate     {stars, user} → stats            one vote/user, updatable
POST /api/plugins/<name>/comment  {text, user}  → comment
POST /api/plugins/<name>/download                → {downloads}
```

`stats` = `{downloads, rating, ratings_count, comments_count}`.

## Search

`GET /api/plugins/search?q=crypto+prices&limit=10` ranks the public catalogue
(`INDEX_URL`, KV-cached for 5 minutes, stale-served when the fetch flakes)
with **the same engine the store page and phone app run locally**:
`landing/assets/store/search.js` — the figment.js pattern, one module for
browser and Worker. It understands store-speak ("find me a plugin for crypto
prices on my HUD" → `currency-converter`) through three deliberate mechanisms:
fielded keyword weights (name > tags > blurb), a curated concept map
(`crypto`→currency/money, `calories`→food/nutrition — grow it alongside the
catalogue), and one-edit typo tolerance. Each result row carries the ranking
signals (`score`, `matched`) plus live social stats folded over the
catalogue's placeholders.

Deliberately **not** a search server (no Typesense, no embeddings box): the
catalogue is a few KB of git-backed JSON and the clients own their copy — a
pure scorer that runs wherever the catalogue is beats infrastructure the
numbers don't need. `search` is a reserved plugin name. If the registry goes
private and no cached copy exists, the route answers `503` and clients keep
ranking locally — same graceful-degradation contract as everything else here.

## Deploy

```
cd registry-api
npx wrangler kv namespace create SOCIAL      # copy the id into wrangler.toml
npx wrangler deploy
```

It's deployed at **`https://api.dreamlayer.app`** (a Workers custom domain; the
`*.workers.dev` URL keeps working too). The clients already point at it:

- **Website** — `SOCIAL_API` in `landing/plugins.html`.
- **Phone app** — `SOCIAL_API` in `phone-app/src/state/usePluginStore.ts`.

Both clients **degrade gracefully**: with `SOCIAL_API` empty or the Worker
unreachable, they fall back to the static `registry/index.json` (the git-backed
phase 1). So the store works before this is deployed, and gets live numbers +
one-tap rating once it is — zero rework, exactly the phased plan.

## Notes / hardening

- v1 identifies raters by a client-generated `user` id (anonymous, stable per
  device). **Per-IP rate limits now run at the Worker edge** (fixed-window
  over KV: 10 rates/h, 10 comments/h, 60 downloads/h, 5 waitlist joins/h;
  fails open on KV errors — the numbers are decoration, availability wins).
  That is the floor, not the ceiling: the `user` field is still spoofable
  one-vote-per-hour-per-IP, so do NOT surface a "top rated" ranking as an
  editorial signal until votes are account-bound (Cloud P1 accounts + signed
  session tokens; Turnstile is the interim option if rankings must ship
  sooner).
- CORS is open (`*`) so the static site can call it; tighten to your domains in
  production.
