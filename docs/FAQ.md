# DreamLayer — Frequently Asked Questions

A plain-language answer to the questions that keep coming up in Discord. If you
only read one entry, read the first — it clears up the biggest misunderstanding.

---

## "How can this work? The display is only 256×256."

This is the number-one confusion, and the short answer is: **the display is not
where the work happens. It's just the window the answer comes out of.**

The Brilliant Labs Halo has a small in-eye display, and DreamLayer renders to a
**256×256** target (`host-python/src/dreamlayer/hud/renderer.py`, `SIZE = 256`).
People see that number and picture trying to run "AI glasses" on a screen smaller
than an app icon. But that's not what the display is for.

**The display's whole job is to show one glanceable card.** A name. A fact-check
verdict. One translated line. "Maya owes you $20." A bearing arrow to a friend in
a crowd. You are not watching a video or reading a webpage in your eye — you are
catching a one-second cue in your periphery and looking back at the world.
256×256 is *plenty* for a few lines of crisp text and a simple glyph. The product
principle is literally **"one thought at a time, glanceable in under two
seconds"** (see `docs/PRODUCT_SPEC.md`). A big, dense screen would be the wrong
design, not a better one.

**All the intelligence runs off the glasses.** DreamLayer is a **host-driven**
stack (`docs/ARCHITECTURE.md`):

```
+---------------------------+       BLE        +----------------------+
|  Host (phone / Mac / PC)  | <--------------> |   Halo glasses       |
|                           |  typed messages  |                      |
|  - memory engine          | -- cards ------> |  - draw the card     |
|  - retrieval + embeddings |                  |  - read taps / gaze  |
|  - LLM reasoning          | <-- events ----- |  - low-latency state |
|  - fact-check, lenses     |                  |                      |
+---------------------------+                  +----------------------+
```

The glasses capture input and emit events; the host does the heavy lifting —
memory, retrieval, language models, fact-checking — and sends back a finished
**card payload**. The renderer rasterizes that card to a 256×256 image and ships
it over Bluetooth. The glasses just draw it. Heavy compute → host. Glanceable
pixels + input → device. That split is the point: it keeps the on-device app
small, deterministic, and low-power.

So "only 256×256" isn't a limitation the project is fighting — it's the canvas
the product was designed around.

---

## "Where does the AI actually run, then?"

Wherever you point it, in tiers, local-first:

- **On the paired phone / a home "Brain" (Mac or PC)** — the default. The memory
  engine, the vector store, and a local model (via Ollama, and optionally exo
  across a few machines you own) run here. No cloud required.
- **In the cloud, only if you opt in** — for heavier reasoning you can wire a
  cloud model. It is opt-in, not the default.
- **On-device tier-0** — a tiny coarse classifier / wake-word seam runs on the
  glasses' own silicon for the fastest, cheapest first pass, before anything
  leaves the frames.

The glasses never need to be a supercomputer, because they aren't the computer.

---

## "Is this real, or a mockup / render?"

The software is real and runs today against an emulator; the hardware path is
built but pre-device. Two specifics people ask about:

- **The HUD frames in the demos and on the site are genuine renderer output** —
  the same `hud/renderer.py` code path that drives the device, at the real
  256×256, not Photoshop mockups.
- **Everything is testable headless.** `emulator_bridge.py` drives a Lua runtime
  with a virtual framebuffer and event injection, so the whole flow — capture →
  memory → card → draw — runs and is covered by an automated test suite. The
  real-device bridge (`real_bridge.py`) implements the *same* interface over
  Brilliant's BLE stack, so swapping from emulator to glasses needs no changes to
  the app logic.

We make no shipping-date claims. It's an early build.

---

## "Isn't a camera on your face a privacy nightmare?"

Privacy is a designed-in constraint, not an afterthought:

- **Structured meaning, not raw media.** By default DreamLayer stores the
  *structured* memory ("promised Jordan the deck by Friday"), not a hoard of
  photos and audio. Raw-media hoarding is an explicit non-goal.
- **The Privacy Veil.** One gesture visibly and instantly stops capture. When the
  Veil is down, the write path refuses — in the newer code this is enforced as a
  *type invariant*: a memory record literally cannot be constructed while capture
  is disallowed, and structured-concurrency helpers cancel every in-flight task
  the moment the Veil drops.
- **PII redaction before write.** Emails, phone numbers, and long digit strings
  are redacted on the way into memory.
- **It's always obvious when memory is active vs paused** — that's HUD principle
  #10, not fine print.

---

## "Which glasses does it need? Only Halo?"

Halo is the first target because that's the hardware this build is written
against. But the architecture deliberately keeps the device behind a thin,
typed bridge, so any capable glasses with a small display + input + a data link
are a future target. The intelligence layer doesn't care what's drawing the
pixels.

---

## "How do I interact with it if there's no keyboard?"

Glance, gesture, and voice. You look at something; a tap or a head gesture
confirms; short voice intents ("note that", "who is this", "what did I promise
them") drive the rest. When more than one thing could be worth showing, a
**Glance Arbiter** decides the single most useful card to surface — so the tiny
display never has to show a menu.

---

## "Can I build on it? Is it open?"

There's a formal plugin surface (`plugins/base.py`) — third parties can add
object providers, new glance candidates, card renderers, and shop/price
providers through one narrow, capability-gated doorway, without touching core.
A recent pass also added an optional entry-point/pluggy discovery path so a
plugin can ship as an ordinary Python package. First-party features are built
*through the same doorway* (we dogfood it).

---

## "What's the catch with the small display — what can't it do?"

It won't show you a movie, a web browser, or a dense dashboard in your eye, and
it isn't trying to. If a task needs a real screen, that belongs on your phone.
DreamLayer's job is the opposite: take everything it knows and distill it to the
*one* glanceable thing worth a second of your attention. The constraint is the
feature.

---

*Have a question that keeps coming up and isn't here? Open an issue or drop it in
Discord and we'll fold it into this list.*
