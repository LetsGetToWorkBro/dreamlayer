# Reality Compiler v2 — Phase 7: Adversarial Pass

Three sections: malicious smuggling, naive self-harm, competitive copying.
Every defense claim below is either enforced in code (cited) or tested
(`src/dreamlayer/tests/`), except where explicitly marked as roadmap.

---

## A. Five ways a malicious user tries to smuggle unsafe behavior

### A1. Speak code into the machine
*"Rehearse. 'require os dot execute rm dash rf'…"*
**Defeated by vocabulary.** The rehearsal grammar (`rehearsal.parse_utterance`)
is closed: utterances that match nothing become *label text*, rendered as
inert characters. There is no eval anywhere in the pipeline, and the Figment
IR has no node type that names a function, a module, or a path — the sentence
compiles to a caption. Tested:
`test_rc2_rehearsal.py::TestGrammar::test_unknown_words_become_labels_never_commands`.

### A2. Forge a figment file into the vault
Attacker drops a hand-crafted `<id>.json` with an 86400-second blank scene
(display squatter) or edits a kept figment's duration on disk.
**Defeated by the signature gate.** Vault entries are HMAC-SHA256-signed by
the per-install session key at keep-time; `Vault.load()` re-verifies and a
tampered entry raises and is excluded from every listing; `StageDeployer`
refuses anything that fails verification. A forged file without the key
cannot produce a valid signature. Tested:
`test_rc2_vault.py::TestVault::test_tampered_file_never_surfaces`,
`test_rc2_deploy.py::TestDeployGates::test_refuses_tampered`.

### A3. Sign first, mutate later (TOCTOU on the budget proof)
Attacker with filesystem access signs a *legal* figment, then swaps illegal
scene data under the same id, or replays a legitimately-signed-but-
later-revoked figment.
**Defeated twice.** (1) The signature covers the canonical JSON of the whole
machine — any mutation invalidates it. (2) The deployer *re-runs the budget
verifier at deploy time* and consults the durable revocation list, so even a
correctly-signed entry must re-prove its budgets on every deploy, and a
revoked id stays dead ("revive by re-keeping" is blocked because the
revocation list is keyed by id, not by file presence). Tested:
`test_rc2_deploy.py::TestDeployGates::test_reverifies_budgets_at_deploy`,
`test_rc2_vault.py::TestVault::test_revocation_is_durable`.

