# Reality Compiler v2 — Phase 1: Eight Paradigms

The question: **what should the Reality Compiler be**, given that v1 — a
pattern-matcher over 15 hand-coded templates — proves the concept and then
caps out exactly where the pattern-matcher stops.

Each concept below is a different answer, not a variation. The shared test
request used in every example: *"keep a 3-minute timer going during my rolls
with a 10-second pulse at the end."*

---

## 1. Rehearsal

**Pitch:** You don't describe the behavior — you *perform it once*, and the
glasses learn the choreography.

**Authoring.** The user puts Halo into rehearsal mode (long-press, "rehearse").
The HUD becomes an empty stage. The user then acts out one round of the
behavior as if it already existed: they tap the button where the trigger
should be, *speak* stretches of time instead of living them ("three minutes
pass"), and mark moments that matter ("pulse here", "warn me", "then it
repeats"). Durations are *folded* — saying "three minutes" advances the
rehearsal clock by 180 seconds in one beat, so rehearsing a 3-minute timer
takes about fifteen seconds. When the user says "done", the compiler plays the
whole behavior back, time-compressed, on the HUD: *"Here's what I learned —
watch."* The user accepts, or re-performs just the beat that came out wrong.

**Compilation.** Beat trace → inferred behavior machine. The recorded beats
(taps, folded durations, spoken marks, repetitions) are generalized into a
**Figment**: a finite, declarative scene-machine — scenes, timed exits, event
exits, bounded counters — whose worst-case cost is computable before anything
ships. Compilation is *inference over a performance*, and the compiled object
is data interpreted by a fixed on-device runtime, never code.

**Why a wearable.** On a desktop you have a keyboard, so a language is cheap.
On glasses the only rich input channel is *the user's own behavior in time* —
taps, dwell, speech, gesture. Rehearsal makes that channel the programming
language. And the output surface (the HUD) doubles as the debugger: what you
authored plays back in the exact place it will live. No other device category
lets the program be performed and previewed in the same theatre.

**Example.** User: "rehearse." Stage opens. User taps twice — *[trigger
learned: double-tap]*. Says "rolling — three minutes" — *[scene ROLLING,
180 s, countdown]*. Says "last ten seconds, pulse" — *[pulse spec: final 10 s,
attention color, 2 Hz breathe]*. Says "then it starts again" — *[cycle back]*.
Says "done." HUD replays the whole round in six seconds, folded. User: "keep
it." Signed, stored, deployed. Total authoring time: ~20 seconds.

---

## 2. Loom

**Pitch:** Behaviors are *strands* — a time strand, an event strand, a display
strand — and you braid them on the phone with your thumbs.

**Authoring.** The phone shows a vertical loom. Strands hang from anchors:
`double-tap`, `every second`, `battery`, `coach byte`. The user drags a strand
down through *knots* — `count down 3:00`, `show big number`, `pulse coral` —
and the braid *is* the behavior. Crossing two strands merges them (a tap
strand crossing a timer strand becomes start/stop). No node-and-wire graph
jargon: strands have physics, snap points, and a visible top-to-bottom flow of
time. A live Halo mirror at the top of the screen runs the braid as you braid.

**Compilation.** The braid is already a dataflow graph with a fixed vocabulary
of knots; compilation flattens it into the same bounded scene-machine
(Figment) and proves budgets over it. Illegal braids are impossible to tie —
knots that would exceed a budget refuse to snap, with a haptic "nope."

**Why a wearable.** In-eye authoring of structure is hopeless (HUD rule: one
thought at a time), but everyone with glasses carries the perfect structural
editor — the phone. Loom accepts the phone/HUD split: shape on the phone,
feel it in the eye instantly.

**Example.** User drags the `double-tap` anchor, pulls the strand through
`count down 3:00`, then through `final 10 s → pulse coral`, then loops the
strand end back to its own start knot ("braid loops"). The mirror shows the
countdown running. Deploy is a flick upward — the braid flies to the glasses.

---

## 3. Echo

**Pitch:** You never author anything — the glasses notice what you keep doing
and offer to keep doing it for you.

**Authoring.** There is no authoring session. Echo watches *manual* usage
patterns on the device: every Tuesday at 18:00 the user opens a stopwatch,
resets it every ~3 minutes, about ten times. After the second Tuesday, a card
appears: *"You run 3-minute rounds on Tuesdays. Want me to run them?"* Single
tap: yes. The inferred behavior is materialized, named ("Tuesday rounds"),
signed, and scheduled. Corrections happen the same way — if the user keeps
overriding the pulse at 10 s to 15 s, Echo offers the amendment.

**Compilation.** Longitudinal trace mining → recurring-pattern hypothesis →
the same bounded Figment. Compilation is *statistics first, machine second*:
the pattern detector proposes, the standard verifier proves budgets, and the
user's single tap is the only syntax in the whole system.

**Why a wearable.** Glasses see every repetition of your day — no other
device has the vantage point to *observe* the program you already run by
hand. The wearable's weakness (no input surface) becomes irrelevant because
input is your life.

**Example.** The user manually runs round timers during Tuesday rolls for two
weeks. Echo proposes: "3-minute rounds, pulse near the end, Tuesdays around
6pm?" Tap. From then on, arriving at the gym on Tuesday arms the timer;
double-tap starts round one.

---

## 4. Séance

**Pitch:** A conversation with the compiler where every answer is a living
preview, not a sentence.

**Authoring.** The user speaks: "keep a timer going during my rolls." The
compiler doesn't reply in words — it *conjures* the behavior immediately on
the HUD with its best-guess parameters and animates it, then asks exactly one
question at a time by showing two candidate previews side by side ("this
end… or this end?" — pulse vs. flash), which the user picks between by tilting
left or right. Iteration converges in three or four exchanges; the dialogue
history *is* the spec.

**Compilation.** Utterance → candidate Figments → interactive disambiguation
→ chosen Figment. The LLM (when present) only ever emits *parameter choices
inside the fixed Figment vocabulary*, never code; offline, a smaller grammar
does the same with fewer candidates.

**Why a wearable.** Voice in, glance out is the native wearable duplex; a
dialogue that answers with renderings uses both halves at full bandwidth.

**Example.** "Keep a 3-minute timer going during my rolls." HUD immediately
runs a folded 3:00 countdown. "End like this — or this?" (pulse | flash);
user tilts toward pulse. "Rounds keep coming?" — nod. Deployed.

---

## 5. Clockface

**Pitch:** Every behavior is a little mechanical instrument you *wind*, not a
program you write.

**Authoring.** Behaviors present as instruments with physical affordances:
timers are crowns you wind (head-roll winds 30 s per degree cluster),
counters are ratchets, reminders are music-box drums with pins. The user
assembles an instrument on the phone from a small case of movements, then
winds and pins it wearing the glasses. The end-of-round pulse is a pin placed
10 s before the mainspring runs out.

**Compilation.** Instrument description (springs, pins, ratchets, escapements)
→ Figment. Mechanical semantics guarantee boundedness by metaphor: springs
run down, drums have finite pins, ratchets have finite teeth.

**Why a wearable.** Winding, tilting and tapping are gestures the head and
hands already know; mechanical metaphors survive tiny displays because
watchmakers solved glanceability 300 years ago.

**Example.** Pick "mainspring" movement, wind to 3:00 with two head-rolls,
place a coral pin at 0:10, close the case, name it "Rolls." Double-tap winds
it up again after each round.

---

## 6. Grimoire

**Pitch:** Authoring is *collecting and bending* — a deck of signed behavior
charms you remix, not a blank page.

**Authoring.** The phone holds a grimoire: every behavior anyone in your
circle has authored (and signed) appears as a charm card with three or four
*bendable* attributes exposed as sliders and toggles — never more. The user
finds "Round bell" in the deck, bends duration to 3:00 and the ending to
"pulse," and presses it onto the glasses. Creating a genuinely new charm is
the rare path (done via a companion flow); bending is the everyday act.

**Compilation.** Charm + bends → re-instantiated Figment, re-verified and
re-signed locally. Provenance travels with the charm; a bent charm cites its
ancestor.

**Why a wearable.** Wearables are social objects — behaviors spread the way
watch faces spread. The deck turns every user's authored figment into another
user's starting point, which is how a 15-template ceiling becomes a
thousand-charm commons.

**Example.** Search deck for "rounds." Bend: 3:00, pulse at 10 s, loops.
Press to deploy. Ten seconds, zero blank-page.

---

## 7. Semaphore

**Pitch:** A gestural composition language — short head-and-tap phrases that
compose primitives like words compose a sentence.

**Authoring.** The user learns a tiny movement vocabulary: tap = "beat",
double-tap = "begin/end", tilt-hold = "stretch time", nod = "yes/next",
shake = "undo". Behaviors are composed as *phrases*: begin — beat — stretch
(3 min) — beat (pulse) — begin (loop) — end. The HUD sketches each phrase
element as it lands, like a musician watching notation appear.

**Compilation.** Gesture phrase → parse tree over the primitive vocabulary →
Figment. The grammar is regular (no nesting), so parsing is total and every
phrase is compilable or immediately rejected with the offending gesture
highlighted.

**Why a wearable.** It's the only paradigm that needs *neither* phone nor
voice — composable in a silent, hands-busy environment (a mat, a kitchen, a
stage wing).

**Example.** Double-tap (begin), tilt-hold while the HUD counts up to 3:00,
tap (mark pulse), nod at "repeat?", double-tap (end). The phrase compiles as
you move.

---

## 8. Tidepool

**Pitch:** A handful of reactive cells — sensors flow in, glass flows out —
the spreadsheet reborn as four pools on a phone screen.

**Authoring.** The phone shows at most six *pools*. Each pool holds one value
and one rule for how it fills: `pool A ← seconds since double-tap`,
`pool B ← 180 − A`, `display ← B, big, center`, `tint ← coral when B < 10`.
Rules are chosen from menus, not typed. Everything recomputes live; the Halo
mirror shows the result while you author.

**Compilation.** The pool graph is an acyclic reactive network with a fixed
operator set; compilation topologically sorts it into per-tick update order
and emits a Figment whose tick rule evaluates the pools. Cycles can't be
expressed (a pool can't reference downstream pools), so termination is
structural.

**Why a wearable.** Continuous sensor→display bindings (battery, time, IMU)
are what a HUD is *for*; a reactive network states them directly instead of
encoding them in control flow.

**Example.** Four pools as above, plus `A resets on double-tap` and
`when B = 0 → B ← 180`. The mirror runs it; flick to deploy.

---

*Phase 2 culls five of these — see `RC_V2_KILLED.md`. Survivors are deepened
in `docs/rc_v2/`.*
