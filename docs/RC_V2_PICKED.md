# Reality Compiler v2 — Phase 4: The Pick

**Shipped: Rehearsal.** Loom and Echo become explicit follow-ups with revival
conditions below.

---

## The argument

All three survivors stand on the same substrate — the **Figment**: a total,
statically-budgeted, signable scene-machine interpreted by a fixed on-device
stage. That substrate is what satisfies the constraint envelope, and it ships
regardless of the pick. The pick is about the *authoring surface*, so the
question is: which surface is the leap?

**Loom is the safest of the three, which is why it loses.** It is genuinely
good — the untieable-mistake property is the cleanest safety-UX fusion here,
and it composes further than the others. But be honest about the demo: a
person dragging strands through knots on a phone is, to a smart friend, a
beautiful node editor. "Cool, that's a nicer template picker" is exactly the
sentence the brief forbids, and a braid UI is imaginable on a keynote slide
today. Loom is the step; the brief demands the leap. (Per the brief's own
instruction: first instinct was to pick it; overridden.)

**Echo is the most magical long-term and cannot lead.** Its cold-start is
fatal as a primary surface — for two weeks the product does nothing, and when
it finally speaks, the user has authored nothing and *feels* nothing of the
founder's north star ("**I** programmed my glasses"). Echo also needs
something to notice — a population of authored behaviors — which presupposes
another surface. It is the perfect second act.

**Rehearsal is the leap, on four grounds:**

1. **It answers the wearable question natively.** The brief invited us to
   reject v1's assumption that plain-English is the right input surface. It
   isn't — describing behavior in prose is a desktop habit. On glasses, the
   richest channel the user owns is *their own conduct in time*, and the
   display where behavior will live is the same display where it can be
   previewed. Perform-then-watch is the only surface among the eight that
   could not exist on any other device. That's what "right for a wearable AR
   HUD specifically" means.
2. **It hits the taste bar on sight.** The demo is: a person taps twice, says
   "rolling — three minutes… last ten seconds, pulse… again… done," watches a
   six-second folded replay, nods — and their glasses are reprogrammed.
   "Wait, do it again, how did you do that" is the *literal expected
   reaction*, because the mechanism (time-folding + inference + instant
   folded playback) is invisible.
3. **Failures teach by re-performance.** Error handling in every other
   paradigm eventually explains something *about the system*. Rehearsal's
   corrections stay in the user's own medium — re-do beat 3 — which is the
   strongest version of "failures are teachable" on the table.
4. **It subsumes the losers gracefully.** Séance's preview-disambiguation
   lives on as the run-through; Semaphore's gestures survive as beats with
   the grammar deleted; Clockface's winding is an optional duration input;
   Echo rides on Rehearsal's vault and history as a feature (pattern memory)
   before it graduates to a paradigm.

The risk accepted knowingly: inference can misread a performance. The
mitigation is structural — the run-through forces every reading to be watched
before it can be kept, so a misreading costs one re-performed beat, never a
deployed surprise.

## What this makes obsolete

v1's plain-English input becomes a **compatibility surface, not the product**.
Deprecation path: `compile_text()` keeps accepting v1 phrasings (it reuses
the v1 parser and lifts the result to a Figment), ships marked deprecated in
docs, emits no new capability, and is removed when the Repertoire can
re-instantiate all of a user's stored behaviors — the stored Figments, not
the phrases, are the durable objects. v1's *codegen* path (string-templated
Lua shipped as code) is obsolete immediately for new behaviors: everything
new travels as data to the fixed stage.

## The two follow-ups, with revival conditions

- **Loom** revives as the *power view* the moment users ask to see or edit a
  figment structurally — every Figment already renders as a braid, so Loom is
  a view-layer PR, not a compiler PR. Trigger: first user request to combine
  three or more behaviors, or to edit a beat's parameters numerically.
- **Echo** revives once two things exist: ≥2 weeks of per-figment performance
  history in vaults (Rehearsal writes it from day one) and the quiet-moment
  heuristics from the orchestrator. Trigger: median user has ≥3 vaulted
  figments; ship as proposals feeding *into* Rehearsal's keep/correct loop.
