# Handoff — read this before touching anything

Working state as of 2026-07-29. Written for whoever picks this up next.

---

## The task in front of you

**Correct every lens and every HUD item, at minimum, plus capabilities.** The
owner asked for this explicitly and asked for it at AAA level: fully built,
tested, mutation-tested, merged.

### Where it stands

Three checkers now answer "is this reachable from the shipped Brain" instead of
anyone's memory. Run all three before believing any claim in this file:

```
python3 scripts/lens_reachability.py         # exits 1 while a lens is unloadable
python3 scripts/hud_reachability.py          # exits 1 while a card is unproducible
python3 scripts/capability_reachability.py   # diagnostic; always exits 0, see §4
```

| | done | open |
|---|---|---|
| **Lenses** | 25 of 28 loadable; the seven hosted ones are called, routed and on a phone screen; Scholar wired | Lucid Recall, Timbre (biometric — §1), Yesterlight |
| **HUD cards** | 24 of 24 have a real glass renderer; 6 have a Brain-side producer | **18 cards nothing in the Brain can produce** (§3) |
| **Capabilities** | 41 of 74 seams loadable; 13 unreachable by design, with reasons | **19 open questions** (§4) |

The single most important thing in this file, because it is the mistake that
keeps repeating: **`lens_reachability.py` reporting a lens as "reachable" is not
evidence it runs.** It says the code can be LOADED. Seven lenses were listed as
reachable for a whole release while nothing constructed one of them. The script
says so in its own header; believe the header, not the green line.

### Testing face recall end-to-end

**This section used to say "no consent flow exists to remove". That is stale —
one was added at `9f0f7c5`.** `face_live.CONSENT_VERSION` /`CONSENT_TEXT` and
`POST /dreamlayer/face/consent` are real, and `identify()`/`enrol()` refuse with
`no-consent` BEFORE the embedder is reached, so without acceptance no template
is computed at all. It is the WEARER's consent, accepted on a bystander's
behalf, and the text says so in those words.

What gates `identify()` is, in order: the Veil, the versioned consent, the
wearer's switch, the model, no face detected, no match — then either a match, or
`face_auto_enrol` storing the stranger, or `_discard`.

Full end-to-end test on a source checkout:

```
pip install -e ".[face]"                      # the model, opt-in by design
python -c "from insightface.app import FaceAnalysis; \
  FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'], \
  allowed_modules=['detection','recognition']).prepare(ctx_id=-1)"   # weights
export DL_FACE_AMBIENT=1                      # ambient; refused in release builds
curl -sX POST localhost:PORT/dreamlayer/config \
  -H "X-DreamLayer-Token: $TOK" -H 'Content-Type: application/json' \
  -d '{"face_recognition": true}'             # the wearer's switch
```

Then every path is exercisable: `POST /dreamlayer/face/enrol` with a name and a
base64 frame, `/identify` for match and no-match, `/forget`, `GET
/dreamlayer/face` for status, plus erase-everything and the retention sweep.

**Auto-enrol shipped, on the owner's explicit call** (`9f0f7c5`). Matching used
to be enrolment-only — the index held only people the wearer named, so a
stranger had nothing to match against. `face_auto_enrol` (default False) changes
that answer: a face matching nobody is STORED rather than discarded, including
bystanders who never agreed and cannot agree in the app. Unnamed identities age
out on the 90-day warm window; named ones are kept until erased.

Every claim this falsified was corrected in the same round (`8666a2e`, 23
confirmed-false sentences across `landing/privacy.html`, `landing/index.html`,
six gitbook pages and three `docs/` pages), and `test_advertised_claims.py` grew
from 9 tests to 16 to hold them. The consent text names biometric templates,
bystanders, BIPA and GDPR Art. 9 outright. **If you change the default, that
copy becomes false again** — the standing rule applies.

### The bar: 1:1 and reachable, no partial wiring

The owner's words: **"it needs to be 1:1 full functionality and reachable, no
shortcuts."** A slogan does not hold a bar, so here it is as eight checks. A
lens is DONE when all eight pass, and not before. "It imports now" is not done.
"There's a method for it" is not done.

