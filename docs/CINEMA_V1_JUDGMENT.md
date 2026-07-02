# Cinema v1 — Judgment

Phase 0 of Cinema v2. Every claim below is cited to a file and line on
`main` as of merge commit `4ecdfa7` (Halo Cinema v1) plus the rename
(`e90eb82`). This document is not a review of effort; it is a judgment of
the artifact. It was written after reading every file the v1 PR touched,
every doc it authored, its golden images, and the rest of the repository
end-to-end.

---

## Three things v1 got right

### 1. It stopped lying to the hardware

The material system is the first code in this repo that treats the 4bpp
indexed display as what it is instead of what Pillow pretends it is.
`palette.reserve_dynamic` / `set_dynamic_y` / `shift_dynamic`
(`halo-lua/display/palette.lua:80-135`) implement "opacity" as the only
thing the panel can actually do — YCbCr reassignment of a reserved slot —
and kill list #8 deleted the `ghost_white = 0x08FFFFFF` pseudo-alpha hack
outright (`docs/HALO_CINEMA_V1.md:288-290`). The slot-aliasing trick —
prism fringes reuse dream drift slots 3/4 because card crossfades and
dream mode are mutually exclusive (`halo-lua/display/materials.lua:55-58`)
— is real systems thinking under a 6-slot budget. And the systemic
RGB-canvas alpha fix (`host-python/src/dreamlayer/hud/renderer.py:337-343`,
documented in `docs/HALO_CINEMA_V1_REVIEW.md:10-23`) proves the
Air/Ghost/Solid contract catches exactly the class of "material
dishonesty" it was designed to catch. This foundation survives v2 intact.

### 2. Where it replaced decoration, it replaced it with information

