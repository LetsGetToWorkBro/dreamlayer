# The community layer — gallery, Golf, Jams

Lenses are safe to share by construction — a whole lens fits in a link,
and every device re-proves it before running it. The community layer
builds on exactly that property: a remixable public wall, a verified
programming game, and themed jams, all served by the same small Worker at
[api.dreamlayer.app](https://api.dreamlayer.app) that already keeps the
store's ratings. The invariant is unchanged: **the API serves data and
proofs, never executable trust.**

## The gallery — a remixable wall

![The gallery — every lens previews live on its own ring](assets/site/gallery.png)

[dreamlayer.app/gallery.html](https://dreamlayer.app/gallery.html) renders
every published lens *live* — each card is a real canvas running the real
interpreter, not a thumbnail, now drawn as a see-through glass lens over
a fitting illustrative world (each showcase carries its own backdrop; the
HUD is screen-blended over it, exactly the simulator's look). Every entry
carries its share code, so **Remix** opens the full lens in
[the builder](lens-builder.md) in one tap, and Share hands you the link
and QR — and each card wears chips naming the host powers the lens
declared, straight from its signed `requires`.

Getting *into* the gallery is deliberately gated: "a submission is a
request, never a publish." `POST /api/figments/submit` shape-checks the
listing (at most 32 scenes, 64 KiB, bounded names and copy), rate-limits
it, and queues it; a maintainer approves it through an admin-token route
after the Python gate re-checks the budget proof. The gallery itself is
bounded at 500 entries.

## Figment Golf — verified, not voted

![Figment Golf — four challenges, server-verified leaderboards](assets/site/golf.png)

[dreamlayer.app/golf.html](https://dreamlayer.app/golf.html) is code golf
for lenses: build the described behavior in the fewest bytes. Four launch
challenges ship in the engine itself (`figment.js: GOLF`):

| Challenge | Par (bytes) |
|---|---|
| Pocket timer | 270 |
| Last 30 | 340 |
| Two-sided tally | 620 |
| Nod streak | 450 |

What makes it *verified*: acceptance checks are **behaviors, not shapes**
("reads 2:00 a minute in", "hold resets both to zero"), and the Worker
re-runs your submission through the same `LensKit.runChallenge` the
browser uses — it decodes your share code, re-proves it safe, executes
the checks, and **recomputes the byte score server-side**, so the
leaderboard cannot be gamed by a doctored client. Fewest bytes wins;
earlier entry breaks ties; winning codes are published on the board so
every leaderboard is also a lesson. (The referee began life as a CLI —
`dreamlayer golf verify` still scores a lens locally.)

## Lens Jams

Themed, time-boxed collections — a jam has a brief, an opening and a
closing time, and a live status (upcoming / open / closed). A gallery
submission tags the jam id; approved entries appear under the jam's wall.
Jams are admin-created and public-read.

## The hardening underneath

The Worker grew community routes and got hardened in the same breath
(`registry-api/worker.js`, Node test suites alongside):

- **Stored-XSS defense in depth:** all stored text is stripped of control
  characters and angle brackets server-side — no tag can even be stored.
- **Index pollution:** names and jam ids must match a strict slug
  (`^[a-z0-9][a-z0-9-]{0,63}$`); the name index caps at 5,000; comments
  at 500 per plugin; gallery 500; jams 100; golf boards 200.
- **Per-IP rate limits** (fixed-window over KV, failing open so an outage
  never bricks reads): ratings and comments 10/h, downloads 60/h,
  waitlist 5/h, gallery submissions 10/h, golf submissions 40/h.

## The store, meanwhile

The plugin store gained an **official publisher** mark — all six
first-party plugins carry the official mark ("Official — built and
maintained by the DreamLayer team") — and a complete paid-store experience that is
deliberately **switched off**: `PAYMENTS_ENABLED = false`, a "Payments —
coming soon" modal instead of a checkout, and an honest split stated up
front (creators keep 85%, DreamLayer keeps 15% for hosting, review, and
payment fees). The Stripe checkout route is a reserved seam that does not
exist in the Worker yet; sample paid plugins appear only behind
`?preview=paid` and never ship in the catalog. Nothing is charged
anywhere today.