1. **In the closure.** `python3 scripts/lens_reachability.py` does not list it
   as unreachable.
2. **Constructed Brain-side.** A host in `ai_brain/server/` builds it —
   `grep -rn "TheClass(" src/dreamlayer/ai_brain --include=*.py` returns a hit.
   Never by resurrecting the `Orchestrator`.
3. **Reachable by the phone.** A route in `_POST_ROUTES` / `_GET_ROUTES`, tested
   over a LIVE server, not just a Brain method. A capability with no route is
   invisible — this is the bug #542 shipped with and #543 shipped with, twice in
   a row, so check it twice.
4. **Fed real input.** The lens gets what the Orchestrator path gives it, not a
   stub, an empty collection, or a surrogate that technically satisfies the
   signature. THIS IS THE ONE THE OWNER IS WARNING ABOUT. A `ConsistencyEngine`
   over an empty ring answers "no contradiction" forever and looks like it
   works. If the real input does not exist Brain-side, BUILD IT (that is what
   the statement ring in `lens_hosts.py` is) or say plainly that the lens is
   blocked and why.
5. **Proven by behaviour, not construction.** A test that puts real state in and
   asserts the lens ANSWERS about it. `assert x is not None` and
   `assert ... or True` are not tests; an earlier draft of
   `test_brain_lens_hosts.py` had three of the latter and they would all have
   passed vacuously.
6. **Mutation-tested.** Break the wiring; the test must fail. Commit first, then
   mutate, then restore — a `git checkout --` during mutation testing has eaten
   uncommitted work in this repo twice now.
7. **Obeys the standing rules** if it stores anything: Veil-gated and
   fail-closed, swept by retention, reached by erase-everything. A new store
   that skips any of the three is how "nothing expires" and "erase everything"
   quietly stop being true.
8. **Claims moved with it.** If wiring it makes a sentence on `dreamlayer.app`
   or in `docs/gitbook/` true or false, fix it in the same change.

If a lens cannot pass all eight, do not half-wire it and move on. Leave it, and
write down which check it fails and what it is blocked on. A documented gap is
recoverable; a lens that looks wired and is not costs the next audit a day.

### 0. The seven hosted lenses (DONE — and it was worse than "no routes")

This section used to say the seven lenses in `lens_hosts.py` "load, they answer,
they are tested" and only lacked routes. **The first half was wrong**, and the
parity audit caught it: `brain.lenses()` had exactly ONE production call site —
`purge_memories()`, which nulls the set two lines later — so in a shipped build
no lens object was ever constructed at all. Importable-never-called is
`decisions/0001` verbatim, one layer up, and `scripts/lens_reachability.py`
listed all seven as "reachable" throughout, exactly as its own header warns it
would. **A clean reachability run is not evidence a lens executes.** Check 2 of
the bar below means CONSTRUCTED ON A PATH A USER REACHES, not "a constructor
exists somewhere".

Closed now: `EarHost.ingest_caption` feeds the ring through
`BrainLenses.ingest_utterance`, nine POST and six GET routes are registered, and
`phone-app/app/lenses.tsx` + `src/state/useLensStore.ts` are the surface. 40
tests in `test_brain_lens_wiring.py`, none of which touches a lens directly —
each drives the ear, a route, a spoken intent or a sweep and asserts the lens
moved. 21 mutants, all killed.

Six real defects fell out of doing it, listed here because each is a shape worth
recognising rather than a one-off:

| What | Why it was invisible |
|---|---|
| "hold that thought" returned `{"intent": "stasis_freeze"}` and the phone rendered the literal text `(stasis_freeze)` | 200 OK. A working-looking no-op, live in the shipped product |
| retention's statement-ring leg read `getattr(brain, "_lenses")` | None at every moment a sweep could observe it — the same bug in miniature |
| the sighting purge ASSIGNED `hot_purged` where it should have added | the ledger line disclosing an automatic deletion under-counted by exactly the statements taken |
| the 24 h ring purge deleted in-force commitments | their rows are cold-forever on disk and the drift lifetime is 48 h; fixed with `purge_before(keep_kinds=)` |
| erase-everything missed `vault/quest_log.json` | xp, streak and badges survived a wipe and a fresh lens set read them straight back |
| nothing emitted `quest_done`/`quest_rescue`/`streak` | all five quest achievements in `saga.py` were unlockable by nothing; the phone drew them permanently locked |