The two best moments in v1 are the two places motion became measurement.
The Confidence Halo encodes confidence twice — radius = 24 + conf×40,
sweep = conf×360° (`halo-lua/display/transitions.lua:190-199`,
`halo-lua/display/animations.lua:101-104`) — replacing a breathe pulse
that carried nothing (kill list #3, `docs/HALO_CINEMA_V1.md:276-277`).
The Memory Comet's entry angle encodes recency at 30°/week
(`halo-lua/display/transitions.lua:243-247`), and its `reduce_motion`
variant preserves the *reading* as a static rim tick at the same angle
(`transitions.lua:268-277`) — the accessibility contract preserved the
information, not just suppressed the motion. That principle — every
`reduce_motion` branch must keep the datum — is v1's single best law and
v2 keeps it as a constitutional rule.

### 3. It argued with itself in writing, and the arguments were real

The kill list gives mechanical reasons, not taste reasons: the 0.94
scale-fade died because "scaling vector line-art by 6% at 256px just
wobbles 1px lines" (`docs/HALO_CINEMA_V1.md:270-272`), and the renderer
carries the scar tissue as a comment (`halo-lua/display/renderer.lua:852`:
`sc = 1.0 -- kill list #1`). The risks doc names the palette-slot
contention hole with the precision of someone who expects to be wrong in
public — a `dream_exit` arriving mid-crossfade repaints a fringe slot
during the most visible moment on glass
(`docs/HALO_CINEMA_V1_RISKS.md:13-33`). And it flagged
`confidence_high = 0xAA00FF` as a founder-taste question instead of
recoloring unilaterally (`HALO_CINEMA_V1_RISKS.md:88-93`). The culture is
right. The execution gaps below are therefore not process failures — they
are imagination failures, which is worse and more fixable.

---

## Three things v1 got wrong

### 1. The vision-review loop certified black frames as "passed"

`assets/hud/samples/commitment_drift.png` and
`assets/hud/samples/time_scrub_node.png` are committed golden images that
are **one hundred percent black discs**. Open them. Nothing is there.

Root cause: `hud/cards.py` emits samples typed `CommitmentDriftCard`
(`cards.py:470`), `TimeScrubNodeCard` (`cards.py:503`) and
`DeviationAlertCard` (`cards.py:531`), but the Python `CardRenderer`
dispatch table (`host-python/src/dreamlayer/hud/renderer.py:344-360`) has
no entries for any of them; `render()` silently falls through
(`renderer.py:361-363`) and saves an empty circle. The v1 review doc then
wrote that these exact cards "passed inspection after the systemic alpha
fix with no card-specific patches"
(`docs/HALO_CINEMA_V1_REVIEW.md:118-125`). A review loop that looks at a
black disc and writes "passed" is not a review loop; it is a checklist
with pictures. Worse, `golden_images.py` now diffs black against black in
CI forever (`hud/golden_images.py:55-80` includes `commitment_drift` and
`time_scrub_node` in `DEFAULT_CARD_KEYS`), so the pipeline *certifies*
the blindness. And worst: the device renderer has full, working draw
functions for all three cards
(`halo-lua/display/renderer.lua:787-789`), so the committed goldens
actively misrepresent what the device shows — a direct violation of the
repo's own triple-mirror doctrine, "fix the divergent side, never fork"
(`phone-app/src/ui/components/CardPreview.tsx:4-8`).

v2's golden pass (Phase 5) treats "a pass found nothing" as a claim that
must itself be proven, and its first regression test asserts that no
golden in the suite is an empty frame.

### 2. Six signatures, one sentence: everything is a notification arriving in a void

Read the signature table and notice what every entry has in common:
`iris`, `ghost_wake`, `ripple`, `comet` are ENTER effects, `prism` is a
crossfade, `halo` is a hold ornament
(`halo-lua/display/transitions.lua:86-91`,
`halo-lua/display/renderer.lua:800-809`). All six answer the same
question — *how does a card arrive or leave* — asked at dead center
(`CX,CY = 128,128`, `renderer.lua:197`). None of them answer the question
a person wearing glasses sixteen hours a day actually lives inside:
**what is the HUD when nothing is arriving?**

v1's answer is either the ReadyCard — an abstract hex-and-orbit glyph
that encodes nothing (`renderer.lua:204-232`): not the time, not memory
state, not a single fact — or Dream Mode's ambient field, whose Air tier
is *defined* as "never information-bearing"
(`halo-lua/display/materials.lua:6-8`, `docs/HALO_CINEMA_V1.md:213`).
Meanwhile the host is sitting on continuous state that begs to be seen:
`CommitmentDriftEngine.all_records()` exposes the full decaying
commitment set — every open promise with a live decay position on a
five-state ladder, blooming→shattered
(`host-python/src/dreamlayer/orchestrator/commitment_drift.py:115-117`,
ladder at `:7-12`). **No renderer anywhere calls it.** The only consumer
of drift state is the one-shot alert card that fires when a promise is
already cracking (`orchestrator/orchestrator.py:198-213`). The ring buffer is a
time-ordered stream of everything the glasses remember
(`memory/ring_buffer.py:44-54`); it is rendered only as one-shot cards
that `DISMISS_MS` annihilates after 3.5 seconds
(`halo-lua/display/animations.lua:59-72`). Cinema's stated promise was
motion as meaning. v1 delivered meaning that lasts 280 milliseconds and
then a black screen.

### 3. The Truth Lens gauge is a dashboard wearing a cinema costume

Nine concentric rings at 4px pitch, one per pipeline stage — face, AU,
voice, prosody, linguistic, narrative, fusion, aggregate, verdict
(`halo-lua/display/renderer.lua:709-764`). On glass, ring identity is
purely positional and unlabeled: which ring is "prosody"? The wearer
cannot know without a manual, and 4px of radial pitch is sub-glanceable
at eyewear focus depth. Look at the committed golden
(`assets/hud/samples/truth_gauge.png`): what survives the eye is "red
means bad and there are a lot of rings." The per-stage evidence the nine
channels exist to carry does not reach the wearer — which fails the
card's *own* justification under "every visual choice carries
information," and fails the product spec directly: "glanceable in under
2 seconds," "no dense dashboards in-eye"
(`docs/PRODUCT_SPEC.md:14,34`). The tell that the altitude is wrong: v1's
own review had to push the rings outward *and* slap a black backing
capsule behind the verdict so the gauge would stop attacking its own
headline (`docs/HALO_CINEMA_V1_REVIEW.md:27-35`,
`renderer.lua:752-756`) — two patches treating symptoms of one disease.
PersonContext v2 has a milder case of the same thing: a 12-segment crown
with three segments amputated to clear the text it was striking through
(`renderer.lua:398`, `HALO_CINEMA_V1_REVIEW.md:45-48`). And
`confidence_high = 0xAA00FF` (`halo-lua/display/palette.lua:45`) — the
violet that every document agrees is off-family — is still shipping in
every high-confidence artifact.

---

## The one thing v1 didn't attempt

**Persistence.** v1 never asked where a memory *lives* on the display
when it isn't being announced.

There is no spatial model. No place where "now" is. No place where "this
morning" is. No place a decaying promise sits while it decays. Every
piece of information materializes at (128,128), performs its signature,
and is annihilated on a timer — existence is a 3.5-second event, not a
state. The wearer can never learn the display's geography because it has
none: yesterday's answer and this morning's answer appear in the same
pixels and vanish the same way.

The bitter part is that v1 already built the orphaned fragments of the
answer. The Memory Comet maps **time to angle** — 12 o'clock = today,
+30° per week (`transitions.lua:243-247`) — but only for the 280ms of the
flight, after which the mapping is discarded. Commitment drift computes a
continuous decay position for every open promise
(`commitment_drift.py:83-108`) that no pixel ever shows between alert
cards. The ring buffer keeps the day in order (`ring_buffer.py:44-48`)
and Time-Scrub even gives it a cursor (`time_scrub.py:47-79`) — rendered
as disconnected one-shot cards through a renderer that, per Wrong #1,
draws them as blackness.

A better version makes the HUD a *place*: a stable geography where
memories, promises, and people hold persistent positions the wearer's
peripheral vision learns within a day — and where "arrival" is not a
materialization at center stage but a movement *inward from where the
thing already lived*. Cards stop being the ontology and become a
behavior: the moment of focus in a field that persists.

That is where v2 begins.
