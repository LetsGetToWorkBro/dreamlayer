# Reality Compiler v2 — Phase 8: Risks

Honest ledger. Each risk: likelihood × impact, what this PR does about it,
and the tripwire that says it's materializing.

## R1 — Inference misreads performances (the paradigm risk)
**High likelihood, medium impact.** The choreographer is deliberately
conservative pattern inference, not magic; real speech is messier than the
closed grammar ("uh, make it like three-ish minutes?"). Mitigated
structurally: every reading is watched in the run-through before it can be
kept, corrections cost one re-performed beat, and unmatched words degrade to
labels (never wrong machines). **Tripwire:** correction rate per kept figment
> 1.5 in dogfooding → grow the grammar corpus before touching the inference
rules.

## R2 — The closed grammar feels closed
**Medium likelihood, medium impact.** Users will say things the grammar
doesn't hold ("ping my coach when I gas out"). v1 had the same ceiling with
worse failure (ValueError); v2 fails to a teach card with an example. The
optional cloud LLM as *pre-labeler into the same closed beat vocabulary*
(never as codegen) is the designed relief valve and is not in this PR.
**Tripwire:** >20 % of rehearsals end in `label`-only traces.

## R3 — Speech input in loud places
**High likelihood, low impact.** Gyms are loud; folded durations are spoken.
The beat model already accepts non-speech alternates (dwell beats, and the
Clockface-derived head-roll winding is specced as an optional duration
input); the phone Score view can retype a label after the fact without
re-performing. **Tripwire:** rehearsal abandon rate at the gym vs. at home.

## R4 — Figment IR expressiveness ceiling
**Certain, by design.** Totality means some legitimate wishes are
unrepresentable (arbitrary arithmetic, free-form animation, cross-figment
messaging). That ceiling is the safety guarantee. The pressure release is
deliberate: new *scene capabilities* (whitelisted, budgeted node types) added
by DreamLayer engineers, never user-defined ops. **Tripwire:** teach cards of
kind `CAN'T STAGE THAT` clustering around one missing capability.

## R5 — Two interpreters, one semantics
**Medium likelihood, high impact if drifting.** interpreter.py and
figment_stage.lua must agree forever; a divergence means the preview lies.
Held by the parity suite (`test_rc2_lua_stage.py`) driving both from the
same figments and asserting identical renders/emits/termination — CI now
runs it (lupa added to dev deps). **Tripwire:** any parity test touched
without a matching change in both files; review rule: the two files change
in the same commit or not at all.

## R6 — On-device stage on real hardware
**Unknown likelihood, high impact.** The stage is exercised under lupa
(Lua 5.5) and the emulator, not yet on Halo silicon: real display latency,
BLE MTU fragmentation of large figments (~4–8 kB), and tick jitter are
unmeasured. The transport reuses the existing length-framed protocol that
the current bridge already runs on hardware, which bounds the surprise.
**Tripwire:** first-device checklist in FIRST_DEVICE_TEST_PLAN.md gains an
RC-v2 section before any hardware demo.

## R7 — Session-key custody
**Low likelihood, medium impact.** The HMAC session key lives 0600 in the
vault dir; a rooted phone can read it and sign at will. Accepted for this
phase: the key gates *deployment to your own glasses*, not a remote
privilege. Sharing figments across installs (Grimoire follow-up) upgrades
signing to asymmetric keys with provenance — explicitly out of scope here.
**Tripwire:** the export feature grows a "share" transport of any kind.

## R8 — Backward-compat is semantic, not byte-identical
**Certain, disclosed.** v1 templates now run as lifted Figments on the
stage, not as generated Lua strings; rendering differs in pixels (cards vs.
raw `frame.display.text`) while behavior (durations, triggers, phases,
counts) is pinned by `test_rc2_compat.py::TestSemanticEquivalence`. The v1
pipeline itself remains in-tree and untouched, and all v1 tests pass
unchanged, so a byte-identical escape hatch exists during the deprecation
window. **Tripwire:** any v1 test modified to accommodate v2.

## R9 — Scope: the demo proves the loop, not the polish
**Certain, disclosed.** Voice capture, on-stage HUD recording UI, and the
live phone bridge for the Rehearsal screen are stubbed at the edges: the
session API is driven programmatically in the demo, and rehearsal.tsx shows
the visual language with placeholder session state. The paradigm's spine —
beats → inference → proof → sign → hot-swap → stage — is real end to end.
Per the brief (Rule 2), the slice was cut without diluting the pitch;
followups: mic beat capture, live Score streaming, head-roll winding.

## R10 — The pick itself
**The bet.** Rehearsal could be wrong — users might prefer describing to
performing. The two survivors are staged as revivals with explicit
conditions (docs/RC_V2_PICKED.md): Loom is a view-layer PR on the same
Figments, Echo feeds on the performance history this PR already writes.
The substrate survives any surface verdict. **Tripwire:** blind-handoff
sessions (the paradigm's one test, run with humans) failing the 60-second
bar for two consecutive cohorts.