Still open on these seven: Commitment Drift reads `ring.latest(kind="task")`
only, so a `promise` row with a real due date is never tracked — that is the
Orchestrator's own design and changing it changes both surfaces, so it is
recorded rather than quietly altered. And Inner Weather has a route and a lens
but **no phone code posts `imu_delta`/`imu_pose`** — the store method exists,
the sensor feed does not.

### 1. The three lenses still unreachable

`scripts/lens_reachability.py` is the check — run it, it exits non-zero while
anything is unreachable. It reports **three** now: Scholar is wired (below) and
Puente is gone rather than excluded. Their constructor shapes, so you do not
have to re-derive them:

```
LucidRecall(social_lens, memory_index, privacy, classify_fn)   .query()
TimbreReactor(baselines, privacy, now_fn)          .tick()
YesterlightController(ledger, now_fn)              .tick()
```

- **Scholar — DONE.** Note the earlier advice here was wrong: `look_lens(frame,
  "doc")` is an OCR reader returning `{"text": …}`, but `read_fn(frame, prompt)`
  wants a MODEL REPLY TO A PROMPT. The right seam was `WorldLensHost._describe`,
  the same one `TasteLens` uses — the docstring on `backend.describe` says it
  outright ("the caller owns the prompt and parses the reply"). Wired at
  `world_lens.py`, routed as `POST /dreamlayer/scholar?mode=answer|form|explain`,
  and on the phone as a four-way mode strip on the Look screen (one photo, four
  questions). 11 tests, including one that asserts SCHOLAR'S OWN PROMPT reached
  the model — a route that sent the object-lens prompt would still return a
  parsed card and still look like it worked.
- **Lucid Recall** wants a `social_lens` and a `memory_index`. The Brain now has
  a real face-recall host (`brain.face_recall()`) and `brain.index`; check
  whether `LucidRecall` needs the full `SocialLens` surface or only `identify`,
  and adapt rather than constructing a second SocialLens.
- **Timbre is a BIOMETRIC lens and must be treated like faces were.** It takes
  voice `baselines` — voiceprints of known speakers. `voice_guard` already
  forbids voiceprinting anyone without consent, and `ear.py:127` records that
  nothing in this product ever populates `speaker`, deliberately. Do not quietly
  reverse that. It needs the #542 treatment: opt-in switch off by default, a
  consented enrolment path, non-matching prints discarded on the spot, erase
  reaching the store. If that is more than you want to take on, say so and leave
  it — do not half-build a biometric.
- **Yesterlight** needs a `ledger`. Find what shape, and note that
  `YesterlightController` is only constructed inside `DreamEngine`, which is
  itself Orchestrator-only — so this is a two-step: give it a Brain-side home,
  not just an import.

### 2. Retire Puente (DONE)

Module, tests, scenario fixture and the `Feature` entry deleted; every public
mention rewritten across `landing/index.html`, both READMEs, five gitbook pages,
`docs/AI_BRAIN.md`, `docs/LENSES.md` and all eleven locales of
`phone-app/src/i18n/translations.ts`.

The copy question this section asked has a real answer: **Rosetta does cover the
ear.** `ops_world_lenses.translate_heard` ("Rosetta Live") was already the live
caption path, riding a figment stage rather than a per-utterance card, and it
had superseded Puente in practice long before this. Puente knew Spanish and
English against Rosetta's dozen-plus languages and non-Latin scripts, and had no
caller outside its own test. So the copy now says Rosetta is the eye AND the
ear, which is true, rather than dropping a half nobody serves.

### 3. Every HUD item, on phone and glasses — MEASURED, 18 still open

