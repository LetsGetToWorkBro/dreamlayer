# Attention and focus

Two opposing forces, one policy: DreamLayer must be able to *interrupt you
out loud* when a moment genuinely demands it, and must be able to *shut up
completely* when you demand that. The attention policy decides the first;
Focus mode enforces the second; the proactive-cue picker tunes everything in
between.

## The hark — "Listen!" and "Watch out!"

A **hark** is the system tapping you on the shoulder: one line, one ring, an
earcon, a haptic.

![A tap on the shoulder](assets/demo/catalog/features/hark/preview.webp)

`orchestrator/attention.py: AttentionPolicy.evaluate(ctx, commitments)` scans
the same live `Context` the anticipation engine sees and produces at most a
handful of ranked alerts:

| Trigger | Level | Example clue |
|---|---|---|
| An event you must leave for within 6 minutes | **watch-out** (urgent) | "4 min to Standup" — "leave for Studio B" |
| Someone you owe is in view right now | listen | "You owe Maya — send the lease" |
| You are walking away from a place that holds your anchor | listen | "You're leaving your bike" |
| A commitment inside its 48-hour slip window | listen | "send the lease by Friday" |

The discipline that keeps it from nagging:

- **One hark at a time** — `attention_tick` speaks only the single most
  important fresh alert, watch-outs ranked first.
- **A 30-minute per-key cooldown** — the same alert cannot repeat inside
  half an hour, and a key is only marked consumed if the hark actually
  spoke (a veil- or focus-suppressed hark does not burn the alert).
- The hark call itself adds a second 120-second cooldown across all harks.
- **Normal harks are held during Focus; urgent watch-outs pierce it.**
  Everything is silenced by the Veil.