### A4. Bypass the phone entirely — raw BLE injection
Attacker replays/synthesizes `figment_put` + `figment_swap` envelopes at the
glasses with a hostile figment (strobe, 10 kB lines, 500 scenes).
**Defeated by the stage's own clamps.** `figment_stage.lua` re-enforces the
envelope on-device: structural caps at load (`_clamp_ok` refuses >32 scenes,
>5 lines, sub-breath durations, pulse >4 Hz — nack'd, never stored), text
truncation at 24 chars on every render, counter saturation on every op, and
the emit token bucket (burst 5, refill 1/s) on every send. The device never
trusts the host's proof; it re-derives the parts that protect *it*. Tested:
`test_rc2_lua_stage.py::TestLifecycle::test_over_budget_pulse_refused_on_device`,
`::TestParityWithPython::test_emit_token_bucket_parity`.
*Roadmap:* BLE-level pairing/encryption is inherited from the Halo link
layer; adding a host-nonce challenge to `figment_swap` is a cheap hardening
step if the link layer proves weak.

### A5. Death by a thousand legal figments — resource exhaustion
Attacker scripts 10,000 keep/deploy cycles (vault bloat, device RAM
exhaustion via `figment_put` spam) or one legal figment that emits exactly
at budget forever to drain battery.
**Defeated by bounded storage and honest budgets.** On-device, `_stored` is
replaced per-id (a re-put overwrites, never accumulates) and a put is
≤ MAX_SCENES × bounded-scene bytes; the sustained emit budget (1/s) is by
construction the *acceptable* battery cost — an attacker at budget is a user
at budget. Vault-side, entries are one small JSON per id and revocation
compacts to an id list.
*Roadmap:* a vault quota (count + bytes) with LRU prompts belongs in the
phone app before public beta.

---

## B. Five ways a naive user could crash their session — and why they can't

### B1. "Strobe thirty times a second"
The grammar *represents* the request honestly (rate 30 Hz); the verifier
rejects it (`pulse_rate` > 4 Hz) and the teach card explains in beats and
offers "pulse". The display never sees it. Tested:
`test_rc2_e2e.py::test_blind_handoff_failure_path_is_teachable`.

### B2. The zero-length loop
"One second… no wait — again — again": a cycle of timed scenes that would
spin the scene graph. Unrepresentable: every timed exit costs ≥ 0.5 s
(`MIN_SCENE_SEC`, enforced in verify and re-clamped on device), and cycles
through event edges cost an external event each. The `livelock` check runs
anyway as defense in depth. Tested:
`test_rc2_budgets.py::TestTemporal::test_sub_breath_duration_rejected`.

### B3. Tap-mashing a counter or an emitting trigger
200 taps in ten seconds on a points marker that sends to the phone.
Counters saturate at their declared bounds (no overflow, no giant render
strings); emits hit the token bucket and drop silently past burst-5 —
the round count on screen stays right, the radio stays quiet. Tested:
`test_rc2_interpreter.py::TestCountersAndGuards::test_counters_saturate`,
`::TestEmitBudget::test_event_flood_clamped_by_token_bucket`.

### B4. The forever-timer typo
"Three hundred minutes" instead of "three minutes" — a five-hour squatter
on the display. Two defenses: the run-through *shows* the 5:00:00 countdown
before keep (the misreading is watched, not discovered next Tuesday), and
every figment remains interruptible — revoke from the phone or the armed
trigger/until-exit ends it; hot-swap replaces it without a reboot. Tested:
`test_rc2_interpreter.py::TestHotSwapRevoke`.

### B5. Authoring over a live behavior
User rehearses while their round timer runs — does the half-formed rehearsal
clobber the deployed figment? No: rehearsal happens entirely host-side
(beats → inference → preview) and nothing reaches the device until an
explicit keep **and** deploy; the stage swaps figments only on
`figment_swap`, atomically, between ticks. Tested:
`test_rc2_lua_stage.py::TestLifecycle::test_hot_swap_replaces_running`.

---

## C. Five ways a competitor copies this in three months — and the moat

### C1. "We added record-a-macro to our glasses"
Naive demonstration capture without time-folding: recording a 3-minute timer
takes 3 minutes, so their demo is a 10-second toy behavior. The fold — spoken
durations advancing a rehearsal clock — is the non-obvious piece, and by the
time they discover it matters, DreamLayer's fold grammar has months of
real-user vocabulary tuning. **Moat: the corpus of folded-speech patterns,
which only accumulates from real rehearsals.**

### C2. "We shipped an LLM that writes glass apps"
The keynote-friendly copy. It fails the constraint envelope in public:
generated code needs sandboxing they haven't built, cloud dependency breaks
airplane-mode authoring, and one viral crash ("my glasses locked up mid-jog")
poisons the category. **Moat: totality — the Figment IR's
no-crash-by-construction claim is a *provable* marketing sentence copiers
who ship codegen cannot say.**

### C3. Clone the Figment format itself
It's readable JSON; a competitor reimplements the machine. Fine — the format
is the least of it. The compounding assets are above and below it: the
choreographer's inference rules (trace → machine) and the vault's
performance history that feeds pattern memory (the Echo follow-up learns
*your Tuesdays*). **Moat: switching cost of an accumulated, locally-owned
repertoire + history that, by the privacy model, literally cannot be
migrated by a third party.**

### C4. Out-spend on the authoring UI (a slicker Loom)
A big player ships a beautiful node canvas. That competes with the follow-up,
not the paradigm: canvas authoring happens *on the phone about the glasses*,
Rehearsal happens *in the glasses' own theatre* — perform-and-watch needs
control of the HUD loop end to end, which platform players license but don't
inhabit. **Moat: vertical integration of stage + preview + runtime on the
same display, plus first-mover claim on "rehearse" as the verb.**

### C5. Poach the safety story ("we have budgets too")
Budgets are copyable; the *teachability* binding is harder: DreamLayer's
violations carry beat provenance from inference through verification to the
HUD card ("your beat 3 asks…"), which requires the authoring trace and the
proof system to share a spine. A bolted-on linter says "error: rate limit
exceeded". **Moat: the beat-provenance thread through the whole stack —
an architecture choice copiers must rebuild from zero, and the single
biggest reason users trust the system enough to keep authoring.**

---

## D. The caps are *proven*, not just tested

Every argument above leans on a handful of hard runtime caps: a counter
never leaves its declared `[lo, hi]`; the emit token bucket never floods
BLE (ceiling) nor goes negative (floor); no display line overruns the
character budget; the named-slot dict never exceeds `MAX_SLOTS`. Unit tests
show these hold *on the examples we thought of*. That is not the same as
holding *for every input an adversary can reach* — and A4/A5/B3 are exactly
"feed the interpreter an input we didn't think of."

So the caps are lifted into pure functions carrying PEP-316 contracts
(`reality_compiler/v2/contracts.py`: `saturate`, `spend_token`,
`refill_tokens`, `clamp_text`, `accept_slot`). CrossHair symbolically
executes each one over Z3 and **proves the postcondition holds for every
input in the symbolic domain** — or returns a concrete counterexample. The
interpreter imports and calls these exact functions (not a copy), and a
wiring test pins the call sites, so the proof guards the real code path.

- Discrete-logic caps (`saturate`, `spend_token`, `accept_slot`) get a full
  CONFIRMED — an actual proof over all integers/booleans.
- Float and symbolic-string caps (`refill_tokens`, `clamp_text`) live in SMT
  theories CrossHair can't always fully close, so the honest claim there is
  an exhaustive *refutation search that finds no violating input*.

Tested: `test_contracts_crosshair.py` (proofs + a deliberately-broken
contract the search must catch, so the suite can't pass vacuously). Runs in
CI via the `verify` extra; skipped cleanly where `crosshair-tool` is absent.

**And the tests are mutation-tested.** A proof shows a property holds; it does
not show the *tests* would notice if the code broke. So mutmut mutates
`contracts.py` — flips every operator, boundary, and constant in the caps — and
confirms the suite kills every mutant. This surfaced a real gap: CrossHair is
blind under mutmut (it swaps the body behind a dispatcher CrossHair's source
read can't see), so the proofs killed nothing — only example-based tests do.
`test_contracts_unit.py` adds boundary tests (spend at exactly one token, each
counter op, the accept-slot truth table, refill direction) that take the score
to **34/34 killed**. The proofs cover ∀-inputs; the boundary tests pin the exact
edges; together they are belt and suspenders. Enforced on demand by
`.github/workflows/mutation.yml` (config in `pyproject.toml [tool.mutmut]`,
`mutation` extra) — a surviving mutant fails the job.