The checker this section asked for exists: **`scripts/hud_reachability.py`**. It
asks both halves for each of the 24 declared cards — does anything a shipped
Brain can reach PRODUCE it, and does `halo-lua` have a real drawing for its
`type` — and exits non-zero while either is missing.

**The glass half is fine: 24 of 24 have a dedicated renderer branch.** The Brain
half is not:

```
NO BRAIN-SIDE PRODUCER (18 of 24)
  Always ready · Ask first · Ask it anything · Forget that · Hey Juno
  It remembers for you · Keep a moment · Live captions · Off your usual path
  Privacy Veil · Private zones · Read the room · Rewind your day
  The answer before you speak · Truth, checked live · What you owe
  Where you left it · Your inner weather
```

Verified by hand, not just by the script: every one of their producers lives in
`orchestrator/ops_*.py` — `ops_conversation`, `ops_ingest`, `ops_commitments`,
`ops_juno_attention`, `ops_world_lenses`. That is `decisions/0001` again, for
the card layer this time. Six do have Brain-side producers: Hark (`ear.py`),
Person Context, Person Dossier, World Anchor, Morning Brief, and Commitment
Drift.

Two traps for whoever closes this, both already paid for once:

- **Do not hand-roll the card dict.** `lens_hosts._drift_card` originally built
  a `{primary, detail, footer}` lookalike; `renderer.lua`'s
  `draw_commitment_drift` reads `task`, `person`, `drift_state` and `decay` and
  would have drawn it wrong while the JSON looked perfect. Call the real
  `hud/cards.py` builder.
- **Do not trust a clean run of the checker without reading it.** Its first
  draft counted `hud/cards.py` itself as a producer (`ALL_SAMPLES` is a dict of
  literal calls to every builder) and reported 0 gaps on a product with 18.
  `tests/test_hud_reachability_checker.py` pins that and the sibling bug where
  the Lua scan missed the whole `DRAW` dispatch table.

### 4. Capabilities — MEASURED, 19 open questions

It is **74** entries, not ~39. `scripts/capability_reachability.py` measures
them the same way as the other two checkers, using the field
`capabilities.py` already carries: every `Cap` names a `seam`, "the adapter file
that consumes it", so a seam outside the Brain's import closure cannot be
exercised however green the meter reads. (`installed()` asks whether a module
IMPORTS — "is the library on disk", not "does anything here use it".)

```
74 declared · 41 seams the Brain can load
19 OPEN · 13 unreachable by design · 1 documented recipe, no adapter
```

This one **exits 0 on purpose** and its two siblings do not. "A declared lens
cannot be loaded" and "a promised card cannot be drawn" have no legitimate
reading; "this adapter belongs to the Orchestrator" has several, and 13 of them
are exactly that — `wake_word`, `speaker_id`, `nlp`, `onnx_speech`, `fs_watch`,
`lan_discovery`, `mesh_range`, `home_hud`, `persona_tuning`,
`structured_concurrency` (Orchestrator), `spatial_viz` (simulator),
`frame_glasses` (another device), `mlx_train` (the REM job the Brain does not
run). Wiring those would be the regression.

The 19 open ones need triage, and they split two ways — **the fixes are
opposite, so do not batch them**:

- **Stale seam string.** `vector_search` points at `memory/vector_store.py`
  while the Brain's actual vector path is `memory/ann_index.py` (usearch), which
  `retention_live._ann_for` and the erase path both use. The capability is live
  and the meter is describing the wrong file. Fix the string.
- **Genuinely not wired.** `social_graph`, `memory_dedup`, `typed_docs`,
  `typed_models`, `facial_aus`, `causal_fusion`, `diarization`, `asr_alignment`,
  `object_tracking`, `live_interpret`, `event_bus`, `skia_render`,
  `lsl_streams`, `extism_plugins`, `wasm_plugins`, `plugin_entrypoints`,
  `structured_output`, `typed_pipeline`. Each is a decision: wire it Brain-side
  or say plainly it is Orchestrator-only and add it to `_BY_DESIGN` with the
  reason. **Do not silently move one to `_BY_DESIGN` to shrink the list** — that
  bucket is a claim, and it is the claim the next audit will check.