- `set_attention(False)` (the phone's "Proactive alerts" toggle, or "Hey
  Juno, stop keeping watch") mutes the policy entirely.

The heartbeat: `pulse(context)` — or the background `start_pulse(context_fn,
interval=15.0)` — runs anticipation and attention together on one context
snapshot. **Seam:** the live context feed (place, people in view, clock)
that a device build supplies to the pulse.

## Focus mode

`set_focus(minutes)` — default 25 by voice ("Hey Juno, focus mode") —
turns the *interruptions* down while **capture keeps running**. That second
half is the difference from Incognito, which pauses capture itself.

Held while Focus is active: anticipation cards, live caption display, message
pop-ups, fact-check cards, delivery reads, answer-ahead, commitment-capture
confirmations, and normal harks. Still running underneath: the ledger, the
user model, commitment tracking, and recall on demand. Still allowed through:
**urgent watch-outs**, and anything you explicitly ask for.

`clear_focus()` ends it early; `focus_active()` reports it; turning Focus on
from the phone also unlocks the Saga's Deep Focus badge.

## The proactive-cue picker

Finer than on/off: `set_cue(kind, on)` mutes any of the three anticipatory
kinds — `event`, `person`, `place` — before the engine's ranking pass, so
you can keep "leave in 8 minutes" while silencing arrival reminders. The
phone nests these three under its Proactive cards toggle. `cue_kinds()`
reports current state.

## The deviation nudge

Related but distinct: the Tell engine (`tell_check`) compares fresh
transcript against your prior commitments and raises a **DeviationAlertCard**
when the new words contradict the old plan — before-versus-now across a
dashed divider, with a severity dot.

![Off your usual path](assets/demo/catalog/features/deviation/preview.webp)

## The Glance Arbiter — which lens owns a look

The hark decides *when* to speak; the Glance Arbiter
(`orchestrator/glance.py`) decides *which lens* a look belongs to — without a
mode picker, because a menu is friction on glasses. On a look, `glance(frame)`
classifies what's in view and every candidate lens **bids**; the arbiter fires
the clear winner, offers a one-tap chooser when it's genuinely ambiguous, or
does nothing.

It reuses the Object Lens provider-registry shape, lifted up a level: there,
providers declare `matches(sighting)` and the registry merges rows into a
panel; here, candidates declare `bid(reading, ctx)` and the registry ranks them
into one decision.

- **Two-tier read.** A free coarse pass (`classify_coarse` over cheap on-device
  cues) runs first; only when it can't tell a form from a question from prose
  (`is_ambiguous`) does the hub spend the Brain's vision tier for a fine read.
  The big model is used *when it changes the answer*, not on every glance.
- **What the coarse pass can honestly see.** Text density, horizontal banding,
  per-axis repetition, overall darkness, scattered point-lights, contrast, and
  high-frequency energy (blur) — plus, from the wearer's own device, where the
  camera is pointed, how long a focus has held, the local hour, and whatever the
  phone's own object detector already saw. Some cues are deliberately *not*
  inferred from pixels: a menu, and a shelf of comparable things, are claimed
  only when a detector genuinely saw several of the same kind of thing, because
  to a gradient profile a bookshelf and a radiator are the same picture. A cue
  that can't be justified is left unset rather than guessed — an absent cue never
  masquerades as a negative.
- **Fire vs offer.** The top bid fires outright when it beats the runner-up by
  the gap (or a spoken intent forced it, or it's the only bidder); otherwise a
  **GlanceChoiceCard** offers the close contenders ("Answer it · Fill it in ·
  Translate"). A pick runs that lens *and* teaches the arbiter.
- **It learns you.** Per-scene priors (`GlancePriors`) reinforce the lens you
  keep choosing for a kind of scene — and for that scene *at that time of day* —
  so tomorrow's ambiguous look leans your way. They persist as a small JSON in
  the Brain's config directory (`glance_priors.json`, the same pattern as the
  user model) — read once at start, rewritten on each pick, in-memory only when
  there's no hub. The local file stays the source of truth so a glance never
  waits on the network; the dict is still serialisable, so a Mac Brain can later
  mirror it across hubs.

  Where this runs, precisely, because the two tiers are not yet symmetric: the
  arbiter is live on the **Live Lens / phone** path (`ai_brain/server/live.py`
  → `world_lens.py`, its own `LIVE_CANDIDATES` set, writing
  `glance_priors.json`). The **glasses-side** twin (`Orchestrator.glance()` /
  `choose_glance()`, `DEFAULT_CANDIDATES`, and a `glancepriors.json` beside the
  vault) has no camera entry point and no uplink from a chooser tap yet, so on
  the glasses the GlanceChoiceCard is drawn but not yet answered, and that file
  is never written. Treat this section as describing the Live Lens today.
- **Only from answers you actually got.** A pick teaches the arbiter only when
  the lens it ran *worked*, and never while the Veil is up — the shield writes
  nothing to disk, priors included. Crediting the tap instead of the result meant
  a lens whose pack wasn't installed still built a habit out of three "install the
  pack" cards. (Both guards live on the Live Lens path; the glasses-side
  `choose_glance()` above is unwired and has neither.)
- **A habit is never a cage.** Counts decay as they accumulate, so a row
  converges rather than growing without bound and a few contrary picks revise a
  formed preference. And once the arbiter is confident enough to stop asking, the
  fire it makes still carries the alternatives it *chose* not to ask about — it
  answers instantly, and the other lens stays one tap away. Not asking is the
  feature; making the alternative unreachable was a bug.
- **Spoken steer.** A recent "read this / how far is that / where are my keys"
  steers the very next look — one utterance, one look. What you said is not a
  guess about your intent, it *is* your intent, so a request that names a lens
  runs it outright. The parser only accepts a **directed** phrase: one that
  points at something ("this", "that", "my keys") and usually stops there.
  Keying on bare verbs instead meant "how far we've come" ran the depth lens and
  "read the room" ran the document lens.
- **Calm.** Hysteresis holds a fresh decision through a debounce window, so a
  glance wandering across a page doesn't flip lenses. Veiled ⇒ nothing.

The candidate lenses today: Person (a face → Social Lens), Scholar (answer /
form / plain-words), TasteLens (a shelf or menu → the pick), Rosetta (foreign
text → translate), and Juno (an object, the sky, or a weak fallback to name
what's here). The live path — the phone in the browser — runs its own set, since
it may only bid lenses that host can actually execute: Read, Math, TasteLens,
Rosetta, Sky, Depth, Segment and Juno. Person is deliberately absent there; every
face defers to the Social Lens, which is the only thing allowed to name anyone.
`find` is absent from both, because it needs the nouns you are hunting and no
bare frame supplies them — it becomes reachable the moment you say what you're
looking for. The chooser, when a look is genuinely ambiguous:

![GlanceChoiceCard — a pick runs the lens and teaches the arbiter](assets/cards/glance_choice.webp)

## Who gets to interrupt — the summary

| Signal | Veil down | Focus on | Normal |
|---|---|---|---|
| Urgent watch-out hark | silent | **speaks** | speaks |
| Normal hark | silent | held | speaks |
| Anticipation cards | silent | held | shown |
| Message pop-ups | silent | held | shown |
| Fact-check / answer-ahead / delivery reads | silent | held | shown (if enabled) |
| Live caption display | silent | hidden (ledger keeps) | shown |
| Things you ask for (recall, rewind, Juno) | recall of kept memories still answers | answered | answered |