Note two that are their own conversation: `diarization` and `asr_alignment` are
speaker attribution, which `ear.py:129-131` records as deliberately absent.
Wiring them is the same biometric decision as Timbre in §1, not a plumbing job.

`ear.py:239-267` is the precedent for getting the RUNTIME half right — it
promotes only the caps a run genuinely drives, after an earlier blanket
promotion lied about engines that were not running.

### 5. Module reachability — the number is a DIAGNOSTIC, not a target

`scripts/lens_reachability.py` reports **199 of 390** modules reachable from the
Brain (up from 189 — the lens hosts, Scholar and their transitive imports).
**Do not try to make that 390.** Three reasons, and they matter:

- `orchestrator/*`, `simulator/*`, `main.py` and the emulator bridge are
  *supposed* to be unreachable. Making the Brain import them is precisely the
  Orchestrator resurrection that `decisions/0001`, #541 and #542 exist to
  prevent. Reachability would go up and the product would get worse.
- The metric is trivially gameable. One module that imports everything scores
  390/390 and proves nothing.
- Plenty of the 201 are other targets' code (halo/phone profiles), alternate
  backends, and CLI paths that the Brain has no business loading.

The honest goal, and the one to work to: **zero declared lenses unreachable,
zero user-facing capabilities unreachable, zero HUD cards unproducible** — then
triage the remaining modules into "should be Brain-reachable → fix" and "must
not be → record why", and put that list somewhere durable. A number that goes
up for a bad reason is worse than a number that stays put for a good one.

Two of those three now have a checker that exits non-zero while the goal is
unmet — `scripts/lens_reachability.py` (3 lenses left: Lucid Recall, Timbre,
Yesterlight) and `scripts/hud_reachability.py` (18 cards left, §3).
Capabilities is the one still measured by eye.

### Step 1 — retention (DONE, #541)

Wired Brain-side, following the `ear.py` / `glance_live.py` precedent rather
than resurrecting the `Orchestrator` the shipped Brain never builds:

- `ai_brain/server/retention_live.py` runs the existing `RetentionSweep`
  primitive against the Brain's own `MemoryDB`.
- Called from `Brain.__init__` beside the `retention_days` log prune, and again
  hourly via `Brain.start_retention_scheduler` — boot alone would mean nothing
  ages out on a machine that stays awake, and the hot ring is in-memory, so boot
  is the one moment it is guaranteed to be empty.
- Windows come from `config.py` (`retention_hot_hours` / `retention_warm_days`),
  read live. Conservatism kept: unknown age → keep, pinned → never expires,
  entities cold-forever, any failure → keep.
- `tests/test_brain_retention_boot.py` is the proof, and every assertion in it
  is a row that is GONE from a real file after a real boot. Mutation-tested.
- `decisions/0001` is now `fixed` (a new status — see `decisions/README.md`),
  and the docs' retention claims were made confident again in the same change.

### Step 2 — face recognition (DONE, #542)

InsightFace `buffalo_l` (SCRFD + ArcFace r50, ONNX/CPU) behind a new opt-in
`face` extra, plus the Brain-side consumer that did not exist — `SocialLens` was
`Orchestrator`-only, so the model alone would have been `decisions/0001` one lens
over. `ai_brain/server/face_live.py` + `POST /dreamlayer/face/{enrol,identify,
forget}` + `GET /dreamlayer/face`.

Both non-negotiables are enforced and mutation-tested: ambient is `$DL_FACE_AMBIENT`
(**not** a `BrainConfig` field — a panel toggle is a thing a release build ships
with) and is refused outright in a frozen build; a non-matching template is
discarded with no disk write, no ledger line, no log. Only ONE template is
computed per frame — the subject's — so a bystander never has a biometric
computed at all.

**Three things carried forward from #542, still open:**

1. **`models.lock` ships `insightface/buffalo_l` UNPINNED.** Capture the hashes
   on a clean, connected, trusted box (`dreamlayer models pin`) before any build
   ships the face pack. The weights the PR was verified against arrived over a
   sandbox proxy, which is not that box.
2. **0.65 / 0.08 are still uncalibrated.** The `real_model` tests pin only the
   DECLINE direction (noise, flat, empty frames). Cross-photo accuracy is
   untested — this repo has no face photographs and should not gain any.
   `social_lens/index.py` says these are placeholders until the Rig 3 perception
   bench runs an ROC over genuine/impostor pairs. Do not treat them as validated.
3. **Two guards must not drift again.** `test_logging_discipline.py` (AST,
   authoritative) and `.semgrep/dreamlayer.yml` (regex twin) contradicted each
   other about `type(exc).__name__` and cost a review round. A test now pins them
   agreeing; keep it that way.

### Step 3 — lens hosts (#543, then finished — see §0)

`ai_brain/server/lens_hosts.py` hosts seven of the twelve unreachable lenses.
#543 made them load and answer through a real `Brain(cfg)` and stopped there;
what that release actually shipped was seven lenses **nothing ever
constructed** — §0 has the full account, and it is the most instructive failure
in this file. Fed, routed and surfaced now.

The build worth knowing about: Provenance, Candor and Commitment Drift each take
a `ring` of what the wearer SAID, and the Brain had nothing of the kind (the ear
writes to `brain.index`; `WorldLensHost.ring` holds sightings). So
`BrainLenses.ring` is new. It is **hot-tier** — in-memory, bounded, swept by
`retention_live` on the same `retention_hot_hours` window — because a durable
ring would be a new permanent record of everything the wearer says. And it is
**warm-seeded** from the memory store at first use, or Candor forgets your story
on every restart and goes quiet for the wrong reason. It holds only rows the
Brain already wrote: a view, not a second copy. Erase-everything reaches it and
any held Stasis thought.

`InnerWeather` needed an adapter, not a wire: `sample()` reads
`ctx.imu_delta`/`imu_pose`/`extra` off a context object written for the glasses.
`BrainLenses.weather_tick(payload)` adapts the phone's IMU payload into that
shape. With no sensors it reports calm — it does not invent a reading.

**And that last sentence is the lens's open problem, not its safety net.** The
adapter's docstring claimed the phone "already posts heading and tilt on the
live path"; a repo-wide grep for `imu_delta` / `imu_pose` / `self_prosody`
across `phone-app/` returns nothing but the adapter's own lines. The route
(`POST /dreamlayer/weather`) and the store method (`useLensStore.weatherTick`)
are wired and tested with real motion, so the plumbing is proven — but no
screen samples the phone's accelerometer yet, so in a shipped build the lens
reports calm forever, which is indistinguishable from a working lens reporting
a calm wearer. Whoever picks this up: the missing piece is a sensor subscription
on the phone, not anything Brain-side.

### The face copy, timed to the release (still pending)

The copy is deliberately UNCHANGED, and still correct: the default install has
no `face` pack and no weights, so the shipped embedder still declines every
frame. `face` is in no `profile-*` extra, which is what keeps the sentence true.

The tripwire moved in #542 and is now sharper, so do not look for the old one.
`test_advertised_claims.py` asserts the default build's behaviour
unconditionally (conftest pins the backend absent for `no_face_double` tests, so
a developer who installs the pack locally no longer flips the assertion), and
`test_the_face_pack_is_in_no_deployment_profile` is the guard that actually
fires: **the moment `face` is added to a deployment profile, it fails.** That is
the signal to change the copy — before the build ships, not after.

What must change when it does ship (exact sentences are in the test docstrings):
- `landing/privacy.html` — "cannot return an identity at all", and "keep a face
  database" (a consented index *with face vectors* is a face database — needs
  the same precision treatment the voice-cloning line got)
- `docs/gitbook/privacy.md` — "absent from the codebase, not switched off"
- The iOS purpose strings and App Store privacy declaration — face templates are
  **biometric identifiers**, and the current declaration says camera is QR-only.
- `"No stranger face lookup"` and `"no public face database"` both **survive**
  if you stay consent-only. That is the line worth defending, because it is true.

---

## Repo landmines that cost real time this session

**`decisions/` — read it before re-raising any finding.** Findings closed without
a code change live there with evidence and the check that would overturn them.
Skim the index first; the hour may already be spent. See `CONTRIBUTING.md`.

**The docs site is GENERATED.** `letsgettoworkbro.github.io/dreamlayer-docs` is
build output. `scripts/build_gitbook_site.py` renders `docs/gitbook/*.md` from
THIS repo and deploys to that repo's `gh-pages`. **Never edit HTML in
`dreamlayer-docs`** — the next deploy silently reverts it. I did this, and only
caught it because a redeploy landed mid-PR and conflicted. Also note that repo's
default branch is `gh-pages`, not `main`.

**`Orchestrator` is not in the shipped product.** Constructed only in `main.py`
(emulator) and `simulator/`. Whole features that "live on the Orchestrator" are
invisible to users. Check before assuming any Orchestrator-owned capability
runs:
```
grep -rn "Orchestrator(" src/dreamlayer --include=*.py | grep -v /tests/
```

**Verify claims with commands, never from memory.** `decisions/0005` is a
refutation I wrote that was directionally right and specifically wrong — "no
production code constructs that class" when two modules do. It was one `grep`
from being correct and would have collapsed the first time anyone checked.

**Mutation-test every regression test.** Revert the fix; the test must fail.
Four tests written earlier in this project could not fail — one reimplemented
the production logic inside the test file. Commit first, then mutate, then
restore: a `git checkout --` during mutation testing once reverted four files
holding uncommitted work.

---

## Conventions

- **Branch:** `claude/dreamlayer-audit-k4xjv5`. It gets merged and deleted each
  round — start each new piece with
  `git fetch origin main && git checkout -B claude/dreamlayer-audit-k4xjv5 origin/main`.
  Never stack on merged history. `git remote prune origin` first if
  `--force-with-lease` complains about stale info.
- **DCO required:** `git commit -s` on every commit.
- **No `gh` CLI.** Use the `mcp__github__*` tools.
- **Squash merge.** Rebase merge returns 405 on this repo.
- **Never put the model identifier in commits, PRs, or code comments.**
- **Full gate:**
  ```
  cd host-python && python -m pytest -q -m "not hardware and not benchmark and not real_model"
  python -m ruff check src/dreamlayer && python -m mypy src/dreamlayer
  ```
  Currently **4496 passed, 22 skipped**. Takes ~4.5 min.
- **PR template** is at `.github/pull_request_template.md` — mirror its
  headings, and only tick boxes you actually verified.

---

## Recently merged (context, not work)

| PR | What |
|----|------|
| #530 | Full-stack audit: Veil leaks, face embedder failing closed, phone location leak |
| #531 | `real-models` CI job actually runs the real models; now fails on any skip |
| #533 | `decisions/` directory + validator |
| #534 | Voice-cloning claim corrected; `test_advertised_claims.py` |
| #535 | Docs claims fixed at source (`docs/gitbook/*.md`) |
| #541 | Retention wired Brain-side; `decisions/0001` closed |
| #542 | Face recognition: ArcFace behind the `face` extra + the Brain-side consumer |
| #543 | Lens reachability checker; 7 of 12 unreachable lenses hosted Brain-side |

**Open and unresolved:** the Ultracode brief at the top of this file — routes
for the seven hosted lenses (they are unreachable from the phone without them),
four lenses still unhosted, Puente's retirement, HUD coverage, capabilities. Plus
the three
carry-forwards from #542, and the face copy when a build ships the pack. Task
list item #58 (tray icons, dock-click, Learn glass) is stale and needs a build
to verify. `decisions/0001` (retention) is closed.

---

## One standing instruction from the owner

The website and knowledge base are promises. When you change what the software
does, check whether a claim on `dreamlayer.app` or the knowledge base just
became false, and fix it in the same change. `test_advertised_claims.py` pins
the ones that matter; when it fails, that is the system working, not an
obstacle.
